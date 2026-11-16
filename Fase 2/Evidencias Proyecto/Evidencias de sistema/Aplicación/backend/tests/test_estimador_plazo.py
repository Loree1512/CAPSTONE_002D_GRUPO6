"""Plazo estimado (modelo de ML v1, provisional): estimador, persistencia, versión y UF.

La paridad se comprueba contra `tests/datos/paridad_plazo_v1.0-2026-11-01.json`, que
genera `ml/src/exportar_backend.py --paridad` con el `predict.py` original. Las UF
salen de la caché real de la CMF (`ml/data/processed/uf_cmf.csv`). Los modelos
"v9.9" de algunas pruebas son fixtures técnicos, no versiones entrenadas.

Ejecutar desde backend/:
    python -m pytest
"""

import csv
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.estimacion import CotizacionActualizar, EstimacionCrear  # noqa: E402
from app.services import estimador_plazo as ep  # noqa: E402
from app.services import servicio_estimaciones, servicio_proyectos  # noqa: E402
from app.services.snapshot_estimacion import armar_plazo  # noqa: E402
from scripts import actualizar_uf  # noqa: E402
from test_permisos_proyecto import _Base  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
VERSION = "v1.0-2026-11-01"
JSON_MODELO = RAIZ / "backend" / "app" / "modelos" / f"plazo_{VERSION}.json"
JOBLIB = RAIZ / "ml" / "models" / f"plazo_{VERSION}.joblib"
DATASET = RAIZ / "ml" / "data" / "processed" / "presupuestos_reales.csv"
CACHE_UF = RAIZ / "ml" / "data" / "processed" / "uf_cmf.csv"
PARIDAD = Path(__file__).resolve().parent / "datos" / f"paridad_plazo_{VERSION}.json"
M009 = (RAIZ / "supabase" / "migrations" / "009_plazo_estimaciones.sql").read_text(encoding="utf-8")
SEED_UF = (RAIZ / "supabase" / "seeds" / "005_valores_uf_cmf.sql").read_text(encoding="utf-8")

with CACHE_UF.open(encoding="utf-8") as _f:
    UF_CMF = {date.fromisoformat(r["fecha"]): Decimal(r["valor_uf"]) for r in csv.DictReader(_f)}

HOY = date(2026, 11, 3)  # UF CMF: 41.263,57


def uf_de(fecha):
    return UF_CMF.get(fecha)


def estimar(tipo, costo, completa=True, fecha=HOY, buscar=uf_de, version=None):
    return ep.estimar(tipo, costo, completa, fecha, buscar_uf=buscar, version=version)


class _SinClases(pickle.Unpickler):
    def find_class(self, modulo, nombre):
        raise pickle.UnpicklingError(f"{modulo}.{nombre}")


# --- Modelo exportado --------------------------------------------------------------

