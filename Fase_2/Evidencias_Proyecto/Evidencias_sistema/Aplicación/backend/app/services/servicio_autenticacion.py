from fastapi import HTTPException, status
from supabase import AuthError

from app.database.supabase import get_anon_client
from app.schemas.autenticacion import (
    SolicitudInicioSesion,
    SolicitudReenviarConfirmacion,
    SolicitudRegistro,
)

TOKEN_TYPE = "bearer"


def registrar_usuario(datos: SolicitudRegistro) -> dict:
    client = get_anon_client()

    try:
        response = client.auth.sign_up({
            "email": datos.email,
            "password": datos.password,
        })
    # Clase base de los errores de Supabase Auth: no distinguimos el tipo.
    except AuthError as error:
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


def iniciar_sesion(datos: SolicitudInicioSesion) -> dict:
    client = get_anon_client()

    try:
        response = client.auth.sign_in_with_password({
            "email": datos.email,
            "password": datos.password,
        })
    except AuthError as error:
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

    return {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
        "token_type": TOKEN_TYPE,
    }


def reenviar_confirmacion(datos: SolicitudReenviarConfirmacion) -> dict:
    client = get_anon_client()

    try:
        client.auth.resend({
            "type": "signup",
            "email": datos.email,
        })
    except AuthError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error.message
        ) from error

    return {"mensaje": "Si el correo existe, se reenvió el email de confirmación"}
