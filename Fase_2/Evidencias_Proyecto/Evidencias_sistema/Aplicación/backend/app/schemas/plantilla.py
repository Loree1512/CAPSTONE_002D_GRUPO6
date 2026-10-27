from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

# Mismos valores que TIPOS_OBRA y MATERIALES del frontend.
TipoObra = Literal["Vivienda unifamiliar", "Ampliación", "Edificación habitacional"]
Materialidad = Literal["Albañilería confinada", "Hormigón armado", "Tabiquería de madera", "Estructura metálica"]


def _nombre(valor):
    if not isinstance(valor, str) or not valor.strip():
        raise PydanticCustomError("texto_obligatorio", "Escribe el nombre de la plantilla.")
    return valor.strip()


# --- Respuestas ------------------------------------------------------------------

class PlantillaResumen(BaseModel):
    id: UUID
    nombre: str
    tipo_obra: str
    materialidad: str
    vigente: bool
    cantidad_partidas: int
    fecha_actualizacion: Optional[datetime] = None


class PartidaPlantilla(BaseModel):
    partida_id: UUID
    orden: int
    cantidad_sugerida: Optional[float] = None
    codigo: str
    nombre: str
    unidad: str
    categoria_id: int
    vigente: bool


class PlantillaDetalle(PlantillaResumen):
    partidas: List[PartidaPlantilla]


# --- Solicitudes -------------------------------------------------------------------

class PlantillaCrear(BaseModel):
    nombre: str
    tipo_obra: TipoObra
    materialidad: Materialidad
    vigente: bool = True

    @field_validator("nombre", mode="before")
    @classmethod
    def validar_nombre(cls, valor):
        return _nombre(valor)


class PlantillaEditar(BaseModel):
    # Parcial: solo se cambian los campos enviados.
    nombre: Optional[str] = None
    tipo_obra: Optional[TipoObra] = None
    materialidad: Optional[Materialidad] = None
    vigente: Optional[bool] = None

    @field_validator("nombre", mode="before")
    @classmethod
    def validar_nombre(cls, valor):
        return _nombre(valor)


class PartidaPlantillaGuardar(BaseModel):
    partida_id: UUID
    # Cantidad fija opcional propuesta al proyecto (p. ej. 1 gl).
    cantidad_sugerida: Optional[Decimal] = None

    @field_validator("cantidad_sugerida")
    @classmethod
    def validar_cantidad(cls, valor):
        if valor is not None and valor < 0:
            raise PydanticCustomError("cantidad_negativa", "La cantidad sugerida no puede ser negativa.")
        return valor


class PlantillaPartidasGuardar(BaseModel):
    # En el orden en que se proponen al proyecto.
    partidas: List[PartidaPlantillaGuardar]
