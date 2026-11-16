"""Partidas del proyecto: la lista editable con que se calcula el presupuesto.

Consultar exige pertenecer al proyecto; modificar, ser propietario o editor. Quien
no pertenece recibe 404 y un lector que intenta modificar, 403. Todo pasa por el
cliente del usuario, así que RLS sigue limitando cada operación.
"""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client
from app.schemas.autenticacion import UsuarioActual
from app.schemas.proyecto import RolProyecto
from app.schemas.partida_proyecto import (
    PartidaProyectoCrear,
    PartidaProyectoEditar,
    PartidasOrdenar,
    PlantillaAplicar,
)
from app.services import servicio_historial, servicio_plantillas, servicio_proyectos
from app.services.concurrencia import en_paralelo
from app.services.motor_costos import a_decimal, estado_linea, resolver_precio, subtotal_linea
from app.services.servicio_banco import _error_http

TABLA = "proyecto_partidas"

COLUMNAS = (
    "id, proyecto_id, partida_id, categoria_id, nombre, unidad, cantidad, "
    "precio_unitario_override, origen, orden, observacion, fecha_actualizacion"
)

ENTIDAD = "proyecto_partida"
# Lo que identifica una partida en el historial al agregarla o quitarla.
CAMPOS_HISTORIAL = ("nombre", "unidad", "cantidad", "origen")

MENSAJES = {
    "23503": "La categoría o la partida indicada no existe.",
    "23514": "Los datos de la partida no son válidos.",
}


def _no_encontrada() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partida no encontrada")


def _invalida(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detalle)


# --- Datos de apoyo -----------------------------------------------------------------

def _categorias(client: Client) -> Dict[int, dict]:
    # Incluye no vigentes: una partida del proyecto puede seguir en una.
    filas = client.table("categorias_partida").select("id, codigo, nombre, orden, vigente").execute().data
    return {f["id"]: f for f in filas}