class ModeloExportado(unittest.TestCase):

    def setUp(self):
        self.json = json.loads(JSON_MODELO.read_text(encoding="utf-8"))
        with JOBLIB.open("rb") as f:
            self.artefacto = _SinClases(f).load()

    def test_parametros_identicos_al_artefacto(self):
        a, j = self.artefacto, self.json
        self.assertEqual(j["parametros"], a["parametros"])
        self.assertEqual(j["tipo_a_clase"], a["tipo_a_clase"])
        self.assertEqual(j["mediana_respaldo"], a["mediana_respaldo"])
        for clave in ("q_inf_log", "q_sup_log"):
            self.assertEqual(j["intervalo"][clave], a["intervalo"][clave])
        self.assertEqual((j["version"], j["metodo"], j["entrenado_en"]), (a["version"], a["metodo"], a["entrenado_en"]))
        self.assertEqual(j["origen"]["sha256"], hashlib.sha256(JOBLIB.read_bytes()).hexdigest())

    def test_dominio_sale_del_dataset_de_entrenamiento(self):
        with DATASET.open(encoding="utf-8") as f:
            filas = {r["id_caso"]: r for r in csv.DictReader(f)}
        usados = [filas[i] for i in self.artefacto["ids_entrenamiento"]]
        d = self.json["dominio"]
        self.assertEqual(d["costo_uf_min"], min(float(r["costo_neto_uf"]) for r in usados))
        self.assertEqual(d["costo_uf_max"], max(float(r["costo_neto_uf"]) for r in usados))
        self.assertEqual((d["plazo_dias_min"], d["plazo_dias_max"]), (2, 42))
        self.assertEqual(set(d["tipos_obra_representados"]), {r["tipo_obra"] for r in usados})
        # obra_nueva no tiene casos reales; ampliacion sí.
        self.assertNotIn("obra_nueva", d["tipos_obra_representados"])
        self.assertIn("ampliacion", d["tipos_obra_representados"])

    def test_declara_su_caracter_provisional(self):
        self.assertEqual((self.json["estado"], self.json["provisional"]), ("provisional", True))
        self.assertIn("provisional", self.json["observaciones"].lower())
        self.assertIn("extrapolación", self.json["observaciones"])
        self.assertIn("No se usaron datos sintéticos", self.json["observaciones"])

    def test_sin_dependencias_de_ml_en_el_backend(self):
        fuente = (RAIZ / "backend" / "app" / "services" / "estimador_plazo.py").read_text(encoding="utf-8")
        requisitos = (RAIZ / "backend" / "requirements.txt").read_text(encoding="utf-8").lower()
        for libreria in ("numpy", "pandas", "sklearn", "scikit", "joblib"):
            self.assertNotRegex(fuente, rf"^\s*(import|from) {libreria}", libreria)
            self.assertNotIn(libreria, requisitos)

    def test_carga_una_sola_vez(self):
        ep.cargar_modelo.cache_clear()
        with patch.object(ep.json, "loads", wraps=json.loads) as leer:
            primero = ep.cargar_modelo(VERSION)
            self.assertIs(ep.cargar_modelo(VERSION), primero)
        self.assertEqual(leer.call_count, 1)


class Paridad(unittest.TestCase):
    """Mismo resultado que ml/src/predict.py."""

    def test_casos_generados_con_predict(self):
        datos = json.loads(PARIDAD.read_text(encoding="utf-8"))
        self.assertEqual((datos["version"], datos["generado_con"]), (VERSION, "ml/src/predict.py"))
        modelo = ep.cargar_modelo(VERSION)
        self.assertGreater(len(datos["casos"]), 600)
        for caso in datos["casos"]:
            # Misma UF que usó predict.py (la de la caché de la CMF).
            self.assertEqual(Decimal(str(caso["uf"])), UF_CMF[date.fromisoformat(caso["fecha"])])
            obtenido = ep.predecir_p2(modelo, caso["tipo_obra_modelo"], caso["costo_neto_clp"] / caso["uf"])
            esperado = (caso["plazo_dias"], caso["intervalo_min_dias"], caso["intervalo_max_dias"])
            self.assertEqual(obtenido, esperado, caso)

    def test_ejemplos_documentados_del_modulo_ml(self):
        # ml/docs/notas_backend.md, sección 7.
        r = estimar("Ampliación", 17_640_000, fecha=date(2026, 5, 5))
        self.assertEqual((r.plazo_dias, r.plazo_min_dias, r.plazo_max_dias), (59, 27, 302))
        modelo = ep.cargar_modelo(VERSION)
        uf = float(UF_CMF[date(2025, 11, 16)])
        self.assertEqual(ep.predecir_p2(modelo, "terminaciones", 3_869_750 / uf), (12, 5, 61))

    def test_respaldo_igual_al_de_predict(self):
        self.assertEqual(ep.predecir_respaldo(ep.cargar_modelo(VERSION)), (14, 2, 35))


# --- Estados de dominio -----------------------------------------------------------

