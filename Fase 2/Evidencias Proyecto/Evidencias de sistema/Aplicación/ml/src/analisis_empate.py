"""Análisis de sensibilidad de la selección P2 frente a Ridge (v1.0-2026-11-01).

Usa el mismo protocolo LOO de `evaluacion.py`: 12 casos reales de evaluación y
R08 (35 días) en el entrenamiento de cada pliegue, salvo donde se indique.
Calcula e imprime, sin escribir ningún archivo:

1. Diferencia pareada por caso |e_P2| − |e_Ridge|: media (= diferencia de MAE),
   DE (ddof = 1 y 0), error estándar SE = DE(ddof=1)/√n, cociente media/SE,
   casos ganados por cada método, Wilcoxon pareado de dos colas
   (zero_method="wilcox"; exacto y aproximación normal sin corrección) y t
   pareada como referencia.
2. Intervalo de P2 y de Ridge: percentiles 10/90 (Weibull) de los residuos log
   LOO, factores multiplicativos, cobertura in-sample y LOO anidada, y cómo se
   ve un plazo central de 12 días.
3. MAE, RMSE y DE de Ridge y P2 con R08 y sin R08 en el entrenamiento,
   evaluando siempre en los mismos 12 casos.
4. Efecto de excluir R05 solo del cálculo de los residuos del intervalo
   (modelos y predicciones sin cambios).

Uso (desde la raíz del repo):
    ml/.venv/Scripts/python ml/src/analisis_empate.py
"""
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no deja __pycache__ en el repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import numpy as np
import pandas as pd
from scipy import stats

from evaluacion import (METODO_PERCENTIL, PERCENTILES_INTERVALO, cargar_casos,
                        comparar_pareado, intervalo, loo, metricas, residuos_log)
from modelos import Candidato

entr, ev = cargar_casos()
r = loo(entr, ev)
preds = r["preds"]
ids = ev["id_caso"].tolist()
y = ev["plazo_dias"].to_numpy()
p2 = np.array([preds["P2"][i] for i in ids])
rg = np.array([preds["ridge"][i] for i in ids])
e2, er = np.abs(y - p2), np.abs(y - rg)
# Núcleo pareado compartido con evaluacion.seleccionar (sin duplicar la lógica).
c = comparar_pareado(y, p2, rg)
d = np.array(c["dif_por_caso"])
n = c["n"]
se = c["se_dif"]

print("== 1. Diferencia pareada |e_P2| - |e_Ridge| ==")
tab = pd.DataFrame({"id": ids, "real": y, "pred_P2": p2, "pred_Ridge": rg,
                    "ae_P2": e2, "ae_Ridge": er, "dif": d})
