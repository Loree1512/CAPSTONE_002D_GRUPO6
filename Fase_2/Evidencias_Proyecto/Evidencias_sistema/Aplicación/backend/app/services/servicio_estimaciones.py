from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.estimacion import EstimacionCrear
from app.services import servicio_proyectos
from app.services.motor_costos import (
    CategoriaEntrada,
    ConfiguracionIncompleta,
    PartidaProyectoEntrada,
    PrecioEntrada,
    ProyectoEntrada,
    a_decimal,
    calcular_estimacion,
    configuracion_desde_parametros,
)
from app.services.resumen_proyecto import firma_partidas
from app.services.servicio_banco import _error_http, _una_fila
from app.services.servicio_configuracion import leer_parametros
from app.services.snapshot_estimacion import a_filas, armar_respuesta, armar_resumen

TABLA_ESTIMACIONES = "estimaciones"
TABLA_LINEAS = "estimacion_partidas"

COLUMNAS_RESUMEN = (
    "id, proyecto_id, fecha_creacion, version_motor, version_precio_id, version_precio, "
    "fuente_version_precio, costo_directo, costo_total, costo_m2, completa, "
    "partidas_calculadas, partidas_sin_precio, partidas_sin_cantidad"
)


def _conflicto(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)


def _no_encontrada() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Estimación no encontrada")


# --- Entradas del motor (cliente del usuario: respeta RLS) ------------------------

def _proyecto_entrada(proyecto: dict) -> ProyectoEntrada:
    return ProyectoEntrada(
        comuna=proyecto["comuna"],
        tipo_obra=proyecto["tipo_obra"],
        materialidad=proyecto["materialidad"],
        superficie_m2=a_decimal(proyecto["superficie_m2"]),
        numero_pisos=int(proyecto["numero_pisos"]),
        estandar_terminaciones=proyecto["estandar_terminaciones"],
    )


def _resolver_version(client: Client, version_id: Optional[UUID]) -> dict:
    consulta = client.table("versiones_precios").select("id, version, fuente")

    if version_id is not None:
        response = consulta.eq("id", str(version_id)).maybe_single().execute()
        if response is None or not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La versión de precios no existe.",
            )
        return response.data

    response = consulta.eq("vigente", True).limit(1).execute()
    if not response.data:
        raise _conflicto("No hay una versión de precios vigente. Publica una en el banco de precios.")
    return response.data[0]


def _partidas_proyecto(client: Client, proyecto_id) -> List[dict]:
    return (
        client
        .table("proyecto_partidas")
        .select(
            "id, partida_id, categoria_id, nombre, unidad, cantidad, "
            "precio_unitario_override, origen, orden, observacion"
        )
        .eq("proyecto_id", str(proyecto_id))
        .order("orden")
        .execute()
    ).data


def _entradas(client: Client, filas: List[dict]) -> List[PartidaProyectoEntrada]:
    # Incluye categorías no vigentes para no dejar fuera sus partidas.
    categorias = {
        f["id"]: CategoriaEntrada(f["id"], f["codigo"], f["nombre"], f["orden"])
        for f in client.table("categorias_partida").select("id, codigo, nombre, orden").execute().data
    }
    ids = sorted({f["partida_id"] for f in filas if f.get("partida_id")})
    codigos = {}
    if ids:
        codigos = {
            f["id"]: f["codigo"]
            for f in client.table("partidas").select("id, codigo").in_("id", ids).execute().data
        }

    return [
        PartidaProyectoEntrada(
            id=f["id"],
            partida_id=f.get("partida_id"),
            codigo=codigos.get(f.get("partida_id")),
            categoria=categorias[f["categoria_id"]],
            nombre=f["nombre"],
            unidad=f["unidad"],
            cantidad=a_decimal(f.get("cantidad")),
            precio_unitario_override=a_decimal(f.get("precio_unitario_override")),
            origen=f["origen"],
            orden=f["orden"],
            observacion=f.get("observacion"),
        )
        for f in filas
    ]


