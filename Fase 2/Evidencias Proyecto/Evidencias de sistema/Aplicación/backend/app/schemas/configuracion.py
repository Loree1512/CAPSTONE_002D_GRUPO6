from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError


# Misma forma que Configuracion del frontend, más los capítulos de cada factor.
class ModeloCamel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# Límites de GG y utilidad; valen para la configuración y para cada estimación.
GASTOS_GENERALES_MAX = 25
UTILIDAD_MAX = 30


def _error(mensaje: str) -> PydanticCustomError:
    # El frontend muestra detail[0].msg tal cual.
    return PydanticCustomError("configuracion_invalida", mensaje)


class TramoPisos(ModeloCamel):
    desde: int
    hasta: int
    factor: float


class FactoresEstandar(ModeloCamel):
    economico: float
    medio: float
    alto: float


class ConfiguracionBase(ModeloCamel):
    valor_hora_hombre: float
    gastos_generales_pct: float
    utilidad_pct: float
    factores_comuna: Dict[str, float]
    tramos_pisos: List[TramoPisos]
    factores_estandar: FactoresEstandar
    factores_material: Dict[str, float]

    @model_validator(mode="after")
    def validar(self):
        if self.valor_hora_hombre < 0:
            raise _error("El valor de la hora hombre no puede ser negativo.")
        if not 0 <= self.gastos_generales_pct <= GASTOS_GENERALES_MAX:
            raise _error(f"Los gastos generales deben estar entre 0 y {GASTOS_GENERALES_MAX} %.")
        if not 0 <= self.utilidad_pct <= UTILIDAD_MAX:
            raise _error(f"La utilidad debe estar entre 0 y {UTILIDAD_MAX} %.")
        if not self.tramos_pisos:
            raise _error("Debe existir al menos un tramo de pisos.")
        for tramo in self.tramos_pisos:
            if tramo.desde < 1 or tramo.hasta < tramo.desde:
                raise _error("Cada tramo de pisos debe cumplir 1 ≤ desde ≤ hasta.")

        factores = [
            *self.factores_comuna.values(),
            *self.factores_material.values(),
            *(t.factor for t in self.tramos_pisos),
            self.factores_estandar.economico,
            self.factores_estandar.medio,
            self.factores_estandar.alto,
        ]
        if any(f <= 0 for f in factores):
            raise _error("Todos los factores deben ser mayores que 0.")
        return self


class ConfiguracionRespuesta(ConfiguracionBase):
    capitulos_estandar: List[str]
    capitulos_materialidad: List[str]


class ConfiguracionEditar(ConfiguracionBase):
    # El frontend no los envía; si faltan, se conservan los guardados.
    capitulos_estandar: Optional[List[str]] = None
    capitulos_materialidad: Optional[List[str]] = None


class UfVigenteRespuesta(ModeloCamel):
    """UF del día desde valores_uf. Sin valor ni fecha si todavía no hay ninguna cargada."""
    valor: Optional[float] = None
    fecha: Optional[date] = None
    fuente: str = "CMF"
