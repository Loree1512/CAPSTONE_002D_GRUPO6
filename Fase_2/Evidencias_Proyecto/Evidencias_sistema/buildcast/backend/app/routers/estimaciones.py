from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.estimacion import EstimacionCrear, EstimacionRespuesta, EstimacionResumen
from app.services import servicio_estimaciones

router = APIRouter(prefix="/proyectos/{proyecto_id}/estimaciones", tags=["Estimaciones"])

# Un proyecto o estimación ajena responde 404.


@router.post("", response_model=EstimacionRespuesta, status_code=status.HTTP_201_CREATED)
def crear_estimacion(
    proyecto_id: UUID,
    # Sin cuerpo se usa la versión vigente y la configuración guardada.
    datos: Optional[EstimacionCrear] = Body(None),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.crear_estimacion(usuario_actual, proyecto_id, datos)


@router.get("", response_model=List[EstimacionResumen])
def listar_estimaciones(
    proyecto_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.listar_estimaciones(usuario_actual, proyecto_id)


@router.get("/{estimacion_id}", response_model=EstimacionRespuesta)
def obtener_estimacion(
    proyecto_id: UUID,
    estimacion_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.obtener_estimacion(usuario_actual, proyecto_id, estimacion_id)
