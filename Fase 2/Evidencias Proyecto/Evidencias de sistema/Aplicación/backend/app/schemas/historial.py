from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel


class EventoHistorial(BaseModel):
    id: UUID
    # miembro_agregado, partida_editada, estimacion_generada…
    accion: str
    # proyecto, proyecto_partida, plantilla, estimacion, miembro.
    entidad: str
    entidad_id: Optional[UUID] = None
    # Quién lo hizo. Sin cuenta (eliminada) quedan en None.
    usuario_id: Optional[UUID] = None
    usuario_email: Optional[str] = None
    usuario_nombre: Optional[str] = None
    # Solo los campos que cambiaron o que identifican lo afectado.
    valores_anteriores: Optional[Dict[str, Any]] = None
    valores_nuevos: Optional[Dict[str, Any]] = None
    # api, rpc o trigger.
    origen: str
    fecha: datetime
