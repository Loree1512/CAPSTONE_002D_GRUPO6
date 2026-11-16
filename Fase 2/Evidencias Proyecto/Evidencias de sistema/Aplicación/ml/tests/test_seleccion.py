"""Pruebas de la regla de empate corregida y de cómo queda registrada en el artefacto."""

import json

import joblib
import numpy as np
import pandas as pd
import pytest

import entrenar
import predict
from evaluacion import comparar_pareado, seleccionar

# Predicciones LOO del análisis de sensibilidad (model card, "Sensibilidad"), 3 decimales.
IDS = ["R02", "R03", "R04", "R05", "R06", "R09", "R10", "R11", "R13", "R14", "R16", "R17"]
REAL = [5, 14, 5, 14, 2, 5, 14, 42, 14, 5, 14, 21]
P2 = [6.208, 11.443, 7.969, 1.816, 4.323, 9.797, 6.978, 61.756, 21.211, 5.289, 9.514, 18.631]
RIDGE = [7.616, 10.542, 8.504, 2.273, 6.592, 10.107, 8.000, 33.939, 14.204, 7.101, 9.561, 20.331]


@pytest.fixture
def datos():
    ev = pd.DataFrame({"id_caso": IDS, "plazo_dias": np.array(REAL, dtype=float)})
    preds = {
        "mediana": {i: 14.0 for i in IDS},
        "P2": dict(zip(IDS, P2)),
        "ridge": dict(zip(IDS, RIDGE)),
    }
    return ev, preds


def test_seleccionar_regla_corregida(datos):
    ev, preds = datos
    s = seleccionar(ev, preds)
    assert s["mejor_linea_base"] == "P2"
    assert s["mejor_candidato"] == "ridge"
    assert s["dif_mae"] == pytest.approx(1.225, abs=0.002)
    assert s["se_dif"] == pytest.approx(1.180, abs=0.002)
    assert s["de_dif_ddof1"] == pytest.approx(4.086, abs=0.002)
    assert s["cociente_dif_se"] == pytest.approx(1.038, abs=0.003)
    assert s["veredicto"] == "candidato_supera"
    assert (s["ganados_candidato"], s["ganados_linea_base"], s["empates"]) == (6, 6, 0)
    assert s["wilcoxon_metodo"] == "exact"
    assert s["wilcoxon_estadistico"] == pytest.approx(37.0)
    assert s["wilcoxon_p"] == pytest.approx(0.91, abs=0.005)
    assert "elegido" not in s  # la regla ya no decide el método vigente


def test_empate_si_diferencia_menor_que_se(datos):
    ev, preds = datos
    # Ridge igual a P2 salvo en R13: una sola diferencia, menor o igual que su SE.
    preds["ridge"] = dict(preds["P2"])
    preds["ridge"]["R13"] = 20.0
    s = seleccionar(ev, preds)
    assert 0 < s["dif_mae"] <= s["se_dif"]
    assert s["veredicto"] == "empate_tecnico"


def test_ningun_candidato_mejora(datos):
    ev, preds = datos
    preds["ridge"] = {i: v + 3 for i, v in preds["P2"].items()}
    assert seleccionar(ev, preds)["veredicto"] == "ningun_candidato_mejora"


def test_comparar_pareado_con_ceros_usa_aproximacion():
    y = np.array([5.0, 6, 7, 8, 9])
    c = comparar_pareado(y, y + 1, y + np.array([1, 2, 0.5, 3, 0.2]))
    assert c["empates"] == 1 and c["wilcoxon_metodo"] == "approx"


def test_artefacto_separa_veredicto_y_decision():
    ruta = predict.ARTEFACTO_POR_DEFECTO
    if not ruta.exists():
        pytest.skip("artefacto no generado")
    art = joblib.load(ruta)
    sel = art["seleccion"]
    assert set(sel) == {"veredicto_regla", "decision"}
    assert sel["veredicto_regla"]["veredicto"] in {"candidato_supera", "empate_tecnico", "ningun_candidato_mejora"}
    assert "se_dif" in sel["veredicto_regla"] and "wilcoxon_p" in sel["veredicto_regla"]
    assert sel["decision"]["metodo"] == entrenar.METODO_VIGENTE == art["metodo"]
    assert sel["decision"]["motivo"]

    js = json.loads(ruta.with_suffix(".json").read_text(encoding="utf-8"))
    dsel = js["detalle"]["seleccion"]
    assert set(dsel) == {"veredicto_regla", "decision"}
    assert dsel["decision"]["metodo"] == entrenar.METODO_VIGENTE
    assert dsel["veredicto_regla"]["veredicto"] == sel["veredicto_regla"]["veredicto"]