class Dominio(unittest.TestCase):

    def assert_plazo(self, r, esperado):
        self.assertEqual((r.plazo_dias, r.plazo_min_dias, r.plazo_max_dias), esperado)

    def test_ampliacion_dentro_del_rango(self):
        r = estimar("Ampliación", 12_000_000)
        self.assertEqual((r.estado, r.motivo, r.fuera_dominio), (ep.DENTRO_DOMINIO, None, False))
        self.assert_plazo(r, (41, 19, 209))
        self.assertEqual((r.metodo, r.provisional, r.version_modelo, r.tipo_obra_modelo),
                         ("P2", True, VERSION, "ampliacion"))
        self.assertEqual((r.uf_valor, r.uf_fecha), (Decimal("41263.57"), HOY))

    def test_costo_inferior_al_rango(self):
        r = estimar("Ampliación", 300_000)  # ≈ 7,3 UF
        self.assertEqual((r.estado, r.motivo, r.fuera_dominio), (ep.FUERA_RANGO_COSTO, ep.MOTIVO_COSTO_BAJO, True))
        self.assertIsNotNone(r.plazo_dias)

    def test_costo_superior_al_rango(self):
        r = estimar("Ampliación", 3000 * UF_CMF[HOY])
        self.assertEqual((r.estado, r.motivo), (ep.FUERA_RANGO_COSTO, ep.MOTIVO_COSTO_ALTO))
        self.assert_plazo(r, (324, 154, 1668))

    def test_bordes_del_rango_son_dominio(self):
        modelo = ep.cargar_modelo(VERSION)
        for uf_obra in (modelo.costo_uf_min, modelo.costo_uf_max):
            r = estimar("Ampliación", Decimal(str(uf_obra)) * UF_CMF[HOY])
            self.assertEqual(r.estado, ep.DENTRO_DOMINIO, uf_obra)

    def test_tipo_de_obra_no_representado(self):
        # Vivienda unifamiliar → obra_nueva: sin casos reales de entrenamiento.
        r = estimar("Vivienda unifamiliar", 60_000_000)
        self.assertEqual((r.estado, r.tipo_obra_modelo, r.motivo), (ep.TIPO_NO_REPRESENTADO, "obra_nueva",
                                                                    ep.MOTIVO_COSTO_ALTO))
        self.assert_plazo(r, (170, 81, 876))
        # Aun con costo dentro del rango sigue fuera del dominio.
        r = estimar("Edificación habitacional", 12_000_000)
        self.assertEqual((r.estado, r.motivo, r.fuera_dominio), (ep.TIPO_NO_REPRESENTADO, None, True))

    def test_estimacion_incompleta(self):
        r = estimar("Ampliación", 5_000_000, completa=False)
        self.assertEqual((r.estado, r.fuera_dominio, r.metodo), (ep.COSTO_INCOMPLETO, True, "P2"))
        self.assert_plazo(r, (19, 8, 96))
        # Lo incompleto domina aunque además esté fuera de rango.
        r = estimar("Vivienda unifamiliar", 60_000_000, completa=False)
        self.assertEqual((r.estado, r.motivo), (ep.COSTO_INCOMPLETO, ep.MOTIVO_TIPO_NO_REPRESENTADO))
        # Ampliación incompleta y cara: el motivo informa el costo fuera de rango.
        r = estimar("Ampliación", 40_000_000, completa=False)
        self.assertEqual((r.estado, r.motivo), (ep.COSTO_INCOMPLETO, ep.MOTIVO_COSTO_ALTO))
        # Dentro del rango: sin motivo.
        self.assertIsNone(estimar("Ampliación", 5_000_000, completa=False).motivo)

    def test_sin_uf_usa_el_respaldo(self):
        r = estimar("Ampliación", 12_000_000, fecha=date(2026, 11, 10))
        self.assertEqual((r.estado, r.motivo, r.metodo), (ep.RESPALDO, ep.MOTIVO_SIN_UF, ep.METODO_RESPALDO))
        self.assert_plazo(r, (14, 2, 35))
        self.assertEqual((r.uf_valor, r.uf_fecha, r.fuera_dominio), (None, None, True))

    def test_uf_que_falla_al_leerse_usa_el_respaldo(self):
        def cae(_fecha):
            raise ConnectionError("sin red")
        with self.assertLogs(ep.logger, level="WARNING"):
            r = estimar("Ampliación", 12_000_000, buscar=cae)
        self.assertEqual((r.estado, r.motivo), (ep.RESPALDO, ep.MOTIVO_SIN_UF))

    def test_costo_no_valido_usa_el_respaldo(self):
        for costo in (0, -1, None, "abc", float("nan")):
            r = estimar("Ampliación", costo)
            self.assertEqual((r.estado, r.motivo), (ep.RESPALDO, ep.MOTIVO_SIN_COSTO), costo)

    def test_tipo_sin_traduccion_no_disponible(self):
        r = estimar("Piscina", 12_000_000)
        self.assertEqual((r.estado, r.motivo, r.plazo_dias, r.version_modelo),
                         (ep.NO_DISPONIBLE, ep.MOTIVO_SIN_TRADUCCION, None, None))

    def test_invariantes_min_plazo_max(self):
        for tipo in ("Ampliación", "Vivienda unifamiliar"):
            for exponente in range(0, 13):
                for completa in (True, False):
                    r = estimar(tipo, 10 ** exponente, completa=completa)
                    self.assertTrue(all(isinstance(v, int) for v in (r.plazo_dias, r.plazo_min_dias, r.plazo_max_dias)))
                    self.assertTrue(1 <= r.plazo_min_dias <= r.plazo_dias <= r.plazo_max_dias, (tipo, exponente))

    def test_columnas_para_guardar(self):
        columnas = estimar("Ampliación", 12_000_000).a_columnas()
        self.assertEqual(set(columnas), {
            "plazo_dias", "plazo_min_dias", "plazo_max_dias", "plazo_metodo", "plazo_provisional", "plazo_estado",
            "plazo_motivo", "version_modelo", "tipo_obra_modelo", "uf_valor", "uf_fecha"})
        self.assertEqual((columnas["uf_valor"], columnas["uf_fecha"]), ("41263.57", "2026-11-03"))
        # Columna generada en la base: no se envía.
        self.assertNotIn("plazo_fuera_dominio", columnas)

    def test_fecha_de_chile(self):
        # 23:30 del 2 de noviembre en Santiago (UTC−3) ya es 3 de noviembre en UTC.
        self.assertEqual(ep.fecha_chile(datetime(2026, 11, 3, 2, 30, tzinfo=timezone.utc)), date(2026, 11, 2))


