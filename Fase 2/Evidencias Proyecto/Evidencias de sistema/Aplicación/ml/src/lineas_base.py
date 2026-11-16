"""Líneas base del modelo de plazo (criterios_inclusion.md).

- Mediana: mediana de `plazo_dias` de los casos reales de entrenamiento.
- P1: días por m², mediana de `plazo_dias / superficie_m2` por `clase_obra`
  (f_pisos = f_estandar = 1, porque no hay datos reales de pisos ni estándar).
  Solo predice casos con superficie.
- P2: plazo por costo. log(plazo) = α + β·log(costo_neto_uf) + γ·edificacion.
  β: Theil–Sen (mediana de las pendientes entre todos los pares de casos con
  log UF distinto). α: mediana de los residuos log(plazo) − β·log UF de todos
  los casos de entrenamiento. γ: mediana de los residuos log(plazo) − (α + β·log UF)
  de los casos de edificación.

Todas usan solo filas `origen_dato = real` (los sintéticos nunca calibran líneas
base) y exponen `ajustar(df) -> self` y `predecir(df) -> np.ndarray` en días.
Las columnas esperadas en `df` son las que arma `evaluacion.cargar_casos`:
`log_uf`, `edif` (0/1), `plazo_dias`, `superficie_m2`, `clase_obra`, `origen_dato`.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def _reales(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["origen_dato"] == "real"]


class Mediana:
    nombre = "mediana"

    def ajustar(self, df: pd.DataFrame) -> "Mediana":
        self.valor = float(np.median(_reales(df)["plazo_dias"]))
        return self

    def predecir(self, df: pd.DataFrame) -> np.ndarray:
        return np.full(len(df), self.valor)


class P1:
    """Días por m² por clase. Si la clase no tiene casos con superficie en el
    entrenamiento, usa la mediana de días/m² de todos los casos con superficie."""

    nombre = "P1"

    def ajustar(self, df: pd.DataFrame) -> "P1":
        r = _reales(df).dropna(subset=["superficie_m2"])
        tasa = r["plazo_dias"] / r["superficie_m2"]
        self.tasa_global = float(np.median(tasa))
        self.tasa_clase = {c: float(np.median(tasa[r["clase_obra"] == c]))
                           for c in r["clase_obra"].unique()}
        return self

    def predecir(self, df: pd.DataFrame) -> np.ndarray:
        tasas = df["clase_obra"].map(self.tasa_clase).fillna(self.tasa_global)
        return np.maximum(1.0, tasas.to_numpy() * df["superficie_m2"].to_numpy())


def theil_sen(x: np.ndarray, y: np.ndarray) -> float:
    pendientes = [(y[j] - y[i]) / (x[j] - x[i])
                  for i, j in combinations(range(len(x)), 2) if x[j] != x[i]]
    return float(np.median(pendientes))


class P2:
    nombre = "P2"

    def ajustar(self, df: pd.DataFrame) -> "P2":
        r = _reales(df)
        x = r["log_uf"].to_numpy()
        y = np.log(r["plazo_dias"].to_numpy(dtype=float))
        e = r["edif"].to_numpy()
        self.beta = theil_sen(x, y)
        self.alpha = float(np.median(y - self.beta * x))
        resid = y - (self.alpha + self.beta * x)
        self.gamma = float(np.median(resid[e == 1])) if (e == 1).any() else 0.0
        resid_final = resid - self.gamma * e
        self.residuos_log = resid_final
        return self

    def predecir_log(self, df: pd.DataFrame) -> np.ndarray:
        return self.alpha + self.beta * df["log_uf"].to_numpy() + self.gamma * df["edif"].to_numpy()

    def predecir(self, df: pd.DataFrame) -> np.ndarray:
        return np.maximum(1.0, np.exp(self.predecir_log(df)))

    def parametros(self) -> dict[str, float]:
        return {"alpha": self.alpha, "beta": self.beta, "gamma": self.gamma}
