import logging
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.estimacion import CotizacionActualizar, EstimacionCrear, PlazoProfesionalDefinir
from app.schemas.proyecto import RolProyecto
from app.services import estimador_plazo, servicio_historial, servicio_proyectos
from app.services.concurrencia import en_paralelo
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
TABLA_PERFILES = "perfiles"

# Métricas y estado de la versión del modelo, por la FK estimaciones.version_modelo.
# El error medio sale de aquí (versiones_modelo.metricas), nunca escrito a mano.
EMBEBIDO_VERSION_MODELO = "versiones_modelo(metodo, estado, metricas)"

COLUMNAS_RESUMEN = (
    "id, proyecto_id, fecha_creacion, version_motor, version_precio_id, version_precio, "
    "fuente_version_precio, costo_directo, costo_total, costo_m2, completa, "
    "partidas_calculadas, partidas_sin_precio, partidas_sin_cantidad, "
    "plazo_dias, plazo_min_dias, plazo_max_dias, plazo_metodo, plazo_provisional, plazo_estado, "
    "plazo_fuera_dominio, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha, "
    "plazo_profesional_dias, plazo_profesional_estado, plazo_profesional_origen, "
    "plazo_profesional_fecha, plazo_profesional_usuario_id, "
    f"{EMBEBIDO_VERSION_MODELO}"
)

# Origen del plazo para la cotización (CHECK de la migración 010).
ORIGEN_SUGERENCIA = "sugerencia"
ORIGEN_MANUAL = "manual"
# Estados del plazo para la cotización (CHECK de la migración 010).
ESTADO_DEFINIDO = "definido"
ESTADO_POR_REVISAR = "por_revisar"

# FK de estimaciones.version_modelo: la versión del backend no está en versiones_modelo.
VERSION_NO_REGISTRADA = "version_no_registrada"

logger = logging.getLogger(__name__)


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


def _categorias(client: Client) -> dict:
    # Incluye categorías no vigentes para no dejar fuera sus partidas.
    return {
        f["id"]: CategoriaEntrada(f["id"], f["codigo"], f["nombre"], f["orden"])
        for f in client.table("categorias_partida").select("id, codigo, nombre, orden").execute().data
    }


def _codigos(client: Client, ids: List[str]) -> dict:
    if not ids:
        return {}
    return {
        f["id"]: f["codigo"]
        for f in client.table("partidas").select("id, codigo").in_("id", ids).execute().data
    }


