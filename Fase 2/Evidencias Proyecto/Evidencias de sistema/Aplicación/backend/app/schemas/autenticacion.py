from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SolicitudRegistro(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class SolicitudInicioSesion(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class SolicitudReenviarConfirmacion(BaseModel):
    email: EmailStr


class RespuestaRegistro(BaseModel):
    id: UUID
    email: str
    # False si Supabase exige confirmar el correo antes de iniciar sesión.
    sesion_creada: bool


class RespuestaToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RespuestaUsuario(BaseModel):
    id: UUID
    email: str


class RespuestaMensaje(BaseModel):
    mensaje: str


# Identidad del usuario autenticado, obtenida desde el token.
class UsuarioActual(BaseModel):
    id: UUID
    email: str
    access_token: str