print(tab.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
print(f"media = {c['dif_mae']:.3f}  DE(ddof=1) = {c['de_dif_ddof1']:.3f}  DE(ddof=0) = {d.std(ddof=0):.3f}")
print(f"SE = DE(ddof=1)/sqrt({n}) = {se:.3f}   media/SE = {c['cociente_dif_se']:.3f}")
print(f"gana Ridge (dif>0): {c['ganados_candidato']}  gana P2 (dif<0): {c['ganados_linea_base']}  empates (|dif|<1e-9): {(np.abs(d) < 1e-9).sum()}")
print(f"MAE P2 = {e2.mean():.3f}  MAE Ridge = {er.mean():.3f}")
absd = np.abs(d)
print(f"ceros: {(absd < 1e-12).sum()}  |dif| repetidas: {len(absd) - len(np.unique(np.round(absd, 12)))}")
w_ap = stats.wilcoxon(d, zero_method="wilcox", alternative="two-sided", method="approx", correction=False)
etiqueta_w = "exacto" if c["wilcoxon_metodo"] == "exact" else "aprox. (hay ceros o empates)"
print(f"Wilcoxon {etiqueta_w}: W = {c['wilcoxon_estadistico']:.3f}  p = {c['wilcoxon_p']:.4f}")
print(f"Wilcoxon aprox. normal (sin corrección de continuidad): W = {w_ap.statistic:.3f}  p = {w_ap.pvalue:.4f}")
tcrit = stats.t.ppf(0.975, n - 1)
print(f"referencia: t pareada = {d.mean() / se:.3f}, p = {2 * stats.t.sf(abs(d.mean() / se), n - 1):.4f} (t crítico 0,975 con {n-1} gl = {tcrit:.3f})")


def armar(f_inf, f_sup, central=12):
    plazo = central
    mn = min(max(1, math.floor(central * f_inf)), plazo)
    mx = max(math.ceil(central * f_sup), plazo)
    return f"{mn}–{mx}"


def fila(nombre, res):
    iv = intervalo(res)
    return {"metodo": nombre, "n_res": iv["n_residuos"], "q10": iv["q_inf_log"], "q90": iv["q_sup_log"],
            "f_inf": iv["factor_inf"], "f_sup": iv["factor_sup"],
            "cob_in": iv["cobertura_in_sample"], "cob_anidada": iv["cobertura_loo_anidada"],
            "12_dias": armar(iv["factor_inf"], iv["factor_sup"])}


res_p2 = residuos_log(ev, preds["P2"])
res_rg = residuos_log(ev, preds["ridge"])
print(f"\n== 2. Intervalo (P{PERCENTILES_INTERVALO[0]}/P{PERCENTILES_INTERVALO[1]}, {METODO_PERCENTIL}, log, multiplicativo) ==")
print(pd.DataFrame([fila("P2", res_p2), fila("Ridge", res_rg)]).to_string(index=False, float_format=lambda v: f"{v:6.3f}"))
print("residuos log ordenados P2:   ", np.round(np.sort(res_p2), 3).tolist())
print("residuos log ordenados Ridge:", np.round(np.sort(res_rg), 3).tolist())

print("\n== 3. Ridge con y sin R08 en el entrenamiento (evaluación en los mismos 12) ==")
sin = {}
for k, f in ev.iterrows():
    train = entr[(entr["id_caso"] != f["id_caso"]) & (entr["id_caso"] != "R08")]
    sin[f["id_caso"]] = float(Candidato("ridge").ajustar(train).predecir(ev.iloc[[k]])[0])
filas = []
for nombre, pr in [("Ridge con R08", preds["ridge"]), ("Ridge sin R08", sin),
                   ("P2 con R08", preds["P2"]), ("P2 sin R08", preds["P2_sin_R08"])]:
    m = metricas(y, np.array([pr[i] for i in ids]))
    filas.append({"metodo": nombre, **{k: m[k] for k in ("mae", "rmse", "sd_ae", "ae_min", "ae_max")}})
print(pd.DataFrame(filas).to_string(index=False, float_format=lambda v: f"{v:6.3f}"))
print("n de entrenamiento por pliegue: con R08 = 12, sin R08 = 11")

print("\n== 4. Efecto de R05 en el cálculo de residuos (modelos y predicciones iguales) ==")
i05 = ids.index("R05")
print(f"residuo log de R05: P2 = {res_p2[i05]:.3f}, Ridge = {res_rg[i05]:.3f}")
filas = []
for nombre, res in [("P2", res_p2), ("Ridge", res_rg)]:
    for etiqueta, base in [("con R05", res), ("sin R05", np.delete(res, i05))]:
        q10, q90 = np.percentile(base, PERCENTILES_INTERVALO, method=METODO_PERCENTIL)
        cob12 = np.mean((res >= q10) & (res <= q90))
        cob11 = np.mean((np.delete(res, i05) >= q10) & (np.delete(res, i05) <= q90))
        filas.append({"metodo": nombre, "residuos": etiqueta, "n": len(base), "q10": q10, "q90": q90,
                      "f_inf": math.exp(q10), "f_sup": math.exp(q90),
                      "12_dias": armar(math.exp(q10), math.exp(q90)),
                      "cob_12": cob12, "cob_11_sin_R05": cob11,
                      "R05_dentro": bool(q10 <= res[i05] <= q90)})
print(pd.DataFrame(filas).to_string(index=False, float_format=lambda v: f"{v:6.3f}"))
