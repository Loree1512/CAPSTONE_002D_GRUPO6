import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database.supabase import get_anon_client
from app.schemas.autenticacion import UsuarioActual

# Desactivamos el error automático para devolver 401 si falta Authorization.
bearer_scheme = HTTPBearer(auto_error=False)


def obtener_usuario_actual(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UsuarioActual:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    client = get_anon_client()

    # Cualquier error se trata como token inválido: siempre respondemos 401.
    try:
        response = client.auth.get_user(token)
    except Exception:
        response = None

    if response is None or response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UsuarioActual(
        id=response.user.id,
        email=response.user.email,
        access_token=token,
    )


def _es_editor(usuario_actual: UsuarioActual) -> bool:
    # Temporal hasta tener roles. Si BANCO_EDITORES está vacía, nadie puede escribir.
    editores = {
        editor.strip().lower()
        for editor in os.getenv("BANCO_EDITORES", "").split(",")
        if editor.strip()
    }
    return str(usuario_actual.id).lower() in editores


def exigir_editor_banco(
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
) -> UsuarioActual:
    if not _es_editor(usuario_actual):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para editar el banco de precios.",
        )

    return usuario_actual


def exigir_editor_configuracion(
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
) -> UsuarioActual:
    # Mismos editores que el banco mientras no existan roles.
    if not _es_editor(usuario_actual):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para editar la configuración del cálculo.",
        )

    return usuario_actual


def exigir_editor_plantillas(
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
) -> UsuarioActual:
    # Mismos editores que el banco mientras no existan roles.
    if not _es_editor(usuario_actual):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para editar las plantillas de presupuesto.",
        )

    return usuario_actual
