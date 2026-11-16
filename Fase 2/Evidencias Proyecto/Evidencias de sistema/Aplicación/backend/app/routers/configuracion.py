from fastapi import APIRouter, Depends

from app.dependencies.autenticacion import exigir_editor_configuracion, obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.configuracion import ConfiguracionEditar, ConfiguracionRespuesta, UfVigenteRespuesta
from app.services import servicio_configuracion

router = APIRouter(prefix="/configuracion", tags=["Configuración"])


@router.get("", response_model=ConfiguracionRespuesta)
def obtener_configuracion(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_configuracion.obtener_configuracion(usuario_actual)


@router.get("/uf-vigente", response_model=UfVigenteRespuesta)
def obtener_uf_vigente(usuario_actual: UsuarioActual = Depends(obtener_usuario_actual)):
    return servicio_configuracion.obtener_uf_vigente(usuario_actual)


@router.put("", response_model=ConfiguracionRespuesta)
def guardar_configuracion(
    datos: ConfiguracionEditar,
    editor: UsuarioActual = Depends(exigir_editor_configuracion),
):
    return servicio_configuracion.guardar_configuracion(editor, datos)
