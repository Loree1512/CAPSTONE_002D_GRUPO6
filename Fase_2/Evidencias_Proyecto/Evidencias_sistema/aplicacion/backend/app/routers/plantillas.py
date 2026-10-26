from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.autenticacion import exigir_editor_plantillas, obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.plantilla import (
    PlantillaCrear,
    PlantillaDetalle,
    PlantillaEditar,
    PlantillaPartidasGuardar,
    PlantillaResumen,
)
from app.services import servicio_plantillas

router = APIRouter(prefix="/plantillas", tags=["Plantillas de presupuesto"])

# Lecturas: cualquier usuario autenticado. Escrituras: mismos editores que el banco.


@router.get("", response_model=List[PlantillaResumen])
def listar_plantillas(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_plantillas.listar(usuario_actual)


@router.get("/{plantilla_id}", response_model=PlantillaDetalle)
def obtener_plantilla(
    plantilla_id: UUID,
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_plantillas.obtener(usuario_actual, plantilla_id)


@router.post("", response_model=PlantillaDetalle, status_code=status.HTTP_201_CREATED)
def crear_plantilla(
    datos: PlantillaCrear,
    editor: UsuarioActual = Depends(exigir_editor_plantillas),
):
    return servicio_plantillas.crear(datos)


@router.put("/{plantilla_id}", response_model=PlantillaDetalle)
def editar_plantilla(
    plantilla_id: UUID,
    datos: PlantillaEditar,
    editor: UsuarioActual = Depends(exigir_editor_plantillas),
):
    return servicio_plantillas.editar(plantilla_id, datos)


@router.put("/{plantilla_id}/partidas", response_model=PlantillaDetalle)
def guardar_partidas_plantilla(
    plantilla_id: UUID,
    datos: PlantillaPartidasGuardar,
    editor: UsuarioActual = Depends(exigir_editor_plantillas),
):
    return servicio_plantillas.guardar_partidas(plantilla_id, datos)
