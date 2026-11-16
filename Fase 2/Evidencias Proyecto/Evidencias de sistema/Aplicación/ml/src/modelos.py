"""Modelos candidatos del plazo (HU-14).

Los tres usan las mismas dos variables: `log_uf` (logaritmo de costo_neto_uf) y
`edif` (1 si clase_obra = edificacion). El objetivo es log(plazo_dias) y la
predicción se devuelve en días con exp(·), igual que P2, para que los
residuos sean multiplicativos y comparables.

Hiperparámetros fijados a priori (con 12 casos de evaluación no se hace
búsqueda anidada; cualquier ajuste con los mismos 12 casos inflaría el MAE LOO):
- Ridge: alpha = 1.0 sobre log_uf estandarizado y edif sin escalar.
- kNN: k = 3, pesos uniformes, distancia euclídea sobre [log_uf estandarizado, edif].
  Una diferencia de clase pesa lo mismo que una desviación estándar de log UF.
- Árbol: max_depth = 2, min_samples_leaf = 2, random_state = 0.

Los sintéticos, si se usan, entran como filas adicionales con el mismo peso.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor

VARIABLES = ["log_uf", "edif"]
SEMILLA = 0


def _escalar_log_uf() -> ColumnTransformer:
    return ColumnTransformer([("log_uf", StandardScaler(), [0])], remainder="passthrough")


def construir(nombre: str):
    if nombre == "ridge":
        return Pipeline([("esc", _escalar_log_uf()), ("modelo", Ridge(alpha=1.0))])
    if nombre == "knn":
        return Pipeline([("esc", _escalar_log_uf()), ("modelo", KNeighborsRegressor(n_neighbors=3))])
    if nombre == "arbol":
        return DecisionTreeRegressor(max_depth=2, min_samples_leaf=2, random_state=SEMILLA)
    raise ValueError(f"modelo desconocido: {nombre}")


CANDIDATOS = ["ridge", "knn", "arbol"]


class Candidato:
    def __init__(self, nombre: str):
        self.nombre = nombre

    def ajustar(self, df: pd.DataFrame) -> "Candidato":
        self.estimador = construir(self.nombre)
        self.estimador.fit(df[VARIABLES].to_numpy(dtype=float),
                           np.log(df["plazo_dias"].to_numpy(dtype=float)))
        return self

    def predecir(self, df: pd.DataFrame) -> np.ndarray:
        return np.maximum(1.0, np.exp(self.estimador.predict(df[VARIABLES].to_numpy(dtype=float))))