class FallosDelModelo(unittest.TestCase):

    def setUp(self):
        self.addCleanup(ep.cargar_modelo.cache_clear)

    def test_version_inexistente_no_disponible(self):
        with self.assertLogs(ep.logger, level="ERROR"):
            r = estimar("Ampliación", 12_000_000, version="v0.0-2000-01-01")
        self.assertEqual((r.estado, r.motivo), (ep.NO_DISPONIBLE, ep.MOTIVO_SIN_MODELO))

    def test_json_incompleto_es_invalido(self):
        datos = json.loads(JSON_MODELO.read_text(encoding="utf-8"))
        for clave in ("parametros", "dominio", "traduccion_tipo_obra"):
            roto = {k: v for k, v in datos.items() if k != clave}
            with self.assertRaises(ep.ModeloInvalido, msg=clave):
                ep.ModeloPlazo.desde_json(roto)
        with self.assertRaises(ep.ModeloInvalido):
            ep.ModeloPlazo.desde_json({**datos, "parametros": {**datos["parametros"], "beta": float("inf")}})

    def test_error_interno_no_disponible(self):
        with patch.object(ep, "predecir_p2", side_effect=ZeroDivisionError), \
                self.assertLogs(ep.logger, level="ERROR"):
            r = estimar("Ampliación", 12_000_000)
        self.assertEqual((r.estado, r.motivo), (ep.NO_DISPONIBLE, ep.MOTIVO_ERROR))


