from enum import Enum
from typing import Optional
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


class SolicitudRefrescar(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=4096)


class RespuestaToken(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # Segundos de vida del access token.
    expires_in: Optional[int] = None


class RolGlobal(str, Enum):
    # Debe coincidir con el CHECK de perfiles.rol_global.
    administrador = "administrador"
    profesional = "profesional"


class RespuestaUsuario(BaseModel):
    id: UUID
    email: str
    rol_global: RolGlobal
    # Integra el grupo que aprueba promociones a administrador.
    es_administrador_principal: bool = False
    nombre: Optional[str] = None
    # False: entró con un enlace de invitación y todavía no crea su contraseña.
    acceso_configurado: bool = True


class SolicitudEstablecerContrasena(BaseModel):
    # La primera contraseña de un usuario invitado. Supabase puede exigir más.
    password: str = Field(..., min_length=8, max_length=72)


class RespuestaMensaje(BaseModel):
    mensaje: str


# Identidad del usuario autenticado, obtenida desde el token.
class UsuarioActual(BaseModel):
    id: UUID
    email: str
    access_token: str
    # Rol leído junto con el estado de acceso; evita otra consulta en la misma petición.
    rol_global: Optional[RolGlobal] = None
    # perfiles.nombre, leído con el rol. Solo para saludar: no autoriza nada.
    nombre: Optional[str] = None