def _entradas(filas: List[dict], categorias: dict, codigos: dict) -> List[PartidaProyectoEntrada]:
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

    # Generar o recalcular exige ser propietario o editor (lector: 403; ajeno: 404).
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)

    client = get_user_scoped_client(usuario_actual.access_token)
    hoy = estimador_plazo.fecha_chile()

    # Lecturas que no dependen entre sí, a la vez: cada una es un viaje a la base y el
    # cálculo en sí tarda menos de 1 ms. Los errores salen en el mismo orden que antes.
    version, parametros, filas, categorias, anterior, uf_del_dia = en_paralelo(
        lambda: _resolver_version(client, datos.version_precio_id),
        lambda: leer_parametros(client),
        lambda: _partidas_proyecto(client, proyecto_id),
        lambda: _categorias(client),
        # Para el historial: el costo que reemplaza esta estimación (se lee antes de guardarla).
        lambda: _estimacion_anterior(client, proyecto_id),
        lambda: _precargar_uf(hoy),
    )
    costo_anterior = {"costo_total": anterior.get("costo_total"), "costo_m2": anterior.get("costo_m2")}

    try:
        configuracion = configuracion_desde_parametros(parametros)
    except ConfiguracionIncompleta as error:
        raise _conflicto(f"La configuración del cálculo está incompleta. {error}")

    if not filas:
        raise _conflicto("El proyecto no tiene partidas. Agrega partidas antes de generar la estimación.")

    ids = sorted({f["partida_id"] for f in filas if f.get("partida_id")})
    codigos, precios = en_paralelo(
        lambda: _codigos(client, ids),
        lambda: _precios(client, version["id"], ids),
    )
    partidas = _entradas(filas, categorias, codigos)

    entrada = _proyecto_entrada(proyecto)
    resultado = calcular_estimacion(
        entrada,
        partidas,
        precios,
        configuracion,
        gastos_generales_pct=a_decimal(datos.gastos_generales_pct),
        utilidad_pct=a_decimal(datos.utilidad_pct),
        aplicar_factores=datos.aplicar_factores,
    )

    # Plazo después del costo definitivo. Nunca lanza: si falla, queda no_disponible.
    plazo = estimador_plazo.estimar(
        entrada.tipo_obra, resultado.costo_total, resultado.completa, hoy,
        buscar_uf=lambda fecha: _uf_para(fecha, hoy, uf_del_dia),
    )

    cabecera, lineas = a_filas(
        resultado,
        proyecto_id=str(proyecto_id),
        proyecto=entrada,
        version=version,
        parametros=parametros,
        # Misma huella que calcula el resumen del proyecto: detecta cambios posteriores.
        firma_partidas=firma_partidas(filas),
        observaciones=datos.observaciones,
        plazo=plazo.a_columnas(),
    )

    guardada = _guardar(usuario_actual, cabecera, lineas)

    def registrar_historial():
        servicio_historial.registrar(
            usuario_actual, proyecto_id, "estimacion_generada", "estimacion", guardada["id"],
            valores_anteriores=costo_anterior,
            valores_nuevos={k: guardada.get(k) for k in (
                "costo_total", "costo_m2", "version_precio", "completa", "plazo_dias", "version_modelo")},
        )
        # El recálculo dejó por revisar un plazo que el profesional había definido. Solo en el
        # paso de definido a por_revisar: otro recálculo sobre uno ya por revisar no repite el aviso.
        if (anterior.get("plazo_profesional_estado") == ESTADO_DEFINIDO
                and guardada.get("plazo_profesional_estado") == ESTADO_POR_REVISAR):
            servicio_historial.registrar(
                usuario_actual, proyecto_id, "plazo_profesional_por_revisar", "estimacion", guardada["id"],
                valores_anteriores={
                    "plazo_profesional_dias": anterior.get("plazo_profesional_dias"),
                    "plazo_profesional_estado": ESTADO_DEFINIDO,
                },
                valores_nuevos={
                    "plazo_profesional_dias": guardada.get("plazo_profesional_dias"),
                    "plazo_profesional_estado": ESTADO_POR_REVISAR,
                },
            )

    # El historial y la relectura de lo guardado no dependen entre sí. El registro nunca lanza.
    _, respuesta = en_paralelo(
        registrar_historial,
        # Responde con lo guardado, igual que el GET.
        lambda: _leer_estimacion(client, proyecto_id, guardada["id"]),
    )
    return respuesta


def _precargar_uf(fecha):
    """(UF del día, error). Se lee junto con lo demás; el error no se pierde: lo relanza _uf_para."""
    try:
        return estimador_plazo.buscar_uf(supabase_admin, fecha), None
    except Exception as error:  # noqa: BLE001 - el estimador decide qué hacer sin UF
        return None, error


def _uf_para(fecha, hoy, precargada):
    """Usa la UF ya leída para hoy; cualquier otra fecha se consulta como siempre."""
    if fecha != hoy:
        return estimador_plazo.buscar_uf(supabase_admin, fecha)
    valor, error = precargada
    if error is not None:
        raise error
    return valor


def _rpc_crear(usuario_actual: UsuarioActual, cabecera: dict, lineas: List[dict]):
    return supabase_admin.rpc(
        "crear_estimacion",
        {"p_usuario_id": str(usuario_actual.id), "p_estimacion": cabecera, "p_partidas": lineas},
    ).execute()


