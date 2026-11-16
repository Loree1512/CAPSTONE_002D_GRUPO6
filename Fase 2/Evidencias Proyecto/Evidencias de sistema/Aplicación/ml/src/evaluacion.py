"""Evaluación leave-one-out común para líneas base y candidatos (HU-14).

Conjuntos (decisión de la usuaria, 2026-11-01):
- Evaluación: 12 casos = 14 utilizables − R08 (plazo como cota) − R07 (sin UF).
- Entrenamiento de cada pliegue: los otros 11 casos de evaluación + R08 (35 días).
- R08 se predice aparte, con el método entrenado en los 12 casos de evaluación,
  y se informa si la predicción respeta la cota (≤ 35 días).
- R07 queda fuera de todo, también de la mediana.
- Los sintéticos (si se usan) se generan dentro de cada pliegue a partir de sus
  reales de entrenamiento y nunca se evalúan.

Métricas en días sobre los 12 pliegues: MAE, RMSE, desviación estándar (ddof=1)
y rango del error absoluto; R² solo informativo.

Uso:
    ml/.venv/Scripts/python ml/src/evaluacion.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from generar_sinteticos import generar
from lineas_base import P1, P2, Mediana
from modelos import CANDIDATOS, Candidato
from validar_dataset import TIPOS_EDIFICACION, TIPOS_PUNTUAL

RAIZ_ML = Path(__file__).resolve().parents[1]
CSV = RAIZ_ML / "data" / "processed" / "presupuestos_reales.csv"

TIPO_A_CLASE = {**{t: "edificacion" for t in TIPOS_EDIFICACION},
                **{t: "puntual" for t in TIPOS_PUNTUAL}}

ID_COTA = "R08"
PERCENTILES_INTERVALO = (10, 90)
# Definición de percentil de Weibull, h = (n + 1)·p: con 12 residuos, P10 interpola
# entre el 1.º y el 2.º valor ordenado y P90 entre el 11.º y el 12.º. Para un caso
# nuevo intercambiable con los 12, la probabilidad esperada de quedar entre esos
# percentiles es 0,8. La definición lineal por defecto de numpy (h = (n − 1)·p)
# los ubicaría entre el 2.º–3.º y el 10.º–11.º.
METODO_PERCENTIL = "weibull"
LINEAS_BASE_COMPLETAS = ["mediana", "P2"]  # las que cubren los 12 casos


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def cargar_casos(ruta: Path = CSV) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (entrenamiento_final, evaluacion): 13 y 12 filas reales."""
    df = pd.read_csv(ruta, encoding="utf-8-sig", dtype={"id_caso": str})
    df = df[(df["utilizable"] == True) & (df["origen_dato"] == "real")].copy()  # noqa: E712
    df = df[df["costo_neto_uf"].notna()].copy()  # excluye R07 (sin fecha -> sin UF)
    clase_mapeada = df["tipo_obra"].map(TIPO_A_CLASE)
    if (clase_mapeada != df["clase_obra"]).any():
        malos = df.loc[clase_mapeada != df["clase_obra"], "id_caso"].tolist()
        raise SystemExit(f"ERROR: clase_obra no coincide con el mapeo de tipo_obra en {malos}")
    df["log_uf"] = np.log(df["costo_neto_uf"].astype(float))
    df["edif"] = (df["clase_obra"] == "edificacion").astype(int)
    df["plazo_dias"] = df["plazo_dias"].astype(float)
    df = df.reset_index(drop=True)
    evaluacion = df[df["plazo_es_cota"] == False].reset_index(drop=True)  # noqa: E712
    return df, evaluacion


# ---------------------------------------------------------------------------
# Métodos
# ---------------------------------------------------------------------------

def _fabricas() -> dict[str, tuple]:
    """nombre -> (constructor, usa_sinteticos, excluye_R08_del_entrenamiento)."""
    f = {
        "mediana": (Mediana, False, False),
        "P2": (P2, False, False),
        "P2_sin_R08": (P2, False, True),
    }
    for c in CANDIDATOS:
        f[c] = (lambda c=c: Candidato(c), False, False)
        f[f"{c}+sint"] = (lambda c=c: Candidato(c), True, False)
    return f


