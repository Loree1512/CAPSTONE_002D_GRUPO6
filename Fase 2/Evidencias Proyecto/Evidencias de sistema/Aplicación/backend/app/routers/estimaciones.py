from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.estimacion import (
    CotizacionActualizar,
    EstimacionCrear,
    EstimacionRespuesta,
    EstimacionResumen,
    PlazoProfesionalDefinir,
)
from app.services import servicio_estimaciones

router = APIRouter(prefix="/proyectos/{proyecto_id}/estimaciones", tags=["Estimaciones"])

# Consultar: cualquier miembro. Generar, actualizar o definir el plazo: propietario o editor (lector: 403).
# Un proyecto o estimación ajena responde 404.


@router.post("", response_model=EstimacionRespuesta, status_code=status.HTTP_201_CREATED)
def crear_estimacion(
    proyecto_id: UUID,
    # Sin cuerpo se usa la versión vigente y la configuración guardada.
    datos: Optional[EstimacionCrear] = Body(None),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.crear_estimacion(usuario_actual, proyecto_id, datos)


# Solo cambia la observación: nueva estimación con los mismos montos (no recalcula).
@router.post(
    "/{estimacion_id}/actualizar-cotizacion",
    response_model=EstimacionRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def actualizar_cotizacion(
    proyecto_id: UUID,
    estimacion_id: UUID,
    datos: CotizacionActualizar,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.actualizar_cotizacion(usuario_actual, proyecto_id, estimacion_id, datos)


# Plazo para la cotización: lo define el profesional (valor escrito o la sugerencia del
# modelo). Nueva estimación con los mismos montos y la misma sugerencia (no recalcula).
@router.post(
    "/{estimacion_id}/plazo-profesional",
    response_model=EstimacionRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def definir_plazo_profesional(
    proyecto_id: UUID,
    estimacion_id: UUID,
    datos: PlazoProfesionalDefinir,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_estimaciones.definir_plazo_profesional(usuario_actual, proyecto_id, estimacion_id, datos)


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
