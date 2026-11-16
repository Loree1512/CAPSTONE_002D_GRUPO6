"""Entrena la versión final del modelo de plazo y escribe el artefacto (HU-14/HU-17).

1. Corre el LOO de `evaluacion.py` y calcula el veredicto de la regla de empate
   corregida (`evaluacion.seleccionar`). El veredicto se informa y se guarda,
   pero no decide el método.
2. Ajusta METODO_VIGENTE con los 13 casos de entrenamiento final
   (12 de evaluación + R08 con 35 días). Sin sintéticos, salvo que el método
   vigente sea una variante '+sint'.
3. Escribe `plazo_<version>.joblib` (diccionario con parámetros, residuos del
   intervalo y respaldo) y `plazo_<version>.json` con los campos de
   `versiones_modelo`. Las métricas son las del LOO, no las del ajuste final.
   En ambos, `seleccion` guarda por separado el veredicto de la regla y la
   decisión final con su motivo.

La versión lleva la fecha de entrenamiento: v1.0-AAAA-MM-DD.

Uso:
    ml/.venv/Scripts/python ml/src/entrenar.py [--salida DIR] [--entrenado-en AAAA-MM-DD]

    --salida        directorio de salida (por defecto ml/models). `ruta_artefacto`
                    del JSON siempre apunta a ml/models/, que es donde lo carga el
                    backend.
    --entrenado-en  fecha de entrenamiento (por defecto, hoy). Se usa para
                    regenerar metadatos de una versión existente sin cambiar su
                    nombre ni su fecha.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import sklearn

from evaluacion import ID_COTA, TIPO_A_CLASE, _entrenar, _fabricas, evaluar, imprimir, residuos_log
from generar_sinteticos import N_SINTETICOS, SEMILLA_BASE
from uf import ENDPOINT

RAIZ_ML = Path(__file__).resolve().parents[1]
DIR_MODELOS = RAIZ_ML / "models"
VERSION_MAYOR = "v1.0"

# Método vigente, decidido por la usuaria el 2026-11-01. La justificación está en
# ml/docs/model_card_v1.0-2026-11-01.md, sección "Selección". Con la regla
# corregida Ridge supera el umbral por 0,045 días, pero ambos métodos son
# estadísticamente indistinguibles y la ventaja de Ridge depende de R08.
METODO_VIGENTE = "P2"
DECISION = {
    "metodo": METODO_VIGENTE,
    "motivo": ("Se mantiene P2: P2 y Ridge son estadísticamente indistinguibles (6 casos "
               "ganados cada uno, Wilcoxon pareado exacto p = 0,91) y la ventaja de Ridge "
               "depende de incluir R08, cuyo plazo es una cota imprecisa (sin R08 en el "
               "entrenamiento, P2 4,93 frente a Ridge 5,27 días)."),
    "alternativa": "ridge",
    "nota_alternativa": "Ridge queda como alternativa a reevaluar con más datos o cuando RAM confirme el plazo de R08.",
    "fecha_decision": "2026-11-01",
    "referencia": "ml/docs/model_card_v1.0-2026-11-01.md#selección",
}


def _redondear(d: dict, nd: int = 3) -> dict:
    return {k: (round(v, 4 if k == "wilcoxon_p" else nd) if isinstance(v, float) else v) for k, v in d.items()}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", type=Path, default=DIR_MODELOS)
    ap.add_argument("--entrenado-en", type=date.fromisoformat, default=date.today())
    args = ap.parse_args(argv)

    if METODO_VIGENTE not in _fabricas():
        raise SystemExit(f"ERROR: METODO_VIGENTE '{METODO_VIGENTE}' no es un método evaluado.")

    fecha = args.entrenado_en
    version = f"{VERSION_MAYOR}-{fecha.isoformat()}"
    res = evaluar()
    imprimir(res)

    sel = res["seleccion"]
    elegido = METODO_VIGENTE
    entrenamiento, evaluacion = res["entrenamiento"], res["evaluacion"]
    final = _entrenar(elegido, entrenamiento, desplazamiento=len(evaluacion) + 1)
    es_param = elegido == "P2"
    met = res["tabla"].loc[elegido]
    usa_sint = elegido.endswith("+sint")
    seleccion = {"veredicto_regla": sel, "decision": DECISION}

    mediana_final = float(np.median(entrenamiento["plazo_dias"]))
    artefacto = {
        "version": version,
        "algoritmo": "parametrica" if es_param else elegido.replace("+sint", ""),
        "metodo": elegido,
        "parametros": final.parametros() if es_param else None,
        "estimador": None if es_param else final.estimador,
        "variables": ["log_uf", "edif"],
        "tipo_a_clase": TIPO_A_CLASE,
        "intervalo": res["intervalos"][elegido],
        "residuos_log_loo": residuos_log(evaluacion, res["preds"][elegido]).tolist(),
        "mediana_respaldo": {"plazo_dias": mediana_final, **{
            k: res["intervalos"]["mediana"][k] for k in ("q_inf_log", "q_sup_log", "percentiles", "metodo_percentil")}},
        "validado": True,
        "provisional": es_param,
        "filas_entrenamiento": int(len(entrenamiento)),
        "ids_entrenamiento": entrenamiento["id_caso"].tolist(),
        "metricas_loo": {k: float(met[k]) for k in ("mae", "rmse", "sd_ae", "ae_min", "ae_max", "r2")},
        "seleccion": seleccion,
        "entrenado_en": fecha.isoformat(),
        "fuente_uf": ENDPOINT,
        "sklearn": sklearn.__version__,
    }

    args.salida.mkdir(parents=True, exist_ok=True)
    ruta_joblib = args.salida / f"plazo_{version}.joblib"
    joblib.dump(artefacto, ruta_joblib)

    fila = {
        "version": version,
        "algoritmo": artefacto["algoritmo"],
        "filas_entrenamiento": artefacto["filas_entrenamiento"],
        "mae_dias": round(float(met["mae"]), 2),
        "rmse_dias": round(float(met["rmse"]), 2),
        "r2": round(float(met["r2"]), 2),
        "validado": True,
        "ruta_artefacto": f"ml/models/{ruta_joblib.name}",
        "vigente": True,
        "entrenado_en": fecha.isoformat(),
        "provisional": es_param,
        "filas_reales": int(len(entrenamiento)),
        "filas_sinteticas": N_SINTETICOS if usa_sint else 0,
        "detalle": {
            "evaluacion": f"leave-one-out sobre {len(evaluacion)} casos reales "
                          f"(14 utilizables − {ID_COTA} − R07); métricas en días",
            "sd_error_abs_dias": round(float(met["sd_ae"]), 2),
            "rango_error_abs_dias": [round(float(met["ae_min"]), 2), round(float(met["ae_max"]), 2)],
            "seleccion": {"veredicto_regla": _redondear(sel), "decision": DECISION},
            "parametros": {k: round(v, 4) for k, v in final.parametros().items()} if es_param else None,
            "intervalo": _redondear(artefacto["intervalo"]),
            "mediana_respaldo_dias": mediana_final,
            "semilla_sinteticos": SEMILLA_BASE,
        },
    }
    ruta_json = args.salida / f"plazo_{version}.json"
    ruta_json.write_text(json.dumps(fila, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n[9] Artefacto final")
    print(f"  método vigente: {METODO_VIGENTE} (veredicto de la regla: {sel['veredicto']})")
    print(f"  {ruta_joblib}  ({ruta_joblib.stat().st_size} bytes)")
    print(f"  {ruta_json}")
    if es_param:
        print("  parámetros finales (13 casos): " + ", ".join(f"{k} = {v:.4f}" for k, v in final.parametros().items()))
    print(f"  mediana de respaldo: {mediana_final:.1f} días")
    return 0


if __name__ == "__main__":
    sys.exit(main())