def _guardar(usuario_actual: UsuarioActual, cabecera: dict, lineas: List[dict]) -> dict:
    """La RPC guarda cabecera y líneas juntas.

    Si la versión del modelo no está registrada en la base (FK), el costo se guarda
    igual con el plazo como no disponible: el plazo no debe impedir la estimación.
    """
    try:
        try:
            response = _rpc_crear(usuario_actual, cabecera, lineas)
        except APIError as error:
            if error.code != "23503" or not cabecera.get("version_modelo"):
                raise
            logger.error("Versión de modelo %s no registrada: estimación sin plazo.", cabecera["version_modelo"])
            sin_plazo = {**cabecera, **estimador_plazo.no_disponible(VERSION_NO_REGISTRADA).a_columnas()}
            response = _rpc_crear(usuario_actual, sin_plazo, lineas)
    except APIError as error:
        # La RPC vuelve a comprobar el permiso: un lector no genera estimaciones.
        if error.code == "42501":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error.message)
        raise _error_http(error)
    return _una_fila(response.data)


def actualizar_cotizacion(
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    estimacion_id: UUID,
    datos: CotizacionActualizar,
) -> dict:
    """Nueva estimación con la observación cambiada y todo lo demás copiado.

    No pasa por el motor: montos, versión y firma quedan iguales, así que el
    estado del proyecto no cambia. La estimación anterior conserva su observación.
    """
    proyecto_id_str = str(proyecto_id)
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)

    client = get_user_scoped_client(usuario_actual.access_token)
    response = (
        client
        .table(TABLA_ESTIMACIONES)
        .select("id, observaciones")
        .eq("id", str(estimacion_id))
        .eq("proyecto_id", proyecto_id_str)
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise _no_encontrada()
    anterior = response.data.get("observaciones")

    try:
        creada = supabase_admin.rpc(
            "actualizar_cotizacion",
            {
                "p_usuario_id": str(usuario_actual.id),
                "p_estimacion_id": str(estimacion_id),
                "p_observaciones": datos.observaciones,
            },
        ).execute()
    except APIError as error:
        if error.code == "42501":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error.message)
        if error.code == "55000":
            raise _conflicto(error.message or "No se pudo actualizar la cotización.")
        raise _error_http(error)

    guardada = _una_fila(creada.data)
    servicio_historial.registrar(
        usuario_actual, proyecto_id, "cotizacion_actualizada", "estimacion", guardada["id"],
        valores_anteriores={"observaciones": anterior},
        valores_nuevos={"observaciones": guardada.get("observaciones")},
    )
    return _leer_estimacion(client, proyecto_id, guardada["id"])


def definir_plazo_profesional(
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    estimacion_id: UUID,
    datos: PlazoProfesionalDefinir,
) -> dict:
    """Nueva estimación con el plazo para la cotización definido y todo lo demás copiado.

    Es la única forma de fijar ese plazo: acción explícita del profesional, con un valor
    escrito o con la sugerencia del modelo de esa misma estimación. No ejecuta el modelo
    ni toca su sugerencia; la estimación anterior conserva lo suyo.
    """
    # Propietario o editor (lector: 403; ajeno: 404), como generar o actualizar.
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)

    client = get_user_scoped_client(usuario_actual.access_token)
    response = (
        client
        .table(TABLA_ESTIMACIONES)
        .select("id, plazo_profesional_dias, plazo_profesional_estado")
        .eq("id", str(estimacion_id))
        .eq("proyecto_id", str(proyecto_id))
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise _no_encontrada()
    anterior = response.data

    # Con la sugerencia, el valor lo toma la RPC de plazo_dias de esa fila, no del cliente.
    origen = ORIGEN_SUGERENCIA if datos.usar_sugerencia else ORIGEN_MANUAL
    try:
        creada = supabase_admin.rpc(
            "definir_plazo_profesional",
            {
                "p_usuario_id": str(usuario_actual.id),
                "p_estimacion_id": str(estimacion_id),
                "p_dias": None if datos.usar_sugerencia else datos.dias,
                "p_origen": origen,
            },
        ).execute()
    except APIError as error:
        if error.code == "42501":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error.message)
        if error.code == "55000":
            raise _conflicto(error.message or "No se pudo definir el plazo para la cotización.")
        raise _error_http(error)

    guardada = _una_fila(creada.data)
    servicio_historial.registrar(
        usuario_actual, proyecto_id, "plazo_profesional_definido", "estimacion", guardada["id"],
        valores_anteriores={
            "plazo_profesional_dias": anterior.get("plazo_profesional_dias"),
            "plazo_profesional_estado": anterior.get("plazo_profesional_estado") or "sin_definir",
        },
        valores_nuevos={
            "plazo_profesional_dias": guardada.get("plazo_profesional_dias"),
            "plazo_profesional_origen": guardada.get("plazo_profesional_origen"),
        },
    )
    return _leer_estimacion(client, proyecto_id, guardada["id"])


