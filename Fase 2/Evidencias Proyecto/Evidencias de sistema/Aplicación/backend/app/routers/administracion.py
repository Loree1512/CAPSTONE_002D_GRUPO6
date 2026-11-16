from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.dependencies.autenticacion import exigir_administrador
from app.schemas.administracion import (
    ConfiguracionAdministracion,
    SolicitudAdministrador,
    UsuarioAdministrado,
    UsuarioCrear,
    UsuarioCreado,
)
from app.schemas.autenticacion import UsuarioActual
from app.services import servicio_administracion

# Todo exige rol global administrador; un profesional recibe 403.
router = APIRouter(prefix="/administracion", tags=["Administración"])


@router.get("/usuarios", response_model=List[UsuarioAdministrado])
def listar_usuarios(admin: UsuarioActual = Depends(exigir_administrador)):
    return servicio_administracion.listar_usuarios(admin)


@router.post("/usuarios", response_model=UsuarioCreado, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    datos: UsuarioCrear,
    response: Response,
    admin: UsuarioActual = Depends(exigir_administrador),
):
    # La respuesta puede traer el enlace de invitación: que nadie la guarde en caché.
    response.headers["Cache-Control"] = "no-store"
    return servicio_administracion.crear_usuario(admin, datos)


@router.post("/usuarios/{usuario_id}/renovar-invitacion", response_model=UsuarioCreado)
def renovar_invitacion(
    usuario_id: UUID,
    response: Response,
    admin: UsuarioActual = Depends(exigir_administrador),
):
    response.headers["Cache-Control"] = "no-store"
    return servicio_administracion.renovar_invitacion(admin, usuario_id)


@router.get("/configuracion", response_model=ConfiguracionAdministracion)
def configuracion(_: UsuarioActual = Depends(exigir_administrador)):
    return servicio_administracion.configuracion()


@router.post(
    "/usuarios/{usuario_id}/solicitar-administrador",
    response_model=SolicitudAdministrador,
    status_code=status.HTTP_201_CREATED,
)
def solicitar_administrador(usuario_id: UUID, admin: UsuarioActual = Depends(exigir_administrador)):
    return servicio_administracion.solicitar_administrador(admin, usuario_id)


@router.get("/solicitudes-administrador", response_model=List[SolicitudAdministrador])
def listar_solicitudes(admin: UsuarioActual = Depends(exigir_administrador)):
    return servicio_administracion.listar_solicitudes(admin)


@router.post("/solicitudes-administrador/{solicitud_id}/aprobar", response_model=SolicitudAdministrador)
def aprobar_solicitud(solicitud_id: UUID, admin: UsuarioActual = Depends(exigir_administrador)):
    return servicio_administracion.aprobar_solicitud(admin, solicitud_id)
