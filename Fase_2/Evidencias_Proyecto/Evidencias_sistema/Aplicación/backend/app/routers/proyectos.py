from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.proyecto import ProyectoActualizar, ProyectoCrear, ProyectoRespuesta
from app.services import servicio_proyectos

router = APIRouter(prefix="/proyectos", tags=["Proyectos"])


@router.post("", response_model=ProyectoRespuesta, status_code=status.HTTP_201_CREATED)
def crear_proyecto(
    proyecto: ProyectoCrear,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_proyectos.crear_proyecto(usuario_actual, proyecto)


@router.get("", response_model=List[ProyectoRespuesta])
def listar_proyectos(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_proyectos.obtener_proyectos(usuario_actual)


@router.get("/{proyecto_id}", response_model=ProyectoRespuesta)
def obtener_proyecto(
    proyecto_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_proyectos.obtener_proyecto_por_id(usuario_actual, proyecto_id)


@router.put("/{proyecto_id}", response_model=ProyectoRespuesta)
def actualizar_proyecto(
    proyecto_id: UUID,
    proyecto: ProyectoActualizar,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_proyectos.actualizar_proyecto(usuario_actual, proyecto_id, proyecto)
