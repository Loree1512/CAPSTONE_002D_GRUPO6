from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.proyecto import RolProyecto


class RolAsignable(str, Enum):
    # El propietario es único y no se asigna: es quien creó el proyecto.
    editor = "editor"
    lector = "lector"


class MiembroAgregar(BaseModel):
    # Correo exacto de un usuario ya registrado.
    email: EmailStr
    rol: RolAsignable


class MiembroCambiarRol(BaseModel):
    rol: RolAsignable


class CandidatoMiembro(BaseModel):
    # Usuario registrado que todavía no pertenece al proyecto.
    usuario_id: UUID
    nombre: Optional[str] = None
    email: str


class MiembroRespuesta(BaseModel):
    usuario_id: UUID
    email: Optional[str] = None
    nombre: Optional[str] = None
    rol: RolProyecto
    # None en el propietario de un proyecto anterior a los permisos por proyecto.
    fecha_creacion: Optional[datetime] = None
