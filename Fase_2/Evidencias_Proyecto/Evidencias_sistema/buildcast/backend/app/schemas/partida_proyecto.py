from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.plantilla import PlantillaResumen

UNIDAD_MAX = 20


def _error(mensaje: str) -> PydanticCustomError:
    # El frontend muestra detail[0].msg tal cual.
    return PydanticCustomError("partida_invalida", mensaje)


def _texto(valor, mensaje: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise _error(mensaje)
    return valor.strip()


def _unidad(valor) -> str:
    unidad = _texto(valor, "Indica la unidad de la partida.")
    if len(unidad) > UNIDAD_MAX:
        raise _error(f"La unidad admite hasta {UNIDAD_MAX} caracteres.")
    return unidad


def _no_negativo(valor: Optional[Decimal], mensaje: str) -> Optional[Decimal]:
    if valor is not None and valor < 0:
        raise _error(mensaje)
    return valor


# --- Respuestas ------------------------------------------------------------------

class PartidaProyectoRespuesta(BaseModel):
    id: UUID
    proyecto_id: UUID
    partida_id: Optional[UUID] = None
    codigo: Optional[str] = None
    categoria_id: int
    categoria_codigo: str
    categoria_nombre: str
    categoria_orden: int
    nombre: str
    unidad: str
    cantidad: Optional[float] = None
    precio_unitario_override: Optional[float] = None
    # Precio de la versión vigente del banco (null en manuales o sin precio).
    precio_banco: Optional[float] = None
    # Override si hay; si no, el del banco.
    precio_unitario: Optional[float] = None
    # cantidad × precio_unitario, sin factores; null si falta alguno.
    subtotal: Optional[float] = None
    estado: str
    origen: str
    orden: int
    observacion: Optional[str] = None
    fecha_actualizacion: Optional[datetime] = None


class VersionBanco(BaseModel):
    id: UUID
    version: str


class PartidasProyectoRespuesta(BaseModel):
    plantilla_aplicada: Optional[PlantillaResumen] = None
    # La que corresponde hoy al tipo de obra + materialidad del proyecto.
    plantilla_sugerida: Optional[PlantillaResumen] = None
    version_precios: Optional[VersionBanco] = None
    partidas: List[PartidaProyectoRespuesta]


# --- Solicitudes -------------------------------------------------------------------

class PartidaProyectoCrear(BaseModel):
    # Las de origen "plantilla" solo entran al aplicar una plantilla.
    origen: Literal["catalogo", "manual"]
    partida_id: Optional[UUID] = None
    categoria_id: Optional[int] = None
    nombre: Optional[str] = None
    unidad: Optional[str] = None
    cantidad: Optional[Decimal] = None
    precio_unitario_override: Optional[Decimal] = None
    observacion: Optional[str] = None

    @field_validator("cantidad")
    @classmethod
    def validar_cantidad(cls, valor):
        return _no_negativo(valor, "La cantidad no puede ser negativa.")

    @field_validator("precio_unitario_override")
    @classmethod
    def validar_precio(cls, valor):
        return _no_negativo(valor, "El precio unitario no puede ser negativo.")

    @model_validator(mode="after")
    def validar(self):
        if self.origen == "catalogo":
            if self.partida_id is None:
                raise _error("Elige la partida del catálogo.")
            # Nombre y unidad salen del catálogo; se pueden editar después.
            if self.nombre is not None:
                self.nombre = _texto(self.nombre, "Escribe el nombre de la partida.")
            return self

        # Una partida manual no existe en el catálogo: se pide todo.
        if self.partida_id is not None:
            raise _error("Una partida manual no se asocia al catálogo.")
        if self.categoria_id is None:
            raise _error("Elige la categoría de la partida.")
        self.nombre = _texto(self.nombre, "Escribe el nombre de la partida.")
        self.unidad = _unidad(self.unidad)
        if self.cantidad is None:
            raise _error("Indica la cantidad de la partida.")
        if self.precio_unitario_override is None:
            raise _error("Indica el precio unitario de la partida.")
        return self


class PartidaProyectoEditar(BaseModel):
    # Parcial. cantidad, precio y observación admiten null para vaciarlos.
    nombre: Optional[str] = None
    unidad: Optional[str] = None
    categoria_id: Optional[int] = None
    cantidad: Optional[Decimal] = None
    precio_unitario_override: Optional[Decimal] = None
    observacion: Optional[str] = None

    @field_validator("nombre", mode="before")
    @classmethod
    def validar_nombre(cls, valor):
        return _texto(valor, "Escribe el nombre de la partida.")

    @field_validator("unidad", mode="before")
    @classmethod
    def validar_unidad(cls, valor):
        return _unidad(valor)

    @field_validator("cantidad")
    @classmethod
    def validar_cantidad(cls, valor):
        return _no_negativo(valor, "La cantidad no puede ser negativa.")

    @field_validator("precio_unitario_override")
    @classmethod
    def validar_precio(cls, valor):
        return _no_negativo(valor, "El precio unitario no puede ser negativo.")

    @field_validator("observacion")
    @classmethod
    def limpiar_observacion(cls, valor):
        if valor is None:
            return None
        return valor.strip() or None


class PartidasOrdenar(BaseModel):
    # Todas las partidas del proyecto, en el nuevo orden.
    ids: List[UUID]


class PlantillaAplicar(BaseModel):
    # Sin id se usa la que corresponde al tipo de obra + materialidad.
    plantilla_id: Optional[UUID] = None
    # Debe ser true para reemplazar partidas existentes.
    reemplazar: bool = False
