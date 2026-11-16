from typing import List

from fastapi import APIRouter, Depends, Query

from app.dependencies.autenticacion import obtener_usuario_actual
from app.dependencies.permisos_proyecto import exigir_miembro_proyecto
from app.schemas.autenticacion import UsuarioActual
from app.schemas.historial import EventoHistorial
from app.services import servicio_historial

router = APIRouter(prefix="/proyectos/{proyecto_id}/historial", tags=["Historial del proyecto"])

# Solo lectura: cualquier miembro consulta. Un proyecto al que no se pertenece responde 404.


@router.get("", response_model=List[EventoHistorial])
def listar_historial(
    limite: int = Query(50, ge=1, le=200),
    proyecto: dict = Depends(exigir_miembro_proyecto),
    usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
):
    return servicio_historial.listar(usuario_actual, proyecto, limite)
