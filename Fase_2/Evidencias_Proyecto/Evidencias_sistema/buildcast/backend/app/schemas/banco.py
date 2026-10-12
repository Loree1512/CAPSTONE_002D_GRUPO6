from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

# Mismas unidades que el tipo Unidad del frontend y el check de partidas.unidad.
Unidad = Literal["m2", "m3", "ml", "kg", "un", "gl", "pto"]
UNIDADES = ("m2", "m3", "ml", "kg", "un", "gl", "pto")


def _texto_obligatorio(valor: object, mensaje: str) -> str:
    # PydanticCustomError deja el mensaje tal cual: el frontend muestra detail[0].msg.
    if not isinstance(valor, str) or not valor.strip():
        raise PydanticCustomError("texto_obligatorio", mensaje)
    return valor.strip()


def _positivo_o_nulo(valor: Optional[float], mensaje: str) -> Optional[float]:
    # La base exige > 0 cuando hay valor; se rechaza aquí con un mensaje claro.
    if valor is not None and valor <= 0:
        raise PydanticCustomError("valor_no_positivo", mensaje)
    return valor


# --- Respuestas: misma forma que frontend/src/tipos/api.ts --------------------

class CategoriaPartidaRespuesta(BaseModel):
    id: int
    codigo: str
    nombre: str
    orden: int


class VersionPreciosRespuesta(BaseModel):
    id: UUID
    version: str
    trimestre: Optional[str] = None
    fuente: Optional[str] = None
    vigente: bool
    cargado_en: Optional[datetime] = None
    # null = borrador editable; con fecha = publicada alguna vez e inmutable.
    fecha_publicacion: Optional[datetime] = None
    # borrador | vigente | historica
    estado: str = "borrador"


class PartidaRespuesta(BaseModel):
    id: UUID
    categoria_id: int
    codigo: str
    nombre: str
    unidad: str
    es_base: bool
    vigente: bool


class FilaBancoRespuesta(PartidaRespuesta):
    # null cuando la partida no tiene valores en la versión consultada.
    precio_unitario: Optional[float] = None
    rendimiento_mo: Optional[float] = None
    fuente: Optional[str] = None
    # Tiene precio en alguna versión: su unidad ya no se puede cambiar.
    tiene_precios: bool = False


# --- Solicitudes ---------------------------------------------------------------

class VersionPreciosCrear(BaseModel):
    version: str
    copiar_de: Optional[UUID] = None

    @field_validator("version", mode="before")
    @classmethod
    def validar_version(cls, valor):
        return _texto_obligatorio(valor, "Escribe el nombre de la versión.")


class PartidaCrear(BaseModel):
    categoria_id: int
    nombre: str
    unidad: Unidad

    @field_validator("nombre", mode="before")
    @classmethod
    def validar_nombre(cls, valor):
        return _texto_obligatorio(valor, "Escribe el nombre de la partida.")

    @field_validator("unidad", mode="before")
    @classmethod
    def validar_unidad(cls, valor):
        if valor not in UNIDADES:
            raise PydanticCustomError(
                "unidad_invalida",
                "La unidad debe ser una de: " + ", ".join(UNIDADES) + ".",
            )
        return valor


class PartidaEditar(BaseModel):
    # Parcial. El código no se edita: lo usan estimaciones y plantillas.
    nombre: Optional[str] = None
    unidad: Optional[Unidad] = None
    categoria_id: Optional[int] = None

    @field_validator("nombre", mode="before")
    @classmethod
    def validar_nombre(cls, valor):
        return _texto_obligatorio(valor, "Escribe el nombre de la partida.")

    @field_validator("unidad", mode="before")
    @classmethod
    def validar_unidad(cls, valor):
        if valor not in UNIDADES:
            raise PydanticCustomError(
                "unidad_invalida",
                "La unidad debe ser una de: " + ", ".join(UNIDADES) + ".",
            )
        return valor


class PrecioEditar(BaseModel):
    # PUT completo: el frontend manda siempre ambos valores; null = sin valor.
    precio_unitario: Optional[float] = None
    rendimiento_mo: Optional[float] = None
    fuente: Optional[str] = None

    @field_validator("precio_unitario")
    @classmethod
    def validar_precio(cls, valor):
        return _positivo_o_nulo(valor, "El precio unitario debe ser mayor que 0.")

    @field_validator("rendimiento_mo")
    @classmethod
    def validar_rendimiento(cls, valor):
        return _positivo_o_nulo(valor, "El rendimiento de mano de obra debe ser mayor que 0.")

    @field_validator("fuente")
    @classmethod
    def limpiar_fuente(cls, valor):
        if valor is None:
            return None
        return valor.strip() or None