def _precios(client: Client, version_id: str, ids: List[str]) -> dict:
    # Solo el precio: el motor no usa el rendimiento de mano de obra.
    if not ids:
        return {}
    response = (
        client
        .table("precios_partida")
        .select("partida_id, precio_unitario, fuente")
        .eq("version_precio_id", version_id)
        .in_("partida_id", ids)
        .execute()
    )
    return {
        f["partida_id"]: PrecioEntrada(a_decimal(f["precio_unitario"]), f.get("fuente"))
        for f in response.data
    }


# --- Operaciones ---------------------------------------------------------------

def crear_estimacion(
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    datos: Optional[EstimacionCrear],
) -> dict:
    datos = datos or EstimacionCrear()

    # RLS oculta proyectos ajenos: 404.
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)

    client = get_user_scoped_client(usuario_actual.access_token)
    version = _resolver_version(client, datos.version_precio_id)

    parametros = leer_parametros(client)
    try:
        configuracion = configuracion_desde_parametros(parametros)
    except ConfiguracionIncompleta as error:
        raise _conflicto(f"La configuración del cálculo está incompleta. {error}")

    filas = _partidas_proyecto(client, proyecto_id)
    if not filas:
        raise _conflicto("El proyecto no tiene partidas. Agrega partidas antes de generar la estimación.")

    partidas = _entradas(client, filas)
    ids = sorted({p.partida_id for p in partidas if p.partida_id})

    entrada = _proyecto_entrada(proyecto)
    resultado = calcular_estimacion(
        entrada,
        partidas,
        _precios(client, version["id"], ids),
        configuracion,
        gastos_generales_pct=a_decimal(datos.gastos_generales_pct),
        utilidad_pct=a_decimal(datos.utilidad_pct),
        aplicar_factores=datos.aplicar_factores,
    )

    cabecera, lineas = a_filas(
        resultado,
        proyecto_id=str(proyecto_id),
        proyecto=entrada,
        version=version,
        parametros=parametros,
        # Misma huella que calcula el resumen del proyecto: detecta cambios posteriores.
        firma_partidas=firma_partidas(filas),
    )

    # La RPC guarda cabecera y líneas juntas.
    try:
        response = supabase_admin.rpc(
            "crear_estimacion",
            {
                "p_usuario_id": str(usuario_actual.id),
                "p_estimacion": cabecera,
                "p_partidas": lineas,
            },
        ).execute()
    except APIError as error:
        raise _error_http(error)

    # Responde con lo guardado, igual que el GET.
    return obtener_estimacion(usuario_actual, proyecto_id, _una_fila(response.data)["id"])


def listar_estimaciones(usuario_actual: UsuarioActual, proyecto_id: UUID) -> List[dict]:
    # Proyecto ajeno: 404 en vez de lista vacía.
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)

    client = get_user_scoped_client(usuario_actual.access_token)
    response = (
        client
        .table(TABLA_ESTIMACIONES)
        .select(COLUMNAS_RESUMEN)
        .eq("proyecto_id", str(proyecto_id))
        .order("fecha_creacion", desc=True)
        .execute()
    )
    return [armar_resumen(fila) for fila in response.data]


def obtener_estimacion(usuario_actual: UsuarioActual, proyecto_id: UUID, estimacion_id) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    # RLS oculta las estimaciones ajenas: 404.
    response = (
        client
        .table(TABLA_ESTIMACIONES)
        .select("*")
        .eq("id", str(estimacion_id))
        .eq("proyecto_id", str(proyecto_id))
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise _no_encontrada()

    lineas = (
        client
        .table(TABLA_LINEAS)
        .select("*")
        .eq("estimacion_id", str(estimacion_id))
        .order("orden")
        .execute()
    )
    return armar_respuesta(response.data, lineas.data)
