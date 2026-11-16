from fastapi import APIRouter, Depends, status

from app.dependencies.autenticacion import obtener_sesion
from app.schemas.autenticacion import (
    RespuestaMensaje,
    RespuestaRegistro,
    RespuestaToken,
    RespuestaUsuario,
    SolicitudEstablecerContrasena,
    SolicitudInicioSesion,
    SolicitudReenviarConfirmacion,
    SolicitudRefrescar,
    SolicitudRegistro,
    UsuarioActual,
)
from app.services import servicio_autenticacion, servicio_perfiles

router = APIRouter(prefix="/autenticacion", tags=["Autenticación"])


@router.post("/registro", response_model=RespuestaRegistro, status_code=status.HTTP_201_CREATED)
def registro(datos: SolicitudRegistro):
    return servicio_autenticacion.registrar_usuario(datos)


@router.post("/iniciar-sesion", response_model=RespuestaToken)
def iniciar_sesion(datos: SolicitudInicioSesion):
    return servicio_autenticacion.iniciar_sesion(datos)


# Sin Bearer: el access token puede estar vencido; basta el refresh token.
@router.post("/refrescar", response_model=RespuestaToken)
def refrescar(datos: SolicitudRefrescar):
    return servicio_autenticacion.refrescar_sesion(datos)


# Acepta la sesión de un invitado que aún no crea su contraseña: así sabe qué falta.
@router.get("/yo", response_model=RespuestaUsuario)
def yo(usuario_actual: UsuarioActual = Depends(obtener_sesion)):
    acceso = servicio_perfiles.estado_acceso(usuario_actual)
    # Sin access_token: solo se expone RespuestaUsuario.
    return {
        "id": usuario_actual.id,
        "email": usuario_actual.email,
        "rol_global": servicio_perfiles.rol_global(usuario_actual),
        "es_administrador_principal": servicio_perfiles.es_administrador_principal(usuario_actual),
        "nombre": usuario_actual.nombre,
        "acceso_configurado": acceso != servicio_perfiles.EstadoAcceso.pendiente,
    }


# Con el access token que trae el enlace de invitación; solo mientras siga pendiente.
@router.post("/establecer-contrasena", response_model=RespuestaMensaje)
def establecer_contrasena(
    datos: SolicitudEstablecerContrasena,
    usuario_actual: UsuarioActual = Depends(obtener_sesion),
):
    return servicio_autenticacion.establecer_contrasena(usuario_actual, datos)


@router.post("/reenviar-confirmacion", response_model=RespuestaMensaje)
def reenviar_confirmacion(datos: SolicitudReenviarConfirmacion):
    return servicio_autenticacion.reenviar_confirmacion(datos)
