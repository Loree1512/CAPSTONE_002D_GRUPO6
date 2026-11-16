"""Pruebas del contrato de predecir_plazo. Sin red: la UF y el artefacto se
sustituyen por fixtures (una prueba lee el artefacto real desde disco)."""

import math
from datetime import date

import pytest

import predict

UF_FIJA = 40000.0
CLAVES = {"plazo_dias", "intervalo_min_dias", "intervalo_max_dias",
          "version_modelo", "metodo", "validado", "provisional"}


@pytest.fixture
def artefacto_falso():
    return {
        "version": "v0.0-test",
        "algoritmo": "parametrica",
        "metodo": "P2",
        "parametros": {"alpha": -1.6, "beta": 0.9, "gamma": 0.27},
        "estimador": None,
        "tipo_a_clase": {"ampliacion": "edificacion", "obra_nueva": "edificacion",
                         "terminaciones": "puntual", "obra_menor_varia": "puntual"},
        "intervalo": {"q_inf_log": -0.74, "q_sup_log": 1.64},
        "mediana_respaldo": {"plazo_dias": 14.0, "q_inf_log": -1.0, "q_sup_log": 0.5},
        "validado": True,
        "provisional": True,
    }


def _uf_falsa(fecha):
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)
    if fecha < date(2025, 2, 1) or fecha > date(2026, 11, 9):
        raise ValueError("fuera de la serie")
    return UF_FIJA


@pytest.fixture
def entorno(monkeypatch, artefacto_falso):
    monkeypatch.setattr(predict, "_artefacto", lambda: artefacto_falso)
    monkeypatch.setattr(predict, "uf_del_dia", _uf_falsa)
    return artefacto_falso


def _orden_ok(r):
    return 1 <= r["intervalo_min_dias"] <= r["plazo_dias"] <= r["intervalo_max_dias"]


def test_contrato_y_valor_p2(entorno):
    r = predict.predecir_plazo("terminaciones", 4_000_000, "2026-03-01")
    assert set(r) == CLAVES
    assert all(isinstance(r[k], int) for k in ("plazo_dias", "intervalo_min_dias", "intervalo_max_dias"))
    esperado = round(math.exp(-1.6 + 0.9 * math.log(4_000_000 / UF_FIJA)))
    assert r["plazo_dias"] == esperado
    assert r["metodo"] == "P2" and r["validado"] is True and r["provisional"] is True
    assert r["version_modelo"] == "v0.0-test"
    assert _orden_ok(r)


def test_edificacion_alarga_plazo(entorno):
    p = predict.predecir_plazo("terminaciones", 8_000_000, date(2026, 5, 5))["plazo_dias"]
    e = predict.predecir_plazo("ampliacion", 8_000_000, date(2026, 5, 5))["plazo_dias"]
    assert e > p


def test_tipo_obra_invalido(entorno):
    with pytest.raises(ValueError):
        predict.predecir_plazo("piscina", 1_000_000, "2026-03-01")


@pytest.mark.parametrize("costo", [None, 0, -5, float("nan"), "1000", True])
def test_costo_invalido_usa_mediana_y_no_validado(entorno, costo):
    r = predict.predecir_plazo("terminaciones", costo, "2026-03-01")
    assert r["metodo"] == "mediana_respaldo"
    assert r["validado"] is False
    assert r["plazo_dias"] == 14
    assert _orden_ok(r)


@pytest.mark.parametrize("fecha", [None, "2024-12-31", "2030-01-01", "no-es-fecha"])
def test_fecha_sin_uf_usa_mediana_y_no_validado(entorno, fecha):
    r = predict.predecir_plazo("ampliacion", 5_000_000, fecha)
    assert r["metodo"] == "mediana_respaldo"
    assert r["validado"] is False
    assert _orden_ok(r)


def test_cmf_caida_usa_respaldo(entorno, monkeypatch):
    def cae(_):
        raise SystemExit("ERROR: no se pudo conectar a la CMF")
    monkeypatch.setattr(predict, "uf_del_dia", cae)
    r = predict.predecir_plazo("terminaciones", 2_000_000, "2026-03-01")
    assert r["metodo"] == "mediana_respaldo" and r["validado"] is False


def test_respaldo_no_validado_aunque_artefacto_validado(entorno):
    assert entorno["validado"] is True
    r = predict.predecir_plazo("terminaciones", None, None)
    assert r["validado"] is False


@pytest.mark.parametrize("costo", [1, 100, 10_000, 1_000_000, 10**9])
def test_orden_intervalo_en_extremos(entorno, costo):
    r = predict.predecir_plazo("obra_menor_varia", costo, "2026-03-01")
    assert _orden_ok(r)


def test_orden_con_cuantiles_del_mismo_signo(entorno):
    entorno["intervalo"] = {"q_inf_log": 0.3, "q_sup_log": 0.9}
    r = predict.predecir_plazo("terminaciones", 4_000_000, "2026-03-01")
    assert _orden_ok(r)


def test_artefacto_real_cumple_contrato(monkeypatch):
    if not predict.ARTEFACTO_POR_DEFECTO.exists():
        pytest.skip("artefacto no generado")
    monkeypatch.setattr(predict, "uf_del_dia", _uf_falsa)
    monkeypatch.delenv(predict.VARIABLE_RUTA, raising=False)
    r = predict.predecir_plazo("ampliacion", 17_640_000, "2026-05-05")
    assert set(r) == CLAVES
    assert r["version_modelo"] == "v1.0-2026-11-01"
    assert _orden_ok(r)
    assert predict.predecir_plazo("ampliacion", None, None)["validado"] is False
