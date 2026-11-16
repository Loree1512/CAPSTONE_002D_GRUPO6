from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.partida_proyecto import (
    PartidaProyectoCrear,
    PartidaProyectoEditar,
    PartidaProyectoRespuesta,
    PartidasOrdenar,
    PartidasProyectoRespuesta,
    PlantillaAplicar,
)
from app.services import servicio_partidas_proyecto

router = APIRouter(prefix="/proyectos/{proyecto_id}/partidas", tags=["Partidas del proyecto"])

# Consultar: cualquier miembro. Modificar: propietario o editor (lector: 403).
# Un proyecto al que no se pertenece responde 404.


@router.get("", response_model=PartidasProyectoRespuesta)
def listar_partidas(
    proyecto_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_partidas_proyecto.listar(usuario_actual, proyecto_id)


@router.post("", response_model=PartidaProyectoRespuesta, status_code=status.HTTP_201_CREATED)
def crear_partida(
    proyecto_id: UUID,
    datos: PartidaProyectoCrear,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_partidas_proyecto.crear(usuario_actual, proyecto_id, datos)


# Rutas fijas antes que /{proyecto_partida_id}.
@router.post("/aplicar-plantilla", response_model=PartidasProyectoRespuesta)
def aplicar_plantilla(
    proyecto_id: UUID,
    datos: PlantillaAplicar,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_partidas_proyecto.aplicar_plantilla(usuario_actual, proyecto_id, datos)


@router.post("/ordenar", response_model=List[PartidaProyectoRespuesta])
def ordenar_partidas(
    proyecto_id: UUID,
    datos: PartidasOrdenar,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_partidas_proyecto.ordenar(usuario_actual, proyecto_id, datos)


@router.put("/{proyecto_partida_id}", response_model=PartidaProyectoRespuesta)
def editar_partida(
    proyecto_id: UUID,
    proyecto_partida_id: UUID,
    datos: PartidaProyectoEditar,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_partidas_proyecto.editar(usuario_actual, proyecto_id, proyecto_partida_id, datos)


@router.delete("/{proyecto_partida_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_partida(
    proyecto_id: UUID,
    proyecto_partida_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    servicio_partidas_proyecto.eliminar(usuario_actual, proyecto_id, proyecto_partida_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
