from fastapi import APIRouter, Depends, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import (
    RespuestaMensaje,
    RespuestaRegistro,
    RespuestaToken,
    RespuestaUsuario,
    SolicitudInicioSesion,
    SolicitudReenviarConfirmacion,
    SolicitudRegistro,
    UsuarioActual,
)
from app.services import servicio_autenticacion

router = APIRouter(prefix="/autenticacion", tags=["Autenticación"])


@router.post("/registro", response_model=RespuestaRegistro, status_code=status.HTTP_201_CREATED)
def registro(datos: SolicitudRegistro):
    return servicio_autenticacion.registrar_usuario(datos)


@router.post("/iniciar-sesion", response_model=RespuestaToken)
def iniciar_sesion(datos: SolicitudInicioSesion):
    return servicio_autenticacion.iniciar_sesion(datos)


@router.get("/yo", response_model=RespuestaUsuario)
def yo(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    # response_model filtra el access_token: solo se expone RespuestaUsuario.
    return usuario_actual


@router.post("/reenviar-confirmacion", response_model=RespuestaMensaje)
def reenviar_confirmacion(datos: SolicitudReenviarConfirmacion):
    return servicio_autenticacion.reenviar_confirmacion(datos)