def _version_vigente(client: Client) -> Optional[dict]:
    response = (
        client
        .table("versiones_precios")
        .select("id, version")
        .eq("vigente", True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def _codigos(client: Client, ids: List[str]) -> Dict[str, str]:
    if not ids:
        return {}
    filas = client.table("partidas").select("id, codigo").in_("id", ids).execute().data
    return {f["id"]: f["codigo"] for f in filas}


def _precios_banco(client: Client, version_id: Optional[str], ids: List[str]) -> Dict[str, object]:
    if not version_id or not ids:
        return {}
    filas = (
        client
        .table("precios_partida")
        .select("partida_id, precio_unitario")
        .eq("version_precio_id", version_id)
        .in_("partida_id", ids)
        .execute()
    ).data
    return {f["partida_id"]: f["precio_unitario"] for f in filas}


def _leer_filas(client: Client, proyecto_id) -> List[dict]:
    return (
        client
        .table(TABLA)
        .select(COLUMNAS)
        .eq("proyecto_id", str(proyecto_id))
        .order("orden")
        .execute()
    ).data


def _a_respuesta(fila: dict, categorias: Dict[int, dict], codigos: dict, precios: dict) -> dict:
    categoria = categorias.get(fila["categoria_id"], {})
    partida_id = fila.get("partida_id")
    cantidad = a_decimal(fila.get("cantidad"))
    override = a_decimal(fila.get("precio_unitario_override"))
    banco = a_decimal(precios.get(partida_id)) if partida_id else None
    precio = resolver_precio(override, banco)
    estado = estado_linea(cantidad, precio)

    return {
        **{k: fila.get(k) for k in (
            "id", "proyecto_id", "partida_id", "categoria_id", "nombre", "unidad", "cantidad",
            "precio_unitario_override", "origen", "orden", "observacion", "fecha_actualizacion",
        )},
        "codigo": codigos.get(partida_id) if partida_id else None,
        "categoria_codigo": categoria.get("codigo", ""),
        "categoria_nombre": categoria.get("nombre", ""),
        "categoria_orden": categoria.get("orden", 0),
        "precio_banco": banco,
        "precio_unitario": precio,
        # Mismo redondeo que el motor.
        "subtotal": subtotal_linea(cantidad, precio),
        "estado": estado,
    }


_NO_LEIDA = object()


def _respuestas(client: Client, filas: List[dict], version=_NO_LEIDA, categorias=None) -> List[dict]:
    """Respuestas con precio y categoría. Quien ya leyó la versión o las categorías las pasa."""
    ids = sorted({f["partida_id"] for f in filas if f.get("partida_id")})
    # Tres lecturas independientes a la vez; el precio necesita la versión, así que va después.
    version, categorias, codigos = en_paralelo(
        (lambda: version) if version is not _NO_LEIDA else (lambda: _version_vigente(client)),
        (lambda: categorias) if categorias is not None else (lambda: _categorias(client)),
        lambda: _codigos(client, ids),
    )
    precios = _precios_banco(client, version["id"] if version else None, ids)
    return [_a_respuesta(f, categorias, codigos, precios) for f in filas]


def _una(client: Client, fila: dict) -> dict:
    return _respuestas(client, [fila])[0]


# --- Operaciones ---------------------------------------------------------------------

def listar(usuario_actual: UsuarioActual, proyecto_id: UUID) -> dict:
    # Cualquier miembro consulta; quien no pertenece recibe 404.
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
    client = get_user_scoped_client(usuario_actual.access_token)

    # Lecturas independientes a la vez (cada una es un viaje a la base).
    filas, version, categorias, aplicada, sugerida = en_paralelo(
        lambda: _leer_filas(client, proyecto_id),
        lambda: _version_vigente(client),
        lambda: _categorias(client),
        lambda: servicio_plantillas.leer(client, proyecto["plantilla_id"]) if proyecto.get("plantilla_id") else None,
        lambda: servicio_plantillas.buscar_vigente(client, proyecto["tipo_obra"], proyecto["materialidad"]),
    )
    resumen_aplicada, resumen_sugerida, partidas = en_paralelo(
        lambda: servicio_plantillas.resumen(client, aplicada),
        lambda: servicio_plantillas.resumen(client, sugerida),
        lambda: _respuestas(client, filas, version, categorias),
    )

    return {
        "plantilla_aplicada": resumen_aplicada,
        "plantilla_sugerida": resumen_sugerida,
        "version_precios": version,
        "partidas": partidas,
    }


def _siguiente_orden(client: Client, proyecto_id) -> int:
    response = (
        client
        .table(TABLA)
        .select("orden")
        .eq("proyecto_id", str(proyecto_id))
        .order("orden", desc=True)
        .limit(1)
        .execute()
    )
    return (response.data[0]["orden"] + 1) if response.data else 1


def _categoria_valida(client: Client, categoria_id: int) -> None:
    categoria = _categorias(client).get(categoria_id)
    if categoria is None or not categoria.get("vigente", True):
        raise _invalida("La categoría no existe.")


def crear(usuario_actual: UsuarioActual, proyecto_id: UUID, datos: PartidaProyectoCrear) -> dict:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)
    client = get_user_scoped_client(usuario_actual.access_token)

    fila = {
        "proyecto_id": str(proyecto_id),
        "origen": datos.origen,
        "cantidad": None if datos.cantidad is None else str(datos.cantidad),
        "precio_unitario_override": (
            None if datos.precio_unitario_override is None else str(datos.precio_unitario_override)
        ),
        "observacion": (datos.observacion or "").strip() or None,
        "orden": _siguiente_orden(client, proyecto_id),
    }

    if datos.origen == "catalogo":
        response = (
            client
            .table("partidas")
            .select("id, categoria_id, nombre, unidad, vigente")
            .eq("id", str(datos.partida_id))
            .maybe_single()
            .execute()
        )
        partida = response.data if response is not None else None
        if not partida or not partida["vigente"]:
            raise _invalida("La partida del catálogo no existe o está dada de baja.")
        # Se copian nombre y unidad: editarlos no toca el catálogo.
        fila.update(
            partida_id=partida["id"],
            categoria_id=partida["categoria_id"],
            nombre=datos.nombre or partida["nombre"],
            unidad=partida["unidad"],
        )
    else:
        _categoria_valida(client, datos.categoria_id)
        # Exclusiva del proyecto: no se agrega al catálogo global.
        fila.update(
            partida_id=None,
            categoria_id=datos.categoria_id,
            nombre=datos.nombre,
            unidad=datos.unidad,
        )

    try:
        response = client.table(TABLA).insert(fila).execute()
    except APIError as error:
        raise _error_http(error, MENSAJES)

    creada = response.data[0]
    # El historial (que no lanza) y la respuesta no dependen entre sí.
    _, respuesta = en_paralelo(
        lambda: servicio_historial.registrar(usuario_actual, proyecto_id, "partida_agregada", ENTIDAD, creada["id"],
                                             valores_nuevos={k: creada.get(k) for k in CAMPOS_HISTORIAL}),
        lambda: _una(client, creada),
    )
    return respuesta


def _leer_fila(client: Client, proyecto_id, partida_proyecto_id) -> dict:
    response = (
        client
        .table(TABLA)
        .select(COLUMNAS)
        .eq("id", str(partida_proyecto_id))
        .eq("proyecto_id", str(proyecto_id))
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise _no_encontrada()
    return response.data


def editar(
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    partida_proyecto_id: UUID,
    datos: PartidaProyectoEditar,
) -> dict:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)
    client = get_user_scoped_client(usuario_actual.access_token)
    actual = _leer_fila(client, proyecto_id, partida_proyecto_id)

    cambios = datos.model_dump(mode="json", exclude_unset=True)

    # Unidad y categoría del catálogo se mantienen: el precio del banco es por esa unidad.
    if actual.get("partida_id") and ({"unidad", "categoria_id"} & cambios.keys()):
        if cambios.get("unidad", actual["unidad"]) != actual["unidad"] or \
                cambios.get("categoria_id", actual["categoria_id"]) != actual["categoria_id"]:
            raise _invalida("La unidad y la categoría de una partida del catálogo no se cambian en el proyecto.")
    if "categoria_id" in cambios:
        if cambios["categoria_id"] is None:
            raise _invalida("La categoría es obligatoria.")
        _categoria_valida(client, cambios["categoria_id"])

    if not cambios:
        return _una(client, actual)

    try:
        response = (
            client
            .table(TABLA)
            .update(cambios)
            .eq("id", str(partida_proyecto_id))
            .eq("proyecto_id", str(proyecto_id))
            .execute()
        )
    except APIError as error:
        raise _error_http(error, MENSAJES)

    if not response.data:
        raise _no_encontrada()

    editada = response.data[0]
    anteriores, nuevos = servicio_historial.diferencias(actual, editada, cambios.keys())
    if not nuevos:
        return _una(client, editada)
    # El historial (que no lanza) y la respuesta no dependen entre sí.
    _, respuesta = en_paralelo(
        # El nombre identifica la partida aunque no haya cambiado.
        lambda: servicio_historial.registrar(usuario_actual, proyecto_id, "partida_editada", ENTIDAD,
                                             partida_proyecto_id, anteriores, {**nuevos, "nombre": editada.get("nombre")}),
        lambda: _una(client, editada),
    )
    return respuesta


def eliminar(usuario_actual: UsuarioActual, proyecto_id: UUID, partida_proyecto_id: UUID) -> None:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)
    client = get_user_scoped_client(usuario_actual.access_token)

    response = (
        client
        .table(TABLA)
        .delete()
        .eq("id", str(partida_proyecto_id))
        .eq("proyecto_id", str(proyecto_id))
        .execute()
    )
    if not response.data:
        raise _no_encontrada()

    eliminada = response.data[0]
    servicio_historial.registrar(usuario_actual, proyecto_id, "partida_eliminada", ENTIDAD, partida_proyecto_id,
                                 valores_anteriores={k: eliminada.get(k) for k in CAMPOS_HISTORIAL})


