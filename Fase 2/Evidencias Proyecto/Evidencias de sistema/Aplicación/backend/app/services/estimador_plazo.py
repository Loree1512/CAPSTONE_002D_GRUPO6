"""Plazo estimado de una estimación (modelo de ML, versión provisional).

El costo lo calcula el motor determinista; este servicio solo estima el plazo a
partir de ese costo, sin numpy ni joblib. Reproduce `ml/src/predict.py`:

    log(plazo) = α + β·log(costo_UF) + γ·[clase = edificacion]

con los parámetros exportados a `app/modelos/plazo_<version>.json` por
`ml/src/exportar_backend.py`. El JSON también trae el dominio conocido (rango de
costo y tipos de obra del entrenamiento) y la traducción de los tipos de obra de
BuildCast al vocabulario del modelo.

`estimar` nunca lanza: si algo falla, el plazo queda `no_disponible` con un motivo
y la estimación de costo se guarda igual.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DIR_MODELOS = Path(__file__).resolve().parents[1] / "modelos"
VERSION_POR_DEFECTO = "v1.0-2026-11-01"
VARIABLE_VERSION = "MODELO_PLAZO_VERSION"

# Estados del plazo. Solo dentro_dominio corresponde al dominio validado.
DENTRO_DOMINIO = "dentro_dominio"
FUERA_RANGO_COSTO = "fuera_rango_costo"
TIPO_NO_REPRESENTADO = "tipo_obra_no_representado"
COSTO_INCOMPLETO = "costo_incompleto"
RESPALDO = "respaldo"
NO_DISPONIBLE = "no_disponible"
ESTADOS = (DENTRO_DOMINIO, FUERA_RANGO_COSTO, TIPO_NO_REPRESENTADO, COSTO_INCOMPLETO, RESPALDO, NO_DISPONIBLE)

METODO_RESPALDO = "mediana_respaldo"

# Motivos controlados (columna plazo_motivo).
MOTIVO_COSTO_BAJO = "costo_bajo_rango"
MOTIVO_COSTO_ALTO = "costo_sobre_rango"
# Solo con costo_incompleto: el estado ya no puede decir que el tipo no está representado.
MOTIVO_TIPO_NO_REPRESENTADO = "tipo_obra_no_representado"
MOTIVO_SIN_UF = "uf_no_disponible"
MOTIVO_SIN_COSTO = "costo_no_valido"
MOTIVO_SIN_TRADUCCION = "tipo_obra_sin_traduccion"
MOTIVO_SIN_MODELO = "modelo_no_disponible"
MOTIVO_ERROR = "error_estimador"

ZONA_CHILE = "America/Santiago"


class ModeloInvalido(ValueError):
    pass


@dataclass(frozen=True)
class ModeloPlazo:
    version: str
    metodo: str
    provisional: bool
    alpha: float
    beta: float
    gamma: float
    q_inf: float
    q_sup: float
    respaldo_dias: float
    respaldo_q_inf: float
    respaldo_q_sup: float
    tipo_a_clase: dict
    traduccion: dict
    costo_uf_min: float
    costo_uf_max: float
    tipos_representados: frozenset

    @classmethod
    def desde_json(cls, datos: dict) -> "ModeloPlazo":
        try:
            if datos["formato"] != 1 or datos["objetivo"] != "plazo" or datos["algoritmo"] != "parametrica":
                raise ModeloInvalido("formato, objetivo o algoritmo no soportado")
            p, i, r, d = datos["parametros"], datos["intervalo"], datos["mediana_respaldo"], datos["dominio"]
            modelo = cls(
                version=str(datos["version"]),
                metodo=str(datos["metodo"]),
                provisional=bool(datos["provisional"]),
                alpha=float(p["alpha"]), beta=float(p["beta"]), gamma=float(p["gamma"]),
                q_inf=float(i["q_inf_log"]), q_sup=float(i["q_sup_log"]),
                respaldo_dias=float(r["plazo_dias"]),
                respaldo_q_inf=float(r["q_inf_log"]), respaldo_q_sup=float(r["q_sup_log"]),
                tipo_a_clase=dict(datos["tipo_a_clase"]),
                traduccion=dict(datos["traduccion_tipo_obra"]),
                costo_uf_min=float(d["costo_uf_min"]), costo_uf_max=float(d["costo_uf_max"]),
                tipos_representados=frozenset(d["tipos_obra_representados"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ModeloInvalido(f"parámetros del modelo incompletos: {error}") from error

        numeros = (modelo.alpha, modelo.beta, modelo.gamma, modelo.q_inf, modelo.q_sup,
                   modelo.respaldo_q_inf, modelo.respaldo_q_sup, modelo.costo_uf_min, modelo.costo_uf_max)
        if not all(math.isfinite(n) for n in numeros) or modelo.respaldo_dias < 1:
            raise ModeloInvalido("parámetros no finitos")
        if not 0 < modelo.costo_uf_min <= modelo.costo_uf_max:
            raise ModeloInvalido("dominio de costo inválido")
        if not set(modelo.traduccion.values()) <= set(modelo.tipo_a_clase):
            raise ModeloInvalido("la traducción usa tipos fuera del vocabulario")
        return modelo


@dataclass(frozen=True)
class ResultadoPlazo:
    estado: str
    motivo: Optional[str] = None
    plazo_dias: Optional[int] = None
    plazo_min_dias: Optional[int] = None
    plazo_max_dias: Optional[int] = None
    metodo: Optional[str] = None
    provisional: Optional[bool] = None
    version_modelo: Optional[str] = None
    tipo_obra_modelo: Optional[str] = None
    uf_valor: Optional[Decimal] = None
    uf_fecha: Optional[date] = None

    @property
    def fuera_dominio(self) -> bool:
        return self.estado != DENTRO_DOMINIO

    def a_columnas(self) -> dict:
        """Columnas de estimaciones (migración 009)."""
        return {
            "plazo_dias": self.plazo_dias,
            "plazo_min_dias": self.plazo_min_dias,
            "plazo_max_dias": self.plazo_max_dias,
            "plazo_metodo": self.metodo,
            "plazo_provisional": self.provisional,
            "plazo_estado": self.estado,
            "plazo_motivo": self.motivo,
            "version_modelo": self.version_modelo,
            "tipo_obra_modelo": self.tipo_obra_modelo,
            "uf_valor": None if self.uf_valor is None else str(self.uf_valor),
            "uf_fecha": None if self.uf_fecha is None else self.uf_fecha.isoformat(),
        }


def no_disponible(motivo: str) -> ResultadoPlazo:
    return ResultadoPlazo(estado=NO_DISPONIBLE, motivo=motivo)


# --- Carga (una vez por proceso) --------------------------------------------------

def version_vigente() -> str:
    return os.getenv(VARIABLE_VERSION, "").strip() or VERSION_POR_DEFECTO


@lru_cache(maxsize=4)
def cargar_modelo(version: str) -> ModeloPlazo:
    # lru_cache no guarda excepciones: un archivo que falta se vuelve a intentar.
    ruta = DIR_MODELOS / f"plazo_{version}.json"
    modelo = ModeloPlazo.desde_json(json.loads(ruta.read_text(encoding="utf-8")))
    if modelo.version != version:
        raise ModeloInvalido(f"el archivo {ruta.name} declara la versión {modelo.version}")
    return modelo


# --- Fecha y UF -------------------------------------------------------------------

def fecha_chile(ahora: Optional[datetime] = None) -> date:
    """Día de la estimación en Chile: la UF se busca para ese día."""
    ahora = ahora or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return ahora.astimezone(ZoneInfo(ZONA_CHILE)).date()
    except Exception:  # noqa: BLE001 - sin base de zonas (Windows sin tzdata)
        return ahora.date()


def buscar_uf(cliente, fecha: date) -> Optional[Decimal]:
    """UF del día desde valores_uf. None si no está: no hay otra fuente."""
    respuesta = (
        cliente.table("valores_uf")
        .select("valor")
        .eq("fecha", fecha.isoformat())
        .maybe_single()
        .execute()
    )
    fila = respuesta.data if respuesta is not None else None
    return Decimal(str(fila["valor"])) if fila and fila.get("valor") is not None else None


# --- Predicción (idéntica a ml/src/predict.py) ------------------------------------

def _armar(log_pred: float, q_inf: float, q_sup: float) -> tuple:
    plazo = max(1, int(round(math.exp(log_pred))))
    minimo = max(1, math.floor(math.exp(log_pred + q_inf)))
    maximo = math.ceil(math.exp(log_pred + q_sup))
    return plazo, min(minimo, plazo), max(maximo, plazo)


def predecir_p2(modelo: ModeloPlazo, tipo_modelo: str, costo_uf: float) -> tuple:
    edif = int(modelo.tipo_a_clase[tipo_modelo] == "edificacion")
    log_pred = max(modelo.alpha + modelo.beta * math.log(costo_uf) + modelo.gamma * edif, 0.0)
    return _armar(log_pred, modelo.q_inf, modelo.q_sup)


def predecir_respaldo(modelo: ModeloPlazo) -> tuple:
    return _armar(math.log(modelo.respaldo_dias), modelo.respaldo_q_inf, modelo.respaldo_q_sup)


def _costo(valor) -> Optional[float]:
    try:
        numero = float(Decimal(str(valor)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


def _estimar(modelo: ModeloPlazo, tipo_obra: str, costo_total, completa: bool, fecha: date,
             buscar_uf: Callable[[date], Optional[Decimal]]) -> ResultadoPlazo:
    tipo_modelo = modelo.traduccion.get(tipo_obra)
    if tipo_modelo is None:
        return no_disponible(MOTIVO_SIN_TRADUCCION)

    base = dict(version_modelo=modelo.version, tipo_obra_modelo=tipo_modelo, provisional=True)

    costo = _costo(costo_total)
    try:
        uf = buscar_uf(fecha) if costo is not None else None
    except Exception as error:  # noqa: BLE001 - la UF no debe tumbar la estimación
        logger.warning("No se pudo leer la UF del %s: %s", fecha, type(error).__name__)
        uf = None

    if costo is None or uf is None or uf <= 0:
        plazo, minimo, maximo = predecir_respaldo(modelo)
        return ResultadoPlazo(
            estado=RESPALDO, motivo=MOTIVO_SIN_COSTO if costo is None else MOTIVO_SIN_UF,
            plazo_dias=plazo, plazo_min_dias=minimo, plazo_max_dias=maximo, metodo=METODO_RESPALDO, **base,
        )

    costo_uf = costo / float(uf)
    plazo, minimo, maximo = predecir_p2(modelo, tipo_modelo, costo_uf)

    # El costo fuera de rango queda en el motivo aunque domine otra etiqueta.
    motivo = (MOTIVO_COSTO_BAJO if costo_uf < modelo.costo_uf_min
              else MOTIVO_COSTO_ALTO if costo_uf > modelo.costo_uf_max else None)

    # Una sola etiqueta, por prioridad: lo más limitante primero.
    if not completa:
        estado = COSTO_INCOMPLETO
        # Que además esté fuera del dominio no debe perderse: el tipo pesa más que el costo.
        if tipo_modelo not in modelo.tipos_representados:
            motivo = MOTIVO_TIPO_NO_REPRESENTADO
    elif tipo_modelo not in modelo.tipos_representados:
        estado = TIPO_NO_REPRESENTADO
    elif motivo is not None:
        estado = FUERA_RANGO_COSTO
    else:
        estado = DENTRO_DOMINIO

    return ResultadoPlazo(
        estado=estado, motivo=motivo, plazo_dias=plazo, plazo_min_dias=minimo, plazo_max_dias=maximo,
        metodo=modelo.metodo, uf_valor=Decimal(str(uf)).quantize(Decimal("0.01")), uf_fecha=fecha, **base,
    )


def estimar(
    tipo_obra: str,
    costo_total,
    completa: bool,
    fecha: date,
    buscar_uf: Callable[[date], Optional[Decimal]],
    version: Optional[str] = None,
) -> ResultadoPlazo:
    """Plazo de una estimación ya costeada. Nunca lanza.

    `buscar_uf(fecha)` devuelve la UF del día o None (ver `buscar_uf(cliente, fecha)`).
    """
    version = version or version_vigente()
    try:
        modelo = cargar_modelo(version)
    except Exception as error:  # noqa: BLE001
        logger.error("Modelo de plazo %s no disponible: %s", version, type(error).__name__)
        return no_disponible(MOTIVO_SIN_MODELO)
    try:
        return _estimar(modelo, tipo_obra, costo_total, completa, fecha, buscar_uf)
    except Exception as error:  # noqa: BLE001
        logger.error("Falló la estimación de plazo (%s): %s", version, type(error).__name__)
        return no_disponible(MOTIVO_ERROR)
