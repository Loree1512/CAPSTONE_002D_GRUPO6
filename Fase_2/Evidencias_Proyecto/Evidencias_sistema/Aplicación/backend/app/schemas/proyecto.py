from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EstandarTerminaciones(str, Enum):
    # Debe coincidir con el CHECK de la migración.
    economico = "economico"
    medio = "medio"
    alto = "alto"


class ProyectoBase(BaseModel):
    nombre: str = Field(..., min_length=1)
    comuna: str = Field(..., min_length=1)
    tipo_obra: str = Field(..., min_length=1)
    materialidad: str = Field(..., min_length=1)
    superficie_m2: float = Field(..., gt=0)
    numero_pisos: int = Field(..., gt=0)
    estandar_terminaciones: EstandarTerminaciones


class ProyectoCrear(ProyectoBase):
    # Sin "estado": nace como "borrador" por el default de la tabla.
    pass


class ProyectoActualizar(BaseModel):
    # Campos opcionales para permitir actualizaciones parciales.
    nombre: Optional[str] = Field(None, min_length=1)
    comuna: Optional[str] = Field(None, min_length=1)
    tipo_obra: Optional[str] = Field(None, min_length=1)
    materialidad: Optional[str] = Field(None, min_length=1)
    superficie_m2: Optional[float] = Field(None, gt=0)
    numero_pisos: Optional[int] = Field(None, gt=0)
    estandar_terminaciones: Optional[EstandarTerminaciones] = None
    estado: Optional[str] = None


class EstadoEstimacion(str, Enum):
    sin_estimar = "sin_estimar"
    vigente = "vigente"
    # Proyecto o partidas editados, o versión de precios distinta desde la última estimación.
    recalcular = "recalcular"


class ProyectoRespuesta(ProyectoBase):
    id: UUID
    # None si la cuenta de Auth fue eliminada (on delete set null).
    usuario_id: Optional[UUID] = None
    estado: str
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    # Última plantilla aplicada; null si nunca se aplicó una.
    plantilla_id: Optional[UUID] = None

    # Resumen de la última estimación; no se guarda en proyectos.
    ultima_estimacion_id: Optional[UUID] = None
    costo_total: Optional[float] = None
    costo_m2: Optional[float] = None
    fecha_estimacion: Optional[datetime] = None
    estado_estimacion: EstadoEstimacion = EstadoEstimacion.sin_estimar
    plazo_dias: Optional[int] = None