def ordenar(usuario_actual: UsuarioActual, proyecto_id: UUID, datos: PartidasOrdenar) -> List[dict]:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)
    client = get_user_scoped_client(usuario_actual.access_token)
    try:
        response = client.rpc(
            "ordenar_partidas_proyecto",
            {"p_proyecto_id": str(proyecto_id), "p_ids": [str(i) for i in datos.ids]},
        ).execute()
    except APIError as error:
        raise _error_http(error)
    return _respuestas(client, response.data or [])


def aplicar_plantilla(usuario_actual: UsuarioActual, proyecto_id: UUID, datos: PlantillaAplicar) -> dict:
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)
    client = get_user_scoped_client(usuario_actual.access_token)

    if datos.plantilla_id is not None:
        plantilla = servicio_plantillas.leer(client, datos.plantilla_id)
        if plantilla is None or not plantilla["vigente"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La plantilla no existe o no está vigente.")
    else:
        plantilla = servicio_plantillas.buscar_vigente(client, proyecto["tipo_obra"], proyecto["materialidad"])
        if plantilla is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No hay plantilla vigente para {proyecto['tipo_obra']} · {proyecto['materialidad']}.",
            )

    # Sin reemplazar, la RPC exige que no haya partidas (si hay, responde 409).
    anteriores = len(_leer_filas(client, proyecto_id)) if datos.reemplazar else 0

    servicio_plantillas.aplicar_a_proyecto(client, proyecto_id, plantilla["id"], datos.reemplazar)

    resultado = listar(usuario_actual, proyecto_id)
    servicio_historial.registrar(
        usuario_actual, proyecto_id, "plantilla_aplicada", "plantilla", plantilla["id"],
        valores_anteriores={"partidas": anteriores} if anteriores else None,
        valores_nuevos={"nombre": plantilla.get("nombre"), "partidas": len(resultado["partidas"])},
    )
    return resultado
