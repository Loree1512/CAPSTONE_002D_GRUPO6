from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

from app.schemas.configuracion import GASTOS_GENERALES_MAX, UTILIDAD_MAX


# Respuestas en camelCase, con los mismos nombres que Presupuesto en el frontend.
class ModeloCamel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Solicitud -------------------------------------------------------------------

# Mismo tope que el CHECK de estimaciones.observaciones (migración 006).
OBSERVACIONES_MAX = 1000


def limpiar_observaciones(valor: Optional[str]) -> Optional[str]:
    # Texto plano: se guarda tal cual (sin interpretar HTML); vacía queda en null.
    if valor is None:
        return None
    valor = valor.replace("\r\n", "\n").strip()
    if not valor:
        return None
    if len(valor) > OBSERVACIONES_MAX:
        raise PydanticCustomError(
            "observaciones_largas",
            f"Las observaciones admiten hasta {OBSERVACIONES_MAX} caracteres.",
        )
    return valor


class EstimacionCrear(BaseModel):
    # Sin versión se usa la vigente.
    version_precio_id: Optional[UUID] = None
    # Sin valor se usan los de la configuración.
    gastos_generales_pct: Optional[float] = None
    utilidad_pct: Optional[float] = None
    # Factores de comuna y pisos: opcionales, apagados por defecto.
    aplicar_factores: bool = False
    # Observaciones de la cotización: quedan guardadas con esta estimación.
    observaciones: Optional[str] = None

    @field_validator("observaciones")
    @classmethod
    def validar_observaciones(cls, valor):
        return limpiar_observaciones(valor)

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


class CotizacionActualizar(BaseModel):
    # Cambia solo la observación: no recalcula montos.
    observaciones: Optional[str] = None

    @field_validator("observaciones")
    @classmethod
    def validar_observaciones(cls, valor):
        return limpiar_observaciones(valor)


# Mismo rango que el CHECK de estimaciones.plazo_profesional_dias (migración 010).
PLAZO_PROFESIONAL_MIN = 1
PLAZO_PROFESIONAL_MAX = 3650


class PlazoProfesionalDefinir(BaseModel):
    """Acción explícita del profesional: un plazo escrito o la sugerencia del modelo.

    Acepta `usarSugerencia` (como lo envía el frontend) o `usar_sugerencia`.
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    dias: Optional[int] = None
    usar_sugerencia: bool = False

    @model_validator(mode="after")
    def validar(self):
        if self.usar_sugerencia:
            if self.dias is not None:
                raise PydanticCustomError(
                    "plazo_ambiguo",
                    "Indica un plazo en días o usa la sugerencia, no ambos.",
                )
            return self
        if self.dias is None or not PLAZO_PROFESIONAL_MIN <= self.dias <= PLAZO_PROFESIONAL_MAX:
            raise PydanticCustomError(
                "plazo_invalido",
                f"El plazo debe ser un número entero de días entre {PLAZO_PROFESIONAL_MIN} "
                f"y {PLAZO_PROFESIONAL_MAX}.",
            )
        return self


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


EstadoPlazo = Literal[
    "dentro_dominio", "fuera_rango_costo", "tipo_obra_no_representado",
    "costo_incompleto", "respaldo", "no_disponible",
]


class PlazoEstimado(ModeloCamel):
    """Plazo sugerido por el modelo de ML, guardado con la estimación (migración 009).

    Es una sugerencia para el profesional, no el plazo del documento de entrega (ese es
    PlazoProfesional). Solo `dentro_dominio` corresponde al rango histórico del modelo;
    el resto es referencial. `dias` es null si el plazo no se pudo calcular.
    """
    dias: Optional[int] = None
    min_dias: Optional[int] = None
    max_dias: Optional[int] = None
    metodo: Optional[str] = None
    estado: EstadoPlazo = "no_disponible"
    fuera_dominio: bool = True
    provisional: Optional[bool] = None
    motivo: Optional[str] = None
    version_modelo: Optional[str] = None
    tipo_obra_modelo: Optional[str] = None
    uf_valor: Optional[float] = None
    uf_fecha: Optional[date] = None
    # De versiones_modelo (no se escriben a mano). El error medio (MAE) es del modelo,
    # no un intervalo de esta predicción; null si el método guardado no es el de la
    # versión (p. ej. la mediana de respaldo) o si la versión no tiene métricas.
    error_medio_dias: Optional[float] = None
    estado_modelo: Optional[str] = None


EstadoPlazoProfesional = Literal["sin_definir", "definido", "por_revisar"]
OrigenPlazoProfesional = Literal["sugerencia", "manual"]


class PlazoProfesional(ModeloCamel):
    """Plazo para la cotización, definido por el profesional (migración 010).

    Es el que muestra el documento de entrega. `por_revisar`: se definió sobre una
    estimación anterior y el costo se recalculó después; conserva el valor anterior.
    """
    dias: Optional[int] = None
    estado: EstadoPlazoProfesional = "sin_definir"
    origen: Optional[OrigenPlazoProfesional] = None
    fecha: Optional[datetime] = None
    usuario_id: Optional[UUID] = None
    # Nombre o correo de quien lo definió (perfiles); null si la cuenta ya no existe.
    usuario_nombre: Optional[str] = None


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
    # Sugerencia del modelo (interna) y plazo para la cotización: datos distintos.
    plazo: PlazoEstimado = PlazoEstimado()
    plazo_profesional: PlazoProfesional = PlazoProfesional()


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

    # Texto plano, tal como quedó al emitir esta estimación.
    observaciones: Optional[str] = None
