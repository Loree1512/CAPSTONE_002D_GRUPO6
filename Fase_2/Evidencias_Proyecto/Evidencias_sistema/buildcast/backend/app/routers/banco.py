from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.autenticacion import exigir_editor_banco, obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.banco import (
    CategoriaPartidaRespuesta,
    FilaBancoRespuesta,
    PartidaCrear,
    PartidaEditar,
    PartidaRespuesta,
    PrecioEditar,
    VersionPreciosCrear,
    VersionPreciosRespuesta,
)
from app.services import servicio_banco

router = APIRouter(prefix="/banco", tags=["Banco de precios"])

# Lecturas: cualquier usuario autenticado (RLS). Escrituras: exigir_editor_banco.


@router.get("/categorias", response_model=List[CategoriaPartidaRespuesta])
def listar_categorias(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_banco.listar_categorias(usuario_actual)


@router.get("/versiones", response_model=List[VersionPreciosRespuesta])
def listar_versiones(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_banco.listar_versiones(usuario_actual)


@router.post("/versiones", response_model=VersionPreciosRespuesta, status_code=status.HTTP_201_CREATED)
def crear_version(
    datos: VersionPreciosCrear,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.crear_version(datos)


@router.post("/versiones/{version_id}/publicar", response_model=VersionPreciosRespuesta)
def publicar_version(
    version_id: UUID,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.publicar_version(version_id)


@router.get("/partidas", response_model=List[FilaBancoRespuesta])
def listar_banco(
    # Sin version se usa la versión vigente.
    version: Optional[UUID] = Query(None, description="Id de la versión de precios"),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_banco.listar_banco(usuario_actual, version)


@router.post("/partidas", response_model=PartidaRespuesta, status_code=status.HTTP_201_CREATED)
def crear_partida(
    datos: PartidaCrear,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.crear_partida(datos)


@router.put("/partidas/{partida_id}", response_model=PartidaRespuesta)
def editar_partida(
    partida_id: UUID,
    datos: PartidaEditar,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.editar_partida(partida_id, datos)


@router.post("/partidas/{partida_id}/baja", response_model=PartidaRespuesta)
def dar_de_baja_partida(
    partida_id: UUID,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.dar_de_baja_partida(partida_id)


@router.put("/versiones/{version_id}/precios/{partida_id}", response_model=FilaBancoRespuesta)
def guardar_precio(
    version_id: UUID,
    partida_id: UUID,
    datos: PrecioEditar,
    editor: UsuarioActual = Depends(exigir_editor_banco),
):
    return servicio_banco.guardar_precio(version_id, partida_id, datos)
