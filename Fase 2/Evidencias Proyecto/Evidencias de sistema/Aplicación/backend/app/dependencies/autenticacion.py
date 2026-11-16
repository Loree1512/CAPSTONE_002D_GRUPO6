import logging
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AuthError

from app.database.supabase import get_anon_client
from app.schemas.autenticacion import RolGlobal, UsuarioActual
from app.services import servicio_autenticacion, servicio_perfiles

# Desactivamos el error automático para devolver 401 si falta Authorization.
bearer_scheme = HTTPBearer(auto_error=False)

logger = logging.getLogger(__name__)


def _token_invalido() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )


ACCESO_PENDIENTE = "Completa tu invitación creando tu contraseña antes de continuar."
# El frontend lo lee para llevar a la persona a «Crea tu contraseña».
CABECERA_ACCESO = "X-BuildCast-Acceso"


def obtener_sesion(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UsuarioActual:
    """Token válido, sin mirar el estado de acceso. Solo para /yo y establecer-contrasena."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    client = get_anon_client()

    # 401 solo si Auth rechaza el token. Si Auth no responde es 503: el frontend
    # no debe cerrar la sesión por eso. Cualquier otra excepción sigue como 500.
    try:
        response = client.auth.get_user(token)
    except (AuthError, httpx.RequestError) as error:
        if servicio_autenticacion.es_transitorio(error):
            logger.warning("Supabase Auth no disponible al validar el token: %s", type(error).__name__)
            raise servicio_autenticacion.auth_no_disponible() from error
        raise _token_invalido() from error

    if response is None or response.user is None:
        raise _token_invalido()

    return UsuarioActual(
        id=response.user.id,
        email=response.user.email,
        access_token=token,
    )


def obtener_usuario_actual(usuario: UsuarioActual = Depends(obtener_sesion)) -> UsuarioActual:
    # Abrir el enlace de invitación ya da una sesión válida de Supabase; hasta crear la
    # contraseña, esa sesión no sirve para el resto de la API.
    if servicio_perfiles.estado_acceso(usuario) == servicio_perfiles.EstadoAcceso.pendiente:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCESO_PENDIENTE,
            headers={CABECERA_ACCESO: "pendiente"},
        )
    return usuario


def es_administrador(usuario_actual: UsuarioActual) -> bool:
    # Única autorización global: perfiles.rol_global, leído de la base.
    return servicio_perfiles.rol_global(usuario_actual) == RolGlobal.administrador


def _exigir(permitido, mensaje: str):
    def dependencia(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)) -> UsuarioActual:
        if not permitido(usuario_actual):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=mensaje)
        return usuario_actual

    return dependencia


exigir_editor_banco = _exigir(es_administrador, "No tienes permisos para editar el banco de precios.")
exigir_editor_configuracion = _exigir(es_administrador, "No tienes permisos para editar la configuración del cálculo.")
exigir_editor_plantillas = _exigir(es_administrador, "No tienes permisos para editar las plantillas de presupuesto.")
exigir_administrador = _exigir(es_administrador, "Solo un administrador puede gestionar usuarios.")