def _estimacion_anterior(client: Client, proyecto_id) -> dict:
    """Costo y plazo profesional de la última estimación guardada, para el historial.

    En la primera el costo queda en null: así se distingue de los eventos antiguos, que
    no guardaban valores anteriores.
    """
    filas = (
        client
        .table(TABLA_ESTIMACIONES)
        .select("costo_total, costo_m2, plazo_profesional_dias, plazo_profesional_estado")
        .eq("proyecto_id", str(proyecto_id))
        .order("fecha_creacion", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    ).data
    return filas[0] if filas else {}


def listar_estimaciones(usuario_actual: UsuarioActual, proyecto_id: UUID) -> List[dict]:
    # Cualquier miembro consulta. Proyecto ajeno: 404 en vez de lista vacía.
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
    # Cualquier miembro consulta; quien no pertenece al proyecto recibe 404.
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)

    client = get_user_scoped_client(usuario_actual.access_token)
    return _leer_estimacion(client, proyecto_id, estimacion_id)


def _nombre_usuario(usuario_id) -> Optional[str]:
    """Nombre o correo de quien definió el plazo para la cotización.

    Con service role, igual que servicio_miembros._perfiles: cada usuario solo ve su
    propio perfil. Si falla, la estimación se responde igual, sin el nombre.
    """
    if not usuario_id:
        return None
    try:
        filas = (
            supabase_admin.table(TABLA_PERFILES).select("id, email, nombre").eq("id", str(usuario_id)).execute()
        ).data
    except APIError as error:
        logger.error("No se pudo leer quién definió el plazo: %s", error.message)
        return None
    perfil = filas[0] if filas else {}
    return perfil.get("nombre") or perfil.get("email")


def _leer_estimacion(client: Client, proyecto_id, estimacion_id) -> dict:
    def cabecera():
        return (
            client
            .table(TABLA_ESTIMACIONES)
            .select(f"*, {EMBEBIDO_VERSION_MODELO}")
            .eq("id", str(estimacion_id))
            .eq("proyecto_id", str(proyecto_id))
            .maybe_single()
            .execute()
        )

    def lineas():
        return (
            client
            .table(TABLA_LINEAS)
            .select("*")
            .eq("estimacion_id", str(estimacion_id))
            .order("orden")
            .execute()
        )

    # Las líneas se piden por el id de la estimación, sin esperar la cabecera: dos viajes a la vez.
    response, filas = en_paralelo(cabecera, lineas)
    # RLS oculta además las estimaciones ajenas: 404.
    if response is None or not response.data:
        raise _no_encontrada()
    definido_por = _nombre_usuario(response.data.get("plazo_profesional_usuario_id"))
    return armar_respuesta(response.data, filas.data, definido_por)
