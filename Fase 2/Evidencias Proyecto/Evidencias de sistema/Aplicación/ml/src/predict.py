"""Predicción del plazo para el backend (HU-15/HU-17).

Contrato:
    predecir_plazo(tipo_obra, costo_neto_clp, fecha) -> dict con
        plazo_dias, intervalo_min_dias, intervalo_max_dias (int, 1 ≤ min ≤ plazo ≤ max),
        version_modelo (str), metodo (str), validado (bool), provisional (bool)

- `tipo_obra` debe pertenecer al vocabulario cerrado del diccionario; si no, ValueError.
  La clase (edificación / puntual) se deduce con el mapeo determinista del artefacto.
- `costo_neto_clp`: costo_total del motor (CLP, sin IVA). Se convierte a UF con la UF
  CMF del día `fecha` (date o 'AAAA-MM-DD'), usando `uf.uf_del_dia` y su caché.
- Respaldo: si el costo es None, no numérico o ≤ 0, o si no hay UF para la fecha
  (fecha None, mal formada, fuera de la serie o la CMF no responde), se devuelve la
  mediana del entrenamiento con metodo = "mediana_respaldo" y validado = False,
  siempre, porque ese camino no es el método validado.
- Intervalo: plazo × exp(q_inf) y plazo × exp(q_sup), con q los percentiles 10/90
  (Weibull) de los residuos log LOO del método. min se redondea hacia abajo y max
  hacia arriba; luego se fuerza 1 ≤ min ≤ plazo ≤ max.

El artefacto se carga una sola vez por proceso (functools.lru_cache). Su ruta es
`BUILDCAST_MODELO_PLAZO` si esa variable de entorno existe; si no, ARTEFACTO_POR_DEFECTO.
"""

from __future__ import annotations

import math
import os
from datetime import date
from functools import lru_cache
from numbers import Real
from pathlib import Path

import joblib
import numpy as np

from uf import uf_del_dia

RAIZ_ML = Path(__file__).resolve().parents[1]
ARTEFACTO_POR_DEFECTO = RAIZ_ML / "models" / "plazo_v1.0-2026-11-01.joblib"
VARIABLE_RUTA = "BUILDCAST_MODELO_PLAZO"


@lru_cache(maxsize=4)
def cargar_artefacto(ruta: str) -> dict:
    return joblib.load(ruta)


def _artefacto() -> dict:
    return cargar_artefacto(os.environ.get(VARIABLE_RUTA, str(ARTEFACTO_POR_DEFECTO)))


def _costo_valido(costo) -> bool:
    return (isinstance(costo, Real) and not isinstance(costo, bool)
            and math.isfinite(costo) and costo > 0)


def _uf_o_none(fecha: date | str | None) -> float | None:
    if fecha is None:
        return None
    try:
        return float(uf_del_dia(fecha))
    except (ValueError, TypeError, SystemExit):
        # SystemExit: uf.py lo lanza si la CMF no responde o falta la clave.
        return None


def _log_prediccion(art: dict, log_uf: float, edif: int) -> float:
    if art["algoritmo"] == "parametrica":
        p = art["parametros"]
        log_pred = p["alpha"] + p["beta"] * log_uf + p["gamma"] * edif
    else:
        log_pred = float(art["estimador"].predict(np.array([[log_uf, edif]], dtype=float))[0])
    return max(log_pred, 0.0)  # plazo ≥ 1 día


def _armar(log_pred: float, q_inf: float, q_sup: float) -> tuple[int, int, int]:
    plazo = max(1, int(round(math.exp(log_pred))))
    minimo = max(1, math.floor(math.exp(log_pred + q_inf)))
    maximo = math.ceil(math.exp(log_pred + q_sup))
    minimo = min(minimo, plazo)
    maximo = max(maximo, plazo)
    return plazo, minimo, maximo


def predecir_plazo(tipo_obra: str, costo_neto_clp, fecha: date | str | None) -> dict:
    art = _artefacto()
    if tipo_obra not in art["tipo_a_clase"]:
        raise ValueError(
            f"tipo_obra '{tipo_obra}' no está en el vocabulario: {sorted(art['tipo_a_clase'])}"
        )
    edif = int(art["tipo_a_clase"][tipo_obra] == "edificacion")

    uf = _uf_o_none(fecha) if _costo_valido(costo_neto_clp) else None
    if uf is None:
        resp = art["mediana_respaldo"]
        log_pred = math.log(resp["plazo_dias"])
        q_inf, q_sup = resp["q_inf_log"], resp["q_sup_log"]
        metodo, validado, provisional = "mediana_respaldo", False, True
    else:
        log_pred = _log_prediccion(art, math.log(costo_neto_clp / uf), edif)
        q_inf, q_sup = art["intervalo"]["q_inf_log"], art["intervalo"]["q_sup_log"]
        metodo, validado, provisional = art["metodo"], bool(art["validado"]), bool(art["provisional"])

    plazo, minimo, maximo = _armar(log_pred, q_inf, q_sup)
    return {
        "plazo_dias": plazo,
        "intervalo_min_dias": minimo,
        "intervalo_max_dias": maximo,
        "version_modelo": art["version"],
        "metodo": metodo,
        "validado": validado,
        "provisional": provisional,
    }
