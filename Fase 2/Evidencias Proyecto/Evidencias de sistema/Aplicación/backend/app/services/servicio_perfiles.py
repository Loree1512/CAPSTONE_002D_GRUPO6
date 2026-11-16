"""Perfil del usuario: su rol global (administrador o profesional) y su estado de acceso."""

import logging
from enum import Enum

from postgrest.exceptions import APIError

from app.database.supabase import get_user_scoped_client
from app.schemas.autenticacion import RolGlobal, UsuarioActual

TABLA = "perfiles"
TABLA_PRINCIPALES = "administradores_principales"

# Columna o tabla inexistente: la migración correspondiente todavía no se aplicó.
ESQUEMA_PENDIENTE = {"42703", "42P01", "PGRST204", "PGRST205"}

logger = logging.getLogger(__name__)


class EstadoAcceso(str, Enum):
    configurado = "configurado"
    # Invitación abierta o no, pero sin contraseña propia: solo puede crearla.
    pendiente = "pendiente"
    # Sin la migración 008: se mantiene el comportamiento anterior.
    desconocido = "desconocido"


def estado_acceso(usuario_actual: UsuarioActual) -> EstadoAcceso:
    """Lee perfiles.acceso_configurado_at con la sesión del usuario (RLS: su propia fila)."""
    client = get_user_scoped_client(usuario_actual.access_token)
    try:
        response = (
            client
            .table(TABLA)
            .select("rol_global, acceso_configurado_at, nombre")
            .eq("id", str(usuario_actual.id))
            .maybe_single()
            .execute()
        )
    except APIError as error:
        if error.code in ESQUEMA_PENDIENTE:
            logger.warning("Estado de acceso no disponible (¿falta la migración 008?): %s", error.code)
            return EstadoAcceso.desconocido
        raise

    perfil = response.data if response is not None else None
    # Sin perfil no hay forma de saber si completó la invitación: no se le abre la API.
    if not perfil:
        return EstadoAcceso.pendiente

    usuario_actual.rol_global = (
        RolGlobal.administrador if perfil.get("rol_global") == RolGlobal.administrador.value
        else RolGlobal.profesional
    )
    usuario_actual.nombre = (perfil.get("nombre") or "").strip() or None
    return EstadoAcceso.configurado if perfil.get("acceso_configurado_at") else EstadoAcceso.pendiente


def rol_global(usuario_actual: UsuarioActual) -> RolGlobal:
    if usuario_actual.rol_global is not None:
        return usuario_actual.rol_global

    # El rol se lee de la base con el id del token ya validado, nunca del JWT.
    client = get_user_scoped_client(usuario_actual.access_token)

    try:
        response = (
            client
            .table(TABLA)
            .select("rol_global")
            .eq("id", str(usuario_actual.id))
            .maybe_single()
            .execute()
        )
    except APIError as error:
        # Sin la tabla (migración 002 pendiente) nadie es administrador.
        logger.warning("No se pudo leer el perfil de %s: %s", usuario_actual.id, error.message)
        return RolGlobal.profesional

    perfil = response.data if response is not None else None

    # Sin perfil, el usuario es profesional.
    if perfil and perfil.get("rol_global") == RolGlobal.administrador.value:
        return RolGlobal.administrador
    return RolGlobal.profesional


def es_administrador_principal(usuario_actual: UsuarioActual) -> bool:
    # RLS deja ver solo la fila propia: basta saber si existe.
    client = get_user_scoped_client(usuario_actual.access_token)

    try:
        response = (
            client
            .table(TABLA_PRINCIPALES)
            .select("perfil_id")
            .eq("perfil_id", str(usuario_actual.id))
            .maybe_single()
            .execute()
        )
    except APIError as error:
        # Sin la migración 005 no hay principales.
        logger.warning("No se pudo leer el grupo de principales: %s", error.message)
        return False

    return bool(response is not None and response.data)
