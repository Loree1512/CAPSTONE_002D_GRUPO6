"""El JSON que carga el backend sale del artefacto vigente, sin cambios.

Si alguien reentrena o edita el JSON a mano, estas pruebas fallan hasta volver a
correr `python ml/src/exportar_backend.py --paridad`.
"""

import io
import json
import pickle

import pytest

import exportar_backend as eb

VERSION = "v1.0-2026-11-01"


def test_json_del_backend_es_el_exportado(tmp_path):
    generado = json.loads(eb.exportar(VERSION, tmp_path).read_text(encoding="utf-8"))
    en_backend = json.loads((eb.SALIDA / f"plazo_{VERSION}.json").read_text(encoding="utf-8"))
    assert generado == en_backend


def test_casos_de_paridad_vigentes():
    guardados = json.loads((eb.PARIDAD / f"paridad_plazo_{VERSION}.json").read_text(encoding="utf-8"))
    assert guardados == json.loads(json.dumps(eb.casos_paridad(VERSION)))


def test_no_abre_artefactos_con_clases(tmp_path):
    ruta = tmp_path / "con_clase.joblib"
    ruta.write_bytes(pickle.dumps({"estimador": io.BytesIO()}))
    with pytest.raises(pickle.UnpicklingError):
        eb.leer_artefacto(ruta)


def test_traduccion_dentro_del_vocabulario():
    art = eb.leer_artefacto(eb.DIR_MODELOS / f"plazo_{VERSION}.joblib")
    assert set(eb.TRADUCCION_TIPO_OBRA.values()) <= set(art["tipo_a_clase"])
    # obra_nueva no tiene casos reales: el backend lo marca como no representado.
    assert "obra_nueva" not in eb.dominio(art)["tipos_obra_representados"]
