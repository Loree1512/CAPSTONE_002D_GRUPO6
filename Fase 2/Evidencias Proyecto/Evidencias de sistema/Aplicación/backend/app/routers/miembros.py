from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.autenticacion import obtener_usuario_actual
from app.dependencies.permisos_proyecto import exigir_miembro_proyecto, exigir_propietario_proyecto
from app.schemas.autenticacion import UsuarioActual
from app.schemas.miembro import CandidatoMiembro, MiembroAgregar, MiembroCambiarRol, MiembroRespuesta
from app.services import servicio_miembros

router = APIRouter(prefix="/proyectos/{proyecto_id}/miembros", tags=["Miembros del proyecto"])

# Consultar: cualquier miembro. Candidatos, agregar, cambiar o quitar: solo el propietario
# (editor o lector: 403). Un proyecto al que no se pertenece responde 404.


@router.get("", response_model=List[MiembroRespuesta])
def listar_miembros(proyecto: dict = Depends(exigir_miembro_proyecto)):
    return servicio_miembros.listar(proyecto)


@router.get("/candidatos", response_model=List[CandidatoMiembro])
def listar_candidatos(
    buscar: Optional[str] = Query(None, max_length=100),
    proyecto: dict = Depends(exigir_propietario_proyecto),
):
    # Solo para el modal de agregar: no es un listado general de usuarios.
    return servicio_miembros.candidatos(proyecto, buscar)


@router.post("", response_model=MiembroRespuesta, status_code=status.HTTP_201_CREATED)
def agregar_miembro(
    datos: MiembroAgregar,
    proyecto: dict = Depends(exigir_propietario_proyecto),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_miembros.agregar(usuario_actual, proyecto, datos)


@router.put("/{usuario_id}", response_model=MiembroRespuesta)
def cambiar_rol_miembro(
    usuario_id: UUID,
    datos: MiembroCambiarRol,
    proyecto: dict = Depends(exigir_propietario_proyecto),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_miembros.cambiar_rol(usuario_actual, proyecto, usuario_id, datos)


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_miembro(
    usuario_id: UUID,
    proyecto: dict = Depends(exigir_propietario_proyecto),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    servicio_miembros.quitar(usuario_actual, proyecto, usuario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