# --- Integración con las estimaciones --------------------------------------------

def _version_fixture(directorio: Path, version: str, beta: float) -> None:
    """Otra versión del modelo para probar el versionado. No es un modelo entrenado."""
    datos = json.loads(JSON_MODELO.read_text(encoding="utf-8"))
    datos.update(version=version, entrenado_en="2027-01-01",
                 parametros={**datos["parametros"], "beta": beta})
    (directorio / f"plazo_{version}.json").write_text(json.dumps(datos), encoding="utf-8")


class PlazoEnEstimaciones(_Base):

    def setUp(self):
        super().setUp()
        self.db["valores_uf"] = [{"fecha": HOY.isoformat(), "valor": "41263.57", "fuente": "cmf"}]
        self.db["versiones_modelo"] = [{"version": VERSION}]
        parche = patch.object(ep, "fecha_chile", return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(ep.cargar_modelo.cache_clear)

    def crear(self, usuario=None):
        return servicio_estimaciones.crear_estimacion(usuario or self.propietario, self.pid, EstimacionCrear())

    def fila(self, estimacion_id):
        return next(e for e in self.db["estimaciones"] if e["id"] == estimacion_id)

    def test_guarda_plazo_version_y_uf_con_la_estimacion(self):
        creada = self.crear()
        fila = self.fila(creada["id"])
        # El proyecto de prueba tiene una partida sin precio: costo parcial.
        self.assertFalse(fila["completa"])
        self.assertEqual((fila["plazo_estado"], fila["plazo_fuera_dominio"]), (ep.COSTO_INCOMPLETO, True))
        self.assertEqual((fila["version_modelo"], fila["tipo_obra_modelo"]), (VERSION, "ampliacion"))
        self.assertEqual((fila["uf_valor"], fila["uf_fecha"]), ("41263.57", "2026-11-03"))
        esperado = estimar("Ampliación", Decimal(fila["costo_total"]), completa=False)
        self.assertEqual((fila["plazo_dias"], fila["plazo_min_dias"], fila["plazo_max_dias"]),
                         (esperado.plazo_dias, esperado.plazo_min_dias, esperado.plazo_max_dias))
        # El costo no depende del plazo.
        self.assertEqual(float(creada["total"]), float(fila["costo_total"]))
        self.assertEqual(creada["plazo"]["dias"], esperado.plazo_dias)

    def test_respuesta_de_la_api_en_camel_case(self):
        creada = self.crear()
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.lector
        self.addCleanup(app.dependency_overrides.clear)
        cuerpo = TestClient(app).get(f"/proyectos/{self.pid}/estimaciones/{creada['id']}").json()
        plazo = cuerpo["plazo"]
        self.assertEqual(set(plazo), {"dias", "minDias", "maxDias", "metodo", "estado", "fueraDominio", "provisional",
                                      "motivo", "versionModelo", "tipoObraModelo", "ufValor", "ufFecha",
                                      "errorMedioDias", "estadoModelo"})
        # 010: el plazo para la cotización va aparte y nace sin definir.
        self.assertEqual(cuerpo["plazoProfesional"]["estado"], "sin_definir")
        self.assertIsNone(cuerpo["plazoProfesional"]["dias"])
        self.assertEqual((plazo["estado"], plazo["fueraDominio"], plazo["versionModelo"]),
                         ("costo_incompleto", True, VERSION))
        listado = TestClient(app).get(f"/proyectos/{self.pid}/estimaciones").json()
        self.assertEqual(listado[0]["plazo"]["dias"], plazo["dias"])

    def test_resumen_del_proyecto_trae_el_plazo(self):
        creada = self.crear()
        proyecto = servicio_proyectos.obtener_proyecto_por_id(self.propietario, self.pid)
        self.assertEqual(proyecto["plazo_dias"], creada["plazo"]["dias"])
        self.assertEqual((proyecto["plazo_estado"], proyecto["plazo_motivo"]),
                         (creada["plazo"]["estado"], creada["plazo"]["motivo"]))

    def test_listado_sin_estimacion_no_inventa_plazo(self):
        listado = servicio_proyectos.obtener_proyectos(self.propietario)
        fila = next(p for p in listado if str(p["id"]) == str(self.pid))
        self.assertEqual((fila["plazo_dias"], fila["plazo_estado"], fila["plazo_motivo"]), (None, None, None))

    def test_sin_uf_guarda_el_respaldo(self):
        self.db["valores_uf"] = []
        fila = self.fila(self.crear()["id"])
        self.assertEqual((fila["plazo_estado"], fila["plazo_metodo"], fila["plazo_dias"]),
                         (ep.RESPALDO, ep.METODO_RESPALDO, 14))
        self.assertIsNone(fila["uf_valor"])

    def test_fallo_del_estimador_no_pierde_el_costo(self):
        with patch.object(ep, "cargar_modelo", side_effect=OSError("archivo ausente")), \
                self.assertLogs(ep.logger, level="ERROR"):
            creada = self.crear()
        fila = self.fila(creada["id"])
        self.assertGreater(float(fila["costo_total"]), 0)
        self.assertEqual((fila["plazo_estado"], fila["plazo_motivo"], fila["plazo_dias"]),
                         (ep.NO_DISPONIBLE, ep.MOTIVO_SIN_MODELO, None))
        self.assertIsNone(creada["plazo"]["dias"])

    def test_version_no_registrada_guarda_el_costo_sin_plazo(self):
        self.db["versiones_modelo"] = []
        with self.assertLogs(servicio_estimaciones.logger, level="ERROR"):
            creada = self.crear()
        fila = self.fila(creada["id"])
        self.assertEqual((fila["plazo_estado"], fila["plazo_motivo"], fila["version_modelo"]),
                         (ep.NO_DISPONIBLE, servicio_estimaciones.VERSION_NO_REGISTRADA, None))
        self.assertEqual(len(self.db["estimaciones"]), 1)

    def test_actualizar_cotizacion_copia_el_plazo_sin_ejecutar_el_modelo(self):
        original = self.fila(self.crear()["id"])
        with patch.object(ep, "estimar", side_effect=AssertionError("no debe recalcular")), \
                patch.object(ep, "cargar_modelo", side_effect=AssertionError("no debe cargar")):
            copia = servicio_estimaciones.actualizar_cotizacion(
                self.editor, self.pid, original["id"], CotizacionActualizar(observaciones="Nueva nota"))
        nueva = self.fila(copia["id"])
        for columna in ("plazo_dias", "plazo_min_dias", "plazo_max_dias", "plazo_metodo", "plazo_provisional",
                        "plazo_estado", "plazo_motivo", "version_modelo", "tipo_obra_modelo", "uf_valor", "uf_fecha"):
            self.assertEqual(nueva[columna], original[columna], columna)
        self.assertEqual(nueva["observaciones"], "Nueva nota")

    def test_una_version_nueva_no_cambia_las_estimaciones_anteriores(self):
        antigua = self.crear()
        antes = dict(self.fila(antigua["id"]))

        directorio = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directorio)
        shutil.copy(JSON_MODELO, directorio / JSON_MODELO.name)
        _version_fixture(directorio, "v9.9-2027-01-01", beta=1.2)
        self.db["versiones_modelo"].append({"version": "v9.9-2027-01-01"})
        ep.cargar_modelo.cache_clear()
        with patch.object(ep, "DIR_MODELOS", directorio), \
                patch.dict(os.environ, {ep.VARIABLE_VERSION: "v9.9-2027-01-01"}):
            nueva = self.crear()

        self.assertEqual(self.fila(nueva["id"])["version_modelo"], "v9.9-2027-01-01")
        self.assertNotEqual(self.fila(nueva["id"])["plazo_dias"], antes["plazo_dias"])
        # La anterior conserva su versión y sus días, también al releerla.
        self.assertEqual(self.fila(antigua["id"]), antes)
        releida = servicio_estimaciones.obtener_estimacion(self.propietario, self.pid, antigua["id"])
        self.assertEqual((releida["plazo"]["dias"], releida["plazo"]["version_modelo"]), (antes["plazo_dias"], VERSION))

    def test_estimacion_anterior_a_la_migracion(self):
        # Fila sin columnas de plazo: se informa como no disponible, sin inventar días.
        self.assertEqual(armar_plazo({"id": "x"}), {"estado": "no_disponible", "fuera_dominio": True,
                                                    "motivo": "anterior_al_modelo"})


