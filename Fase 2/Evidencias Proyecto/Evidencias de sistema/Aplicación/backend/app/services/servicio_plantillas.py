"""Plantillas de presupuesto: partidas iniciales por tipo de obra + materialidad.

Una plantilla solo propone partidas. Al aplicarla se copian al proyecto, así
que editarla después no cambia proyectos ya creados.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.plantilla import PlantillaCrear, PlantillaEditar, PlantillaPartidasGuardar
from app.services.servicio_banco import _error_http

TABLA_PLANTILLAS = "plantillas_presupuesto"
TABLA_PLANTILLA_PARTIDAS = "plantilla_partidas"

COLUMNAS_PLANTILLA = "id, nombre, tipo_obra, materialidad, vigente, fecha_actualizacion"

MENSAJES = {
    "23505": "Ya existe una plantilla vigente para ese tipo de obra y materialidad.",
}


def _no_encontrada() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La plantilla no existe.")


def _a_resumen(fila: dict, cantidad_partidas: int) -> dict:
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "tipo_obra": fila["tipo_obra"],
        "materialidad": fila["materialidad"],
        "vigente": fila["vigente"],
        "cantidad_partidas": cantidad_partidas,
        "fecha_actualizacion": fila.get("fecha_actualizacion"),
    }


def _contar_partidas(client: Client, ids: List[str]) -> dict:
    if not ids:
        return {}
    response = (
        client
        .table(TABLA_PLANTILLA_PARTIDAS)
        .select("plantilla_id")
        .in_("plantilla_id", ids)
        .execute()
    )
    conteo: dict = {}
    for fila in response.data:
        conteo[fila["plantilla_id"]] = conteo.get(fila["plantilla_id"], 0) + 1
    return conteo


def _leer_plantilla(client: Client, plantilla_id) -> dict:
    response = (
        client
        .table(TABLA_PLANTILLAS)
        .select(COLUMNAS_PLANTILLA)
        .eq("id", str(plantilla_id))
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        raise _no_encontrada()
    return response.data


def _partidas_de(client: Client, plantilla_id) -> List[dict]:
    """Partidas de la plantilla con los datos del catálogo, en orden."""
    filas = (
        client
        .table(TABLA_PLANTILLA_PARTIDAS)
        .select("partida_id, orden, cantidad_sugerida")
        .eq("plantilla_id", str(plantilla_id))
        .order("orden")
        .execute()
    ).data
    if not filas:
        return []

    catalogo = (
        client
        .table("partidas")
        .select("id, categoria_id, codigo, nombre, unidad, vigente")
        .in_("id", [f["partida_id"] for f in filas])
        .execute()
    ).data
    por_id = {p["id"]: p for p in catalogo}

    return [
        {
            "partida_id": f["partida_id"],
            "orden": f["orden"],
            "cantidad_sugerida": f.get("cantidad_sugerida"),
            "codigo": por_id[f["partida_id"]]["codigo"],
            "nombre": por_id[f["partida_id"]]["nombre"],
            "unidad": por_id[f["partida_id"]]["unidad"],
            "categoria_id": por_id[f["partida_id"]]["categoria_id"],
            "vigente": por_id[f["partida_id"]]["vigente"],
        }
        for f in filas
        if f["partida_id"] in por_id
    ]


# --- Uso desde proyectos (cliente del usuario: respeta RLS) ------------------------

def buscar_vigente(client: Client, tipo_obra: str, materialidad: str) -> Optional[dict]:
    """Plantilla vigente que calza exacto con tipo de obra + materialidad."""
    response = (
        client
        .table(TABLA_PLANTILLAS)
        .select(COLUMNAS_PLANTILLA)
        .eq("tipo_obra", tipo_obra)
        .eq("materialidad", materialidad)
        .eq("vigente", True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def resumen(client: Client, plantilla: Optional[dict]) -> Optional[dict]:
    if plantilla is None:
        return None
    conteo = _contar_partidas(client, [plantilla["id"]])
    return _a_resumen(plantilla, conteo.get(plantilla["id"], 0))


def leer(client: Client, plantilla_id) -> Optional[dict]:
    try:
        return _leer_plantilla(client, plantilla_id)
    except HTTPException:
        return None


def filas_desde_plantilla(partidas_plantilla: List[dict]) -> List[dict]:
    """Copia las partidas de la plantilla como filas nuevas del proyecto.

    Son valores, no referencias: la plantilla puede cambiar después sin tocar
    el proyecto. Las partidas dadas de baja no se proponen.
    """
    vigentes = [p for p in partidas_plantilla if p.get("vigente", True)]
    return [
        {
            "partida_id": str(p["partida_id"]),
            "categoria_id": p["categoria_id"],
            "nombre": p["nombre"],
            "unidad": p["unidad"],
            # La cantidad sugerida es opcional; si no hay, queda por definir.
            "cantidad": None if p.get("cantidad_sugerida") is None else str(p["cantidad_sugerida"]),
            "orden": i,
        }
        for i, p in enumerate(vigentes, start=1)
    ]


def aplicar_a_proyecto(client: Client, proyecto_id, plantilla_id, reemplazar: bool) -> List[dict]:
    """Copia la plantilla al proyecto en una sola transacción (RPC con RLS)."""
    filas = filas_desde_plantilla(_partidas_de(client, plantilla_id))
    try:
        response = client.rpc(
            "aplicar_plantilla_proyecto",
            {
                "p_proyecto_id": str(proyecto_id),
                "p_plantilla_id": str(plantilla_id),
                "p_partidas": filas,
                "p_reemplazar": reemplazar,
            },
        ).execute()
    except APIError as error:
        if error.code == "55000":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message)
        raise _error_http(error)
    return response.data or []


def crear_proyecto_con_plantilla(client: Client, proyecto: dict, plantilla_id) -> dict:
    """Crea el proyecto y copia la plantilla en una sola transacción (RPC con RLS)."""
    filas = filas_desde_plantilla(_partidas_de(client, plantilla_id))
    try:
        response = client.rpc(
            "crear_proyecto_con_plantilla",
            {"p_proyecto": proyecto, "p_plantilla_id": str(plantilla_id), "p_partidas": filas},
        ).execute()
    except APIError as error:
        raise _error_http(error)
    return response.data[0] if isinstance(response.data, list) else response.data


# --- Administración ---------------------------------------------------------------

def listar(usuario_actual: UsuarioActual) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)
    filas = (
        client
        .table(TABLA_PLANTILLAS)
        .select(COLUMNAS_PLANTILLA)
        .order("tipo_obra")
        .order("materialidad")
        .execute()
    ).data
    conteo = _contar_partidas(client, [f["id"] for f in filas])
    return [_a_resumen(f, conteo.get(f["id"], 0)) for f in filas]


def obtener(usuario_actual: UsuarioActual, plantilla_id: UUID) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)
    return _detalle(client, plantilla_id)


def _detalle(client: Client, plantilla_id) -> dict:
    plantilla = _leer_plantilla(client, plantilla_id)
    partidas = _partidas_de(client, plantilla_id)
    return {**_a_resumen(plantilla, len(partidas)), "partidas": partidas}


def crear(datos: PlantillaCrear) -> dict:
    try:
        response = (
            supabase_admin
            .table(TABLA_PLANTILLAS)
            .insert(datos.model_dump(mode="json"))
            .execute()
        )
    except APIError as error:
        raise _error_http(error, MENSAJES)
    return _detalle(supabase_admin, response.data[0]["id"])


def editar(plantilla_id: UUID, datos: PlantillaEditar) -> dict:
    _leer_plantilla(supabase_admin, plantilla_id)
    cambios = datos.model_dump(mode="json", exclude_unset=True)
    if cambios:
        try:
            (
                supabase_admin
                .table(TABLA_PLANTILLAS)
                .update(cambios)
                .eq("id", str(plantilla_id))
                .execute()
            )
        except APIError as error:
            raise _error_http(error, MENSAJES)
    return _detalle(supabase_admin, plantilla_id)


def guardar_partidas(plantilla_id: UUID, datos: PlantillaPartidasGuardar) -> dict:
    # Lista completa en su orden: sirve para agregar, quitar y reordenar.
    filas = [
        {
            "partida_id": str(p.partida_id),
            "orden": i,
            "cantidad_sugerida": None if p.cantidad_sugerida is None else str(p.cantidad_sugerida),
        }
        for i, p in enumerate(datos.partidas, start=1)
    ]
    try:
        supabase_admin.rpc(
            "guardar_partidas_plantilla",
            {"p_plantilla_id": str(plantilla_id), "p_partidas": filas},
        ).execute()
    except APIError as error:
        raise _error_http(error, {"23505": "Una partida está repetida en la plantilla."})
    return _detalle(supabase_admin, plantilla_id)
