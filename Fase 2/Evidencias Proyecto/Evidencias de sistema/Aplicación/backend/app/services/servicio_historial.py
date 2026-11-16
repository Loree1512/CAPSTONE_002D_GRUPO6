"""Historial del proyecto: quién hizo qué y cuándo. Solo se anexa."""

import logging
from typing import Dict, Iterable, List, Optional, Tuple

from postgrest.exceptions import APIError

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual

TABLA = "historial_proyecto"
TABLA_PERFILES = "perfiles"

COLUMNAS = (
    "id, accion, entidad, entidad_id, usuario_id, usuario_email, "
    "valores_anteriores, valores_nuevos, origen, fecha"
)

logger = logging.getLogger(__name__)


def registrar(
    usuario_actual: UsuarioActual,
    proyecto_id,
    accion: str,
    entidad: str,
    entidad_id=None,
    valores_anteriores: Optional[dict] = None,
    valores_nuevos: Optional[dict] = None,
) -> None:
    """Anexa un evento. Se llama después de la operación, ya autorizada y hecha."""
    fila = {
        "proyecto_id": str(proyecto_id),
        "usuario_id": str(usuario_actual.id),
        "usuario_email": usuario_actual.email,
        "accion": accion,
        "entidad": entidad,
        "entidad_id": None if entidad_id is None else str(entidad_id),
        "valores_anteriores": valores_anteriores,
        "valores_nuevos": valores_nuevos,
        "origen": "api",
    }

    try:
        supabase_admin.table(TABLA).insert(fila).execute()
    except Exception as error:
        # La operación ya se hizo: no se le responde un error al usuario por el registro.
        logger.error("No se pudo registrar %s en el historial del proyecto %s: %s",
                     accion, proyecto_id, getattr(error, "message", error))


def _mismo_valor(a, b) -> bool:
    # La base devuelve numeric como texto o número: 20, 20.0 y "20" son lo mismo.
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def diferencias(antes: dict, despues: dict, campos: Iterable[str]) -> Tuple[dict, dict]:
    """Solo los campos que cambian: (valores anteriores, valores nuevos)."""
    distintos = [c for c in campos if not _mismo_valor(antes.get(c), despues.get(c))]
    return {c: antes.get(c) for c in distintos}, {c: despues.get(c) for c in distintos}


def _nombres(ids: List[str]) -> Dict[str, Optional[str]]:
    # Con service role: cada usuario solo ve su propio perfil.
    if not ids:
        return {}
    try:
        filas = supabase_admin.table(TABLA_PERFILES).select("id, nombre").in_("id", ids).execute().data
    except APIError as error:
        logger.error("No se pudieron leer los nombres del historial: %s", error.message)
        return {}
    return {str(f["id"]): f.get("nombre") for f in filas}


def listar(usuario_actual: UsuarioActual, proyecto: dict, limite: int) -> List[dict]:
    """Eventos del proyecto, el más reciente primero. El permiso ya viene comprobado."""
    client = get_user_scoped_client(usuario_actual.access_token)
    filas = (
        client
        .table(TABLA)
        .select(COLUMNAS)
        .eq("proyecto_id", str(proyecto["id"]))
        .order("fecha", desc=True)
        # Desempata eventos de la misma transacción.
        .order("id", desc=True)
        .limit(limite)
        .execute()
    ).data

    nombres = _nombres(sorted({str(f["usuario_id"]) for f in filas if f.get("usuario_id")}))
    return [{**f, "usuario_nombre": nombres.get(str(f.get("usuario_id")))} for f in filas]