# --- Migración 009 y seed de UF -------------------------------------------------------

class Migracion009(unittest.TestCase):

    def test_version_registrada_es_el_mismo_json_del_backend(self):
        literal = re.search(r"\$modelo\$\n(.*?)\n\$modelo\$", M009, flags=re.S).group(1)
        self.assertEqual(json.loads(literal), json.loads(JSON_MODELO.read_text(encoding="utf-8")))

    def test_columnas_y_restricciones_del_plazo(self):
        for columna in ("plazo_dias integer", "plazo_min_dias integer", "plazo_max_dias integer", "plazo_metodo text",
                        "plazo_provisional boolean", "plazo_estado text not null default 'no_disponible'",
                        "plazo_motivo text", "version_modelo text", "tipo_obra_modelo text",
                        "uf_valor numeric(12, 2)", "uf_fecha date"):
            self.assertIn(f"add column {columna}", M009)
        self.assertIn("generated always as (plazo_estado <> 'dentro_dominio') stored", M009)
        self.assertIn("1 <= plazo_min_dias and plazo_min_dias <= plazo_dias and plazo_dias <= plazo_max_dias", M009)
        self.assertIn("references public.versiones_modelo(version) on delete restrict", M009)
        for estado in ep.ESTADOS:
            self.assertIn(f"'{estado}'", M009)

    def test_plazo_y_version_inmutables(self):
        self.assertIn("create trigger estimaciones_plazo_inmutable", M009)
        self.assertIn("create trigger versiones_modelo_inmutables", M009)
        self.assertIn("create unique index versiones_modelo_vigente_idx", M009)
        self.assertIn("where vigente;", M009)

    def test_rpc_guardan_y_copian_el_plazo(self):
        columnas = ("plazo_dias", "plazo_min_dias", "plazo_max_dias", "plazo_metodo", "plazo_provisional",
                    "plazo_estado", "plazo_motivo", "version_modelo", "tipo_obra_modelo", "uf_valor", "uf_fecha")
        crear = M009.split("create or replace function public.crear_estimacion(")[1].split("$$;")[0]
        copiar = M009.split("create or replace function public.actualizar_cotizacion(")[1].split("$$;")[0]
        for columna in columnas:
            self.assertIn(f"r.{columna}", crear)
            self.assertIn(f"v_origen.{columna}", copiar)
        self.assertNotIn("plazo_fuera_dominio", crear + copiar)

    def test_permisos(self):
        self.assertNotRegex(M009, r"grant [^;]*\bto [^;]*\b(anon|public)\b")
        self.assertIn("grant select, insert, update on public.valores_uf to service_role;", M009)
        self.assertIn("grant select on public.valores_uf to authenticated;", M009)
        self.assertRegex(M009, r"revoke execute on function public\.crear_estimacion\([^)]*\) from public, anon, authenticated;")

    def test_seed_de_uf_es_copia_exacta_de_la_cmf(self):
        filas = re.findall(r"\('(\d{4}-\d{2}-\d{2})', ([\d.]+), '([^']+)', '(\d{4}-\d{2}-\d{2})'\)", SEED_UF)
        self.assertEqual({date.fromisoformat(f): Decimal(v) for f, v, _, _ in filas}, UF_CMF)
        self.assertEqual({fuente for _, _, fuente, _ in filas},
                         {"https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/2025/01"})
        self.assertIn("on conflict (fecha) do nothing;", SEED_UF)


