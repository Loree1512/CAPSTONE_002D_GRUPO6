import logging
import os

import httpx
from fastapi import HTTPException, status
from supabase import AuthError
from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthUnknownError

from app.database.supabase import get_anon_client, supabase_admin
from app.schemas.autenticacion import (
    SolicitudEstablecerContrasena,
    SolicitudInicioSesion,
    SolicitudReenviarConfirmacion,
    SolicitudRefrescar,
    SolicitudRegistro,
    UsuarioActual,
)
from app.services import servicio_perfiles

TOKEN_TYPE = "bearer"

MENSAJE_AUTH_NO_DISPONIBLE = "No se pudo validar la sesión en este momento. Inténtalo nuevamente."

logger = logging.getLogger(__name__)

# Los errores de conexión de httpx no los envuelve el SDK: llegan tal cual.
ERRORES_TRANSITORIOS = (AuthRetryableError, AuthUnknownError, httpx.RequestError)


def auth_no_disponible() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MENSAJE_AUTH_NO_DISPONIBLE)


def es_transitorio(error: Exception) -> bool:
    """Supabase Auth no respondió o falló por su lado: no dice nada del token."""
    if isinstance(error, ERRORES_TRANSITORIOS):
        return True
    # 429: límite de peticiones; 5xx: Auth caído.
    return isinstance(error, AuthApiError) and (error.status == 429 or error.status >= 500)


def _registrar_transitorio(operacion: str, error: Exception) -> None:
    # Solo el tipo: el mensaje podría incluir datos de la solicitud.
    logger.warning("Supabase Auth no disponible al %s: %s", operacion, type(error).__name__)


def registro_publico_abierto() -> bool:
    # Abierto mientras se valida la invitación por Administración. Estado final: false.
    return os.getenv("REGISTRO_PUBLICO", "true").strip().lower() not in ("false", "0", "no")


def registrar_usuario(datos: SolicitudRegistro) -> dict:
    if not registro_publico_abierto():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro público está cerrado. Pide a un administrador que te invite.",
        )

    client = get_anon_client()

    try:
        response = client.auth.sign_up({
            "email": datos.email,
            "password": datos.password,
        })
    except (AuthError, httpx.RequestError) as error:
        if es_transitorio(error):
            _registrar_transitorio("registrar", error)
            raise auth_no_disponible() from error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error.message
        ) from error

    if response.user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo registrar el usuario"
        )

    return {
        "id": response.user.id,
        "email": response.user.email,
        # Sin sesión si Supabase exige confirmar el correo primero.
        "sesion_creada": response.session is not None,
    }


def _tokens(session) -> dict:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": TOKEN_TYPE,
        "expires_in": session.expires_in,
    }


def iniciar_sesion(datos: SolicitudInicioSesion) -> dict:
    client = get_anon_client()

    try:
        response = client.auth.sign_in_with_password({
            "email": datos.email,
            "password": datos.password,
        })
    except (AuthError, httpx.RequestError) as error:
        if es_transitorio(error):
            _registrar_transitorio("iniciar sesión", error)
            raise auth_no_disponible() from error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas"
        ) from error

    # Puede fallar por correo sin confirmar, aunque la contraseña sea correcta.
    if response.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo iniciar sesión"
        )

    return _tokens(response.session)


def refrescar_sesion(datos: SolicitudRefrescar) -> dict:
    """Canjea el refresh token por una sesión nueva. Supabase lo rota: el anterior deja de servir."""
    client = get_anon_client()

    try:
        response = client.auth.refresh_session(datos.refresh_token)
    except (AuthError, httpx.RequestError) as error:
        if es_transitorio(error):
            _registrar_transitorio("refrescar la sesión", error)
            raise auth_no_disponible() from error
        # Vencido, revocado, ya usado o con formato inválido: hay que volver a entrar.
        raise _sesion_vencida() from error

    session = getattr(response, "session", None)
    if session is None:
        raise _sesion_vencida()
    return _tokens(session)


def _sesion_vencida() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesión expiró. Vuelve a iniciar sesión.",
    )


def reenviar_confirmacion(datos: SolicitudReenviarConfirmacion) -> dict:
    client = get_anon_client()

    try:
        client.auth.resend({
            "type": "signup",
            "email": datos.email,
        })
    except (AuthError, httpx.RequestError) as error:
        if es_transitorio(error):
            _registrar_transitorio("reenviar la confirmación", error)
            raise auth_no_disponible() from error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error.message
        ) from error

    return {"mensaje": "Si el correo existe, se reenvió el email de confirmación"}


YA_CONFIGURADO = "Tu cuenta ya tiene contraseña. Inicia sesión con tu correo y contraseña."
ACTIVACION_FALLIDA = ("Tu contraseña se guardó, pero no pudimos activar tu cuenta. "
                      "Vuelve a intentarlo en unos minutos.")


def establecer_contrasena(usuario_actual: UsuarioActual, datos: SolicitudEstablecerContrasena) -> dict:
    """El invitado define su contraseña con la sesión que trae el enlace.

    Supabase Auth guarda la contraseña; BuildCast solo marca el acceso como configurado,
    y únicamente después de que Auth la aceptó. Una cuenta activa no vuelve a pasar por aquí.
    """
    estado = servicio_perfiles.estado_acceso(usuario_actual)
    if estado == servicio_perfiles.EstadoAcceso.configurado:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=YA_CONFIGURADO)

    try:
        supabase_admin.auth.admin.update_user_by_id(str(usuario_actual.id), {"password": datos.password})
    except (AuthError, httpx.RequestError) as error:
        if es_transitorio(error):
            _registrar_transitorio("establecer la contraseña", error)
            raise auth_no_disponible() from error
        # Contraseña débil o rechazada por la política del proyecto. Sigue pendiente.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La contraseña no cumple los requisitos de seguridad. Usa una más larga o distinta.",
        ) from error

    # Sin la migración 008 no hay estado que marcar.
    if estado == servicio_perfiles.EstadoAcceso.desconocido:
        return {"mensaje": "Contraseña guardada."}

    try:
        supabase_admin.rpc("completar_acceso", {"p_usuario_id": str(usuario_actual.id)}).execute()
    except Exception as error:
        # Sigue pendiente: puede repetir el formulario. Solo el tipo, nunca los datos.
        logger.error("Contraseña de %s guardada sin completar el acceso: %s",
                     usuario_actual.id, type(error).__name__)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ACTIVACION_FALLIDA) from error

    return {"mensaje": "Contraseña guardada."}
