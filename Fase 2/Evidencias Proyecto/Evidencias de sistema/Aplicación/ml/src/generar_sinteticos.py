"""Generador de presupuestos sintéticos para estabilizar el ajuste (HU-13/HU-14).

Los sintéticos SOLO entran al entrenamiento de los candidatos. Nunca calibran
las líneas base ni entran a ninguna evaluación. No aportan información nueva:
reproducen la relación de P2 observada en los casos reales que reciben.

Reglas (todas explícitas):
1. Entrada: los casos reales de entrenamiento de un pliegue. Dentro del LOO se
   llama con el pliegue, nunca con el caso evaluado, así que no hay fuga.
2. Cantidad: N_SINTETICOS = 24 filas (el doble de los 12 reales de entrenamiento
   de cada pliegue), repartidas por clase_obra en la misma proporción que los
   reales, con al menos 1 fila por clase presente.
3. log(costo_neto_uf): uniforme entre el mínimo y el máximo de log UF de los
   reales de esa clase. No se extrapola fuera del rango observado.
4. tipo_obra: muestreado de los tipos reales de esa clase (frecuencia empírica).
5. Plazo: log(plazo) = α + β·log UF + γ·edif + ε, con α, β, γ de P2 ajustada con
   esos mismos reales y ε remuestreado (con reemplazo) de los residuos log de P2
   en esos reales. plazo_dias = max(1, round(exp(·))).
6. origen_dato = sintetico, tipo_plazo = ofertado, id_caso S0001…
7. Semilla fija: SEMILLA_BASE + desplazamiento (el número de pliegue en el LOO).

Uso por línea de comandos (genera con los 13 casos de entrenamiento final y
escribe un CSV de ejemplo para inspección):
    python ml/src/generar_sinteticos.py [ruta_salida]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from lineas_base import P2

SEMILLA_BASE = 20261101
N_SINTETICOS = 24


def generar(reales: pd.DataFrame, n: int = N_SINTETICOS, desplazamiento: int = 0) -> pd.DataFrame:
    reales = reales[reales["origen_dato"] == "real"]
    rng = np.random.default_rng(SEMILLA_BASE + desplazamiento)
    p2 = P2().ajustar(reales)
    residuos = p2.residuos_log

    conteo = reales["clase_obra"].value_counts()
    cuotas = {c: max(1, int(round(n * k / len(reales)))) for c, k in conteo.items()}

    filas = []
    for clase, cuota in sorted(cuotas.items()):
        r = reales[reales["clase_obra"] == clase]
        lo, hi = r["log_uf"].min(), r["log_uf"].max()
        tipos = r["tipo_obra"].to_numpy()
        edif = int(clase == "edificacion")
        for _ in range(cuota):
            log_uf = float(rng.uniform(lo, hi))
            eps = float(rng.choice(residuos))
            plazo = max(1, int(round(np.exp(p2.alpha + p2.beta * log_uf + p2.gamma * edif + eps))))
            filas.append({
                "clase_obra": clase,
                "tipo_obra": str(rng.choice(tipos)),
                "log_uf": log_uf,
                "costo_neto_uf": round(float(np.exp(log_uf)), 2),
                "edif": edif,
                "plazo_dias": plazo,
                "superficie_m2": np.nan,
                "origen_dato": "sintetico",
                "tipo_plazo": "ofertado",
                "plazo_es_cota": False,
            })
    sint = pd.DataFrame(filas)
    sint.insert(0, "id_caso", [f"S{i:04d}" for i in range(1, len(sint) + 1)])
    return sint


def main(argv: list[str]) -> int:
    from evaluacion import cargar_casos

    salida = Path(argv[1]) if len(argv) > 1 else None
    entrenamiento, _ = cargar_casos()
    sint = generar(entrenamiento)
    print(f"{len(sint)} sintéticos generados (semilla {SEMILLA_BASE}) "
          f"a partir de {len(entrenamiento)} reales: {sint['clase_obra'].value_counts().to_dict()}")
    if salida:
        sint.to_csv(salida, index=False, encoding="utf-8")
        print(f"Escrito en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