# --- Script de actualización de UF -----------------------------------------------------

CLAVE = "clave-secreta-cmf"


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _TablaUF:
    def __init__(self, ultimo=None):
        self.ultimo, self.guardado, self.opciones = ultimo, None, None

    def table(self, _nombre):
        return self

    def select(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def upsert(self, filas, **opciones):
        self.guardado, self.opciones = filas, opciones
        return self

    def execute(self):
        datos = [{"fecha": self.ultimo.isoformat()}] if self.ultimo and self.guardado is None else []
        return type("R", (), {"data": datos})()


class ActualizarUF(unittest.TestCase):

    CUERPO = json.dumps({"UFs": [{"Valor": "41.295,46", "Fecha": "2026-11-09"},
                                 {"Valor": "41.299,01", "Fecha": "2026-11-10"}]}).encode()

    def test_parsea_el_formato_de_la_cmf(self):
        self.assertEqual(actualizar_uf.parsear(self.CUERPO),
                         {date(2026, 11, 9): Decimal("41295.46"), date(2026, 11, 10): Decimal("41299.01")})
        for malo in (b"no json", b'{"UFs": []}', b'{"otro": 1}', b'{"UFs": [{"Valor": "-1", "Fecha": "2026-01-01"}]}'):
            with self.assertRaises(actualizar_uf.ErrorUF):
                actualizar_uf.parsear(malo)

    def test_pide_desde_el_mes_anterior_y_no_pisa_lo_guardado(self):
        pedidas = []

        def abrir(url, timeout):
            pedidas.append(url)
            return _Respuesta(self.CUERPO)

        tabla = _TablaUF(ultimo=date(2026, 11, 9))
        self.assertEqual(actualizar_uf.actualizar(tabla, CLAVE, abrir=abrir), 2)
        self.assertIn("/uf/posteriores/2026/10?", pedidas[0])
        self.assertEqual(tabla.opciones, {"on_conflict": "fecha", "ignore_duplicates": True})
        self.assertEqual([f["fecha"] for f in tabla.guardado], ["2026-11-09", "2026-11-10"])
        # La fuente guardada no incluye la clave.
        self.assertNotIn(CLAVE, json.dumps(tabla.guardado))
        self.assertEqual(actualizar_uf.mes_anterior(date(2026, 1, 15)), (2025, 12))

    def test_los_errores_no_revelan_la_clave(self):
        def falla_http(url, timeout):
            raise urllib.error.HTTPError(url, 401, "no", {}, None)

        def sin_red(url, timeout):
            raise urllib.error.URLError(f"fallo al abrir {url}")

        for abrir in (falla_http, sin_red):
            with self.assertRaises(actualizar_uf.ErrorUF) as error:
                actualizar_uf.actualizar(_TablaUF(), CLAVE, desde=(2026, 10), abrir=abrir)
            self.assertNotIn(CLAVE, str(error.exception))
            self.assertNotIn("apikey", str(error.exception))

    def test_sin_clave_no_hace_nada(self):
        with patch.dict(os.environ, {actualizar_uf.VARIABLE_CLAVE: ""}), \
                self.assertLogs(actualizar_uf.logger, level="ERROR"):
            self.assertEqual(actualizar_uf.main([]), 2)


if __name__ == "__main__":
    unittest.main()