def _entrenar(nombre: str, train: pd.DataFrame, desplazamiento: int):
    constructor, usa_sint, sin_cota = _fabricas()[nombre]
    if sin_cota:
        train = train[train["id_caso"] != ID_COTA]
    if usa_sint:
        train = pd.concat([train, generar(train, desplazamiento=desplazamiento)], ignore_index=True)
    return constructor().ajustar(train)


def loo(entrenamiento: pd.DataFrame, evaluacion: pd.DataFrame) -> dict:
    """Predicciones LOO por método. Devuelve {metodo: {id_caso: pred}} y P1 aparte."""
    preds: dict[str, dict[str, float]] = {m: {} for m in _fabricas()}
    preds["P1"] = {}
    params_p2 = []
    for k, fila in evaluacion.iterrows():
        train = entrenamiento[entrenamiento["id_caso"] != fila["id_caso"]]
        caso = evaluacion.iloc[[k]]
        for m in _fabricas():
            modelo = _entrenar(m, train, desplazamiento=k)
            preds[m][fila["id_caso"]] = float(modelo.predecir(caso)[0])
            if m == "P2":
                params_p2.append({"excluido": fila["id_caso"], **modelo.parametros()})
        if pd.notna(fila["superficie_m2"]):
            preds["P1"][fila["id_caso"]] = float(P1().ajustar(train).predecir(caso)[0])

    # R08: entrenado con los 12 de evaluación.
    cota = entrenamiento[entrenamiento["id_caso"] == ID_COTA]
    r08 = {}
    for m in _fabricas():
        if m == "P2_sin_R08":
            continue
        r08[m] = float(_entrenar(m, evaluacion, desplazamiento=len(evaluacion)).predecir(cota)[0])
    if pd.notna(cota["superficie_m2"].iloc[0]):
        r08["P1"] = float(P1().ajustar(evaluacion).predecir(cota)[0])
    return {"preds": preds, "r08": r08, "params_p2": pd.DataFrame(params_p2)}


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def metricas(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    e = np.abs(y - p)
    sst = float(np.sum((y - y.mean()) ** 2))
    return {
        "n": int(len(y)),
        "mae": float(e.mean()),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "sd_ae": float(e.std(ddof=1)) if len(e) > 1 else float("nan"),
        "ae_min": float(e.min()),
        "ae_max": float(e.max()),
        "r2": float(1 - np.sum((y - p) ** 2) / sst) if sst > 0 else float("nan"),
    }


def tabla(evaluacion: pd.DataFrame, preds: dict, ids: list[str] | None = None) -> pd.DataFrame:
    ev = evaluacion if ids is None else evaluacion[evaluacion["id_caso"].isin(ids)]
    filas = []
    for m, d in preds.items():
        sub = ev[ev["id_caso"].isin(d)]
        if len(sub) != len(ev):
            continue
        y = sub["plazo_dias"].to_numpy()
        p = np.array([d[i] for i in sub["id_caso"]])
        filas.append({"metodo": m, **metricas(y, p)})
    return pd.DataFrame(filas).set_index("metodo")


def residuos_log(evaluacion: pd.DataFrame, pred: dict[str, float]) -> np.ndarray:
    y = evaluacion["plazo_dias"].to_numpy()
    p = np.array([pred[i] for i in evaluacion["id_caso"]])
    return np.log(y) - np.log(p)


# ---------------------------------------------------------------------------
# Selección e intervalo
# ---------------------------------------------------------------------------

NO_CANDIDATOS = ("mediana", "P2", "P2_sin_R08", "P1")


def comparar_pareado(y: np.ndarray, pred_base: np.ndarray, pred_cand: np.ndarray) -> dict:
    """Diferencia pareada d = |e_base| − |e_cand| por caso (d > 0: el candidato
    acierta mejor). Devuelve la media (= diferencia de MAE), la DE (ddof = 1), el
    error estándar SE = DE/√n, el cociente media/SE, los casos ganados por cada
    método y los empates, y el Wilcoxon pareado de dos colas (zero_method="wilcox").
    Se usa el método exacto; si hay diferencias nulas o empates en |d|, que el
    exacto no admite, se usa la aproximación normal y se registra el método."""
    y = np.asarray(y, dtype=float)
    e_b = np.abs(y - np.asarray(pred_base, dtype=float))
    e_c = np.abs(y - np.asarray(pred_cand, dtype=float))
    d = e_b - e_c
    n = len(d)
    de = float(d.std(ddof=1))
    se = de / math.sqrt(n)
    absd = np.abs(d)
    hay_ceros = bool((absd == 0).any())
    hay_empates = len(np.unique(absd)) < n
    metodo_w = "approx" if (hay_ceros or hay_empates) else "exact"
    w = stats.wilcoxon(d, zero_method="wilcox", alternative="two-sided", method=metodo_w)
    return {
        "n": int(n),
        "dif_mae": float(d.mean()),
        "de_dif_ddof1": de,
        "se_dif": float(se),
        "cociente_dif_se": float(d.mean() / se) if se > 0 else float("inf"),
        "ganados_candidato": int((d > 0).sum()),
        "ganados_linea_base": int((d < 0).sum()),
        "empates": int((d == 0).sum()),
        "wilcoxon_estadistico": float(w.statistic),
        "wilcoxon_p": float(w.pvalue),
        "wilcoxon_metodo": metodo_w,
        "dif_por_caso": d.tolist(),
    }


def seleccionar(evaluacion: pd.DataFrame, preds: dict) -> dict:
    """Regla de empate corregida (2026-11-01). Compara el mejor candidato con la
    mejor línea base que cubre los 12 casos (mediana o P2): el candidato supera
    si la diferencia de MAE es mayor que el error estándar de la diferencia
    pareada, SE = DE(|e_base| − |e_cand|, ddof=1) / √n.

    Solo informa el veredicto de la regla. **No decide el método vigente**: esa
    decisión está en `entrenar.METODO_VIGENTE` (ver la model card, "Selección").
    """
    t = tabla(evaluacion, preds)
    mejor_base = t.loc[[m for m in LINEAS_BASE_COMPLETAS if m in t.index], "mae"].idxmin()
    cands = t.drop(index=[i for i in t.index if i in NO_CANDIDATOS])
    mejor_cand = cands["mae"].idxmin()
    ids = evaluacion["id_caso"].tolist()
    par = comparar_pareado(evaluacion["plazo_dias"].to_numpy(),
                           np.array([preds[mejor_base][i] for i in ids]),
                           np.array([preds[mejor_cand][i] for i in ids]))
    if par["dif_mae"] <= 0:
        veredicto = "ningun_candidato_mejora"
    elif par["dif_mae"] > par["se_dif"]:
        veredicto = "candidato_supera"
    else:
        veredicto = "empate_tecnico"
    return {
        "regla": "candidato supera si dif_mae > SE = DE(|e_base| - |e_cand|, ddof=1)/sqrt(n)",
        "mejor_linea_base": mejor_base, "mae_mejor_linea_base": float(t.loc[mejor_base, "mae"]),
        "mejor_candidato": mejor_cand, "mae_mejor_candidato": float(t.loc[mejor_cand, "mae"]),
        **{k: v for k, v in par.items() if k != "dif_por_caso"},
        "margen_sobre_se": float(par["dif_mae"] - par["se_dif"]),
        "veredicto": veredicto,
    }


def intervalo(res_log: np.ndarray, pcts=PERCENTILES_INTERVALO) -> dict:
    """Percentiles de residuos log LOO (multiplicativos). Cobertura in-sample
    (por construcción) y cobertura LOO anidada (percentiles sin el caso i)."""
    q_inf, q_sup = (float(v) for v in np.percentile(res_log, pcts, method=METODO_PERCENTIL))
    dentro = np.mean((res_log >= q_inf) & (res_log <= q_sup))
    anidada = []
    for i in range(len(res_log)):
        otros = np.delete(res_log, i)
        a, b = np.percentile(otros, pcts, method=METODO_PERCENTIL)
        anidada.append(a <= res_log[i] <= b)
    return {
        "percentiles": list(pcts), "metodo_percentil": METODO_PERCENTIL, "q_inf_log": q_inf, "q_sup_log": q_sup,
        "factor_inf": float(np.exp(q_inf)), "factor_sup": float(np.exp(q_sup)),
        "cobertura_in_sample": float(dentro), "cobertura_loo_anidada": float(np.mean(anidada)),
        "n_residuos": int(len(res_log)),
    }


def evaluar() -> dict:
    entrenamiento, evaluacion = cargar_casos()
    r = loo(entrenamiento, evaluacion)
    t = tabla(evaluacion, r["preds"])
    sel = seleccionar(evaluacion, r["preds"])
    ids_sup = evaluacion.loc[evaluacion["superficie_m2"].notna(), "id_caso"].tolist()
    return {
        "entrenamiento": entrenamiento, "evaluacion": evaluacion, **r,
        "tabla": t, "seleccion": sel, "ids_superficie": ids_sup,
        "tabla_p1": tabla(evaluacion, r["preds"], ids_sup),
        "tabla_puntual": tabla(evaluacion, r["preds"],
                               evaluacion.loc[evaluacion["edif"] == 0, "id_caso"].tolist()),
        "tabla_edif": tabla(evaluacion, r["preds"],
                            evaluacion.loc[evaluacion["edif"] == 1, "id_caso"].tolist()),
        # Intervalo de cada método que cubre los 12 casos. entrenar.py usa el del
        # método vigente (METODO_VIGENTE) y el de la mediana para el respaldo.
        "intervalos": {m: intervalo(residuos_log(evaluacion, p))
                       for m, p in r["preds"].items() if m != "P1"},
    }


def _fmt(t: pd.DataFrame) -> str:
    return t.to_string(float_format=lambda v: f"{v:6.2f}")


def imprimir(res: dict) -> None:
    ev = res["evaluacion"]
    print("=" * 78)
    print("LOO del modelo de plazo")
    print(f"Evaluación: {len(ev)} casos {ev['id_caso'].tolist()}")
    print(f"Entrenamiento por pliegue: {len(res['entrenamiento']) - 1} reales (11 + {ID_COTA}); "
          "con '+sint' se suman 24 sintéticos generados dentro del pliegue.")
    print("=" * 78)
    print("\n[1] Global, 12 casos (MAE/RMSE/SD/rango en días; R² informativo)")
    print(_fmt(res["tabla"]))
    print(f"\n[2] Subconjunto con superficie {res['ids_superficie']} (P1 aplicable)")
    print(_fmt(res["tabla_p1"]))
    print("\n[3] Por clase: puntual")
    print(_fmt(res["tabla_puntual"]))
    print("\n[3] Por clase: edificación (n = 2, solo descriptivo)")
    print(_fmt(res["tabla_edif"]))
    print(f"\n[4] {ID_COTA} aparte (cota 35 días; entrenado con los 12 de evaluación)")
    for m, p in res["r08"].items():
        print(f"  {m:12s} pred = {p:6.2f}  respeta cota (≤ 35): {'sí' if p <= 35 else 'no'}  |pred − 35| = {abs(p - 35):6.2f}")
    print("\n[5] Parámetros de P2 por pliegue")
    pp = res["params_p2"]
    print(pp.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
    print("  rango: " + ", ".join(f"{c} [{pp[c].min():.3f}, {pp[c].max():.3f}]" for c in ("alpha", "beta", "gamma")))
    print("\n[6] Veredicto de la regla de empate (no decide el método vigente; ver entrenar.METODO_VIGENTE)")
    for k, v in res["seleccion"].items():
        print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
    sel = res["seleccion"]
    for m in (sel["mejor_linea_base"], sel["mejor_candidato"]):
        print(f"\n[7] Intervalo de {m} (percentiles de residuos log LOO)")
        for k, v in res["intervalos"][m].items():
            print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
    print("\n[8] Predicciones LOO por caso")
    pr = pd.DataFrame(res["preds"]).reindex(ev["id_caso"])
    pr.insert(0, "real", ev.set_index("id_caso")["plazo_dias"])
    print(pr.to_string(float_format=lambda v: f"{v:6.1f}"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    imprimir(evaluar())
    return 0


if __name__ == "__main__":
    sys.exit(main())
