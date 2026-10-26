from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

from app.schemas.configuracion import GASTOS_GENERALES_MAX, UTILIDAD_MAX


# Respuestas en camelCase, con los mismos nombres que Presupuesto en el frontend.
class ModeloCamel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Solicitud -------------------------------------------------------------------

class EstimacionCrear(BaseModel):
    # Sin versión se usa la vigente.
    version_precio_id: Optional[UUID] = None
    # Sin valor se usan los de la configuración.
    gastos_generales_pct: Optional[float] = None
    utilidad_pct: Optional[float] = None
    # Factores de comuna y pisos: opcionales, apagados por defecto.
    aplicar_factores: bool = False

    # PydanticCustomError deja el mensaje tal cual: el frontend muestra detail[0].msg.
    @field_validator("gastos_generales_pct")
    @classmethod
    def validar_gastos_generales(cls, valor):
        if valor is not None and not 0 <= valor <= GASTOS_GENERALES_MAX:
            raise PydanticCustomError(
                "porcentaje_invalido",
                f"Los gastos generales deben estar entre 0 y {GASTOS_GENERALES_MAX} %.",
            )
        return valor

    @field_validator("utilidad_pct")
    @classmethod
    def validar_utilidad(cls, valor):
        if valor is not None and not 0 <= valor <= UTILIDAD_MAX:
            raise PydanticCustomError(
                "porcentaje_invalido",
                f"La utilidad debe estar entre 0 y {UTILIDAD_MAX} %.",
            )
        return valor


# --- Respuestas ------------------------------------------------------------------

class VersionPreciosUsada(ModeloCamel):
    id: UUID
    version: str
    fuente: Optional[str] = None


class ProyectoEstimado(ModeloCamel):
    # Datos del proyecto tal como estaban al estimar.
    comuna: str
    tipo_obra: str
    materialidad: str
    superficie_m2: float
    numero_pisos: int
    estandar_terminaciones: str


class FactoresAplicados(ModeloCamel):
    # Valores usados: 1 si la estimación no aplicó factores.
    comuna: float
    pisos: float
    ajuste: float  # comuna × pisos


class LineaPartida(ModeloCamel):
    id: Optional[UUID] = None  # partida del proyecto de origen
    codigo: Optional[str] = None
    nombre: str
    unidad: str
    categoria_codigo: str
    categoria_nombre: str
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None  # precio usado, sin factor
    subtotal: float

    partida_id: Optional[UUID] = None  # null = partida manual
    origen: str
    observacion: Optional[str] = None
    estado: str
    precio_unitario_base: Optional[float] = None
    precio_unitario_override: Optional[float] = None
    fuente_precio: Optional[str] = None
    factor_aplicado: float
    subtotal_base: float


class CapituloPresupuesto(ModeloCamel):
    codigo: str
    nombre: str
    subtotal: float
    incidencia: float
    lineas: List[LineaPartida]


class EstimacionResumen(ModeloCamel):
    id: UUID
    proyecto_id: UUID
    fecha_creacion: datetime
    version_motor: str
    version_precios: VersionPreciosUsada
    costo_directo: float
    total: float
    costo_m2: float
    completa: bool
    partidas_calculadas: int
    partidas_sin_precio: int
    partidas_sin_cantidad: int


class EstimacionRespuesta(EstimacionResumen):
    proyecto: ProyectoEstimado

    capitulos: List[CapituloPresupuesto]
    # Suma de partidas antes de factores.
    costo_directo_base: float
    gastos_generales_pct: float
    gastos_generales: float
    utilidad_pct: float
    utilidad: float
    aplicar_factores: bool
    factores: FactoresAplicados

    # Partidas que no suman al costo directo, con el motivo en `estado`.
    sin_precio: List[LineaPartida]
    sin_cantidad: List[LineaPartida]
