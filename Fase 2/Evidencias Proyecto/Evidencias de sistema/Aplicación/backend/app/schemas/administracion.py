from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.autenticacion import RolGlobal

NOMBRE_MAX = 120


class UsuarioCrear(BaseModel):
    nombre: str
    email: EmailStr

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if not valor:
            raise PydanticCustomError("nombre_vacio", "Escribe el nombre del usuario.")
        if len(valor) > NOMBRE_MAX:
            raise PydanticCustomError("nombre_largo", f"El nombre admite hasta {NOMBRE_MAX} caracteres.")
        return valor


class EstadoCuenta(str, Enum):
    activo = "activo"
    # Invitado o sin confirmar el correo: todavía no entra.
    pendiente = "pendiente"


class AprobacionPrincipal(BaseModel):
    administrador_id: UUID
    nombre: Optional[str] = None
    email: Optional[str] = None
    aprobada: bool
    fecha: Optional[datetime] = None


class SolicitudAdministrador(BaseModel):
    id: UUID
    usuario_id: UUID
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None
    solicitado_por: Optional[UUID] = None
    estado: Literal["pendiente", "aprobada"]
    fecha_creacion: datetime
    fecha_resolucion: Optional[datetime] = None
    aprobaciones_recibidas: int
    aprobaciones_requeridas: int
    # Un renglón por principal, aprobado o no, en orden fijo.
    aprobaciones: List[AprobacionPrincipal]
    # Para quien consulta: principal que todavía no aprobó.
    puedo_aprobar: bool


class UsuarioAdministrado(BaseModel):
    id: UUID
    email: Optional[str] = None
    nombre: Optional[str] = None
    rol_global: RolGlobal
    es_administrador_principal: bool
    fecha_creacion: Optional[datetime] = None
    # null si Supabase Auth no respondió.
    estado: Optional[EstadoCuenta] = None
    solicitud_pendiente: Optional[SolicitudAdministrador] = None
    puede_solicitar_administrador: bool


ModoInvitacion = Literal["enlace", "correo"]


class UsuarioCreado(BaseModel):
    """Respuesta al crear un usuario o renovar su invitación."""
    usuario: UsuarioAdministrado
    modo: ModoInvitacion
    # Solo en modo enlace, solo en esta respuesta: no se guarda ni se vuelve a mostrar.
    enlace: Optional[str] = None


class ConfiguracionAdministracion(BaseModel):
    # Decide si la acción dice «Generar nuevo enlace» o «Reenviar invitación».
    modo_invitacion: ModoInvitacion
