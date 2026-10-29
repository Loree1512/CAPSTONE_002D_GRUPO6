"""Partidas del proyecto: la lista editable con que se calcula el presupuesto.

Todo pasa por el cliente del usuario, así que RLS limita cada operación a los
proyectos propios. Un proyecto ajeno responde 404.
"""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client
from app.schemas.autenticacion import UsuarioActual
from app.schemas.partida_proyecto import (
    PartidaProyectoCrear,
    PartidaProyectoEditar,
    PartidasOrdenar,
    PlantillaAplicar,
)
from app.services import servicio_plantillas, servicio_proyectos
from app.services.motor_costos import a_decimal, estado_linea, resolver_precio, subtotal_linea
from app.services.servicio_banco import _error_http

TABLA = "proyecto_partidas"

COLUMNAS = (
    "id, proyecto_id, partida_id, categoria_id, nombre, unidad, cantidad, "
    "precio_unitario_override, origen, orden, observacion, fecha_actualizacion"
)

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


def _respuestas(client: Client, filas: List[dict]) -> List[dict]:
    ids = sorted({f["partida_id"] for f in filas if f.get("partida_id")})
    version = _version_vigente(client)
    categorias = _categorias(client)
    codigos = _codigos(client, ids)
    precios = _precios_banco(client, version["id"] if version else None, ids)
    return [_a_respuesta(f, categorias, codigos, precios) for f in filas]


def _una(client: Client, fila: dict) -> dict:
    return _respuestas(client, [fila])[0]


# --- Operaciones ---------------------------------------------------------------------

def listar(usuario_actual: UsuarioActual, proyecto_id: UUID) -> dict:
    # RLS oculta proyectos ajenos: 404.
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
    client = get_user_scoped_client(usuario_actual.access_token)

    filas = _leer_filas(client, proyecto_id)
    version = _version_vigente(client)

    aplicada = servicio_plantillas.leer(client, proyecto["plantilla_id"]) if proyecto.get("plantilla_id") else None
    sugerida = servicio_plantillas.buscar_vigente(client, proyecto["tipo_obra"], proyecto["materialidad"])

    return {
        "plantilla_aplicada": servicio_plantillas.resumen(client, aplicada),
        "plantilla_sugerida": servicio_plantillas.resumen(client, sugerida),
        "version_precios": version,
        "partidas": _respuestas(client, filas),
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
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
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

    return _una(client, response.data[0])


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
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
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
    return _una(client, response.data[0])


def eliminar(usuario_actual: UsuarioActual, proyecto_id: UUID, partida_proyecto_id: UUID) -> None:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
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


def ordenar(usuario_actual: UsuarioActual, proyecto_id: UUID, datos: PartidasOrdenar) -> List[dict]:
    servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
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
    proyecto = servicio_proyectos.leer_proyecto(usuario_actual, proyecto_id)
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

    # Con partidas existentes y sin confirmar, la RPC responde 409.
    servicio_plantillas.aplicar_a_proyecto(client, proyecto_id, plantilla["id"], datos.reemplazar)
    return listar(usuario_actual, proyecto_id)
