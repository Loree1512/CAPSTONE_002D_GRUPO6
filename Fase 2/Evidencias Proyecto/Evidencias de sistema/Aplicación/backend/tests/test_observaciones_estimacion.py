"""Observaciones de la cotización: snapshot por estimación, permisos y persistencia histórica.

Ejecutar desde backend/:
    python -m pytest
"""

import os
import re
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.estimacion import CotizacionActualizar, EstimacionCrear, OBSERVACIONES_MAX  # noqa: E402
from app.schemas.partida_proyecto import PartidaProyectoEditar  # noqa: E402
from app.services import servicio_estimaciones, servicio_partidas_proyecto, servicio_proyectos  # noqa: E402
from test_permisos_proyecto import _Base  # noqa: E402

M006 = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
        / "006_observaciones_estimacion.sql").read_text(encoding="utf-8")

TEXTO = "Valor preliminar sujeto a revisión de\nespecialidades y confirmación de terreno."


class Observaciones(_Base):

    def crear(self, usuario=None, observaciones=None):
        datos = EstimacionCrear(observaciones=observaciones)
        return servicio_estimaciones.crear_estimacion(usuario or self.propietario, self.pid, datos)

    def actualizar(self, estimacion_id, observaciones, usuario=None):
        return servicio_estimaciones.actualizar_cotizacion(
            usuario or self.editor, self.pid, estimacion_id, CotizacionActualizar(observaciones=observaciones))

    def estado(self):
        return servicio_proyectos.obtener_proyecto_por_id(self.propietario, self.pid)["estado_estimacion"]

    # --- Opcional -------------------------------------------------------------------------

    def test_sin_observacion(self):
        self.assertIsNone(self.crear()["observaciones"])
        # Sin cuerpo, igual que antes.
        self.assertIsNone(servicio_estimaciones.crear_estimacion(self.propietario, self.pid, None)["observaciones"])

    def test_con_observacion_queda_guardada_y_se_relee(self):
        creada = self.crear(observaciones=f"  {TEXTO}  ")
        self.assertEqual(creada["observaciones"], TEXTO)
        self.assertEqual(servicio_estimaciones.obtener_estimacion(self.lector, self.pid, creada["id"])["observaciones"],
                         TEXTO)

    def test_en_blanco_queda_vacia(self):
        self.assertIsNone(self.crear(observaciones=" \n \r\n ")["observaciones"])

    def test_html_se_guarda_como_texto(self):
        html = '<img src=x onerror="alert(1)"> & <b>negrita</b>'
        self.assertEqual(self.crear(observaciones=html)["observaciones"], html)

    def test_longitud_maxima(self):
        self.assertEqual(len(EstimacionCrear(observaciones="x" * OBSERVACIONES_MAX).observaciones), 1000)
        for modelo in (EstimacionCrear, CotizacionActualizar):
            with self.assertRaises(ValidationError) as error:
                modelo(observaciones="x" * (OBSERVACIONES_MAX + 1))
            self.assertIn("1000 caracteres", str(error.exception))

    def test_api_responde_422_con_mensaje(self):
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.propietario
        self.addCleanup(app.dependency_overrides.clear)
        respuesta = TestClient(app).post(f"/proyectos/{self.pid}/estimaciones", json={"observaciones": "x" * 1001})
        self.assertEqual(respuesta.status_code, 422)
        self.assertIn("1000 caracteres", respuesta.json()["detail"][0]["msg"])

    # --- Permisos ---------------------------------------------------------------------------

    def test_propietario_y_editor_la_definen(self):
        self.assertEqual(self.crear(self.propietario, "Del propietario")["observaciones"], "Del propietario")
        ultima = self.crear(self.editor, "Del editor")
        self.assertEqual(ultima["observaciones"], "Del editor")
        self.assertEqual(self.actualizar(ultima["id"], "Editada", self.propietario)["observaciones"], "Editada")

    def test_lector_solo_visualiza(self):
        creada = self.crear(observaciones=TEXTO)
        self.assertEqual(servicio_estimaciones.obtener_estimacion(self.lector, self.pid, creada["id"])["observaciones"],
                         TEXTO)
        antes = len(self.db["estimaciones"])
        self.assert_estado({
            "generar con observación": lambda: self.crear(self.lector, "Del lector"),
            "actualizar cotización": lambda: self.actualizar(creada["id"], "Del lector", self.lector),
        }, 403)
        self.assert_estado({
            "ajeno actualiza": lambda: self.actualizar(creada["id"], "Ajeno", self.ajeno),
        }, 404)
        self.assertEqual(len(self.db["estimaciones"]), antes)

    def test_estimacion_de_otro_proyecto_404(self):
        otro = servicio_proyectos.crear_proyecto(self.propietario, self._datos_otro())
        servicio_partidas_proyecto.editar(self.propietario, otro["id"], self.partidas(otro["id"])[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 5}))
        ajena = servicio_estimaciones.crear_estimacion(self.propietario, otro["id"], None)
        with self.assertRaises(HTTPException) as error:
            self.actualizar(ajena["id"], "Cruzada", self.propietario)
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            self.actualizar(uuid4(), "No existe", self.propietario)
        self.assertEqual(error.exception.status_code, 404)

    # --- Persistencia histórica ---------------------------------------------------------------

    def test_historica_conserva_su_observacion(self):
        original = self.crear(observaciones="Primera")
        nueva = self.actualizar(original["id"], "Segunda")

        self.assertNotEqual(nueva["id"], original["id"])
        self.assertEqual(nueva["observaciones"], "Segunda")
        releida = servicio_estimaciones.obtener_estimacion(self.propietario, self.pid, original["id"])
        self.assertEqual(releida["observaciones"], "Primera")
        self.assertEqual(releida, original)

        # Mismos montos, partidas y versión: no pasa por el motor.
        sin_id = lambda e: {k: v for k, v in e.items() if k not in ("id", "fecha_creacion", "observaciones")}
        self.assertEqual(sin_id(nueva), sin_id(original))

        ultima = servicio_estimaciones.listar_estimaciones(self.propietario, self.pid)[0]
        self.assertEqual(ultima["id"], nueva["id"])

    def test_actualizar_cotizacion_no_cambia_el_estado(self):
        original = self.crear(observaciones="Primera")
        self.assertEqual(self.estado(), "vigente")
        self.actualizar(original["id"], "Segunda")
        self.assertEqual(self.estado(), "vigente")

        # Si ya estaba por recalcular, sigue igual: la observación no cambia el costo.
        servicio_partidas_proyecto.editar(self.propietario, self.pid, self.partidas()[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 99}))
        self.assertEqual(self.estado(), "recalcular")
        ultima = servicio_estimaciones.listar_estimaciones(self.propietario, self.pid)[0]
        self.actualizar(ultima["id"], "Tercera")
        self.assertEqual(self.estado(), "recalcular")

    def test_nueva_estimacion_guarda_lo_que_se_envia(self):
        # El formulario propone la anterior; lo que llega es lo que se guarda.
        self.crear(observaciones="Anterior")
        self.assertIsNone(self.crear()["observaciones"])
        self.assertEqual(self.crear(observaciones="Anterior")["observaciones"], "Anterior")

    def test_solo_la_mas_reciente_y_con_cambio(self):
        original = self.crear(observaciones="Primera")
        with self.assertRaises(HTTPException) as error:
            self.actualizar(original["id"], " Primera ")
        self.assertEqual(error.exception.status_code, 409)

        self.crear(observaciones="Otra estimación")
        with self.assertRaises(HTTPException) as error:
            self.actualizar(original["id"], "Tarde")
        self.assertEqual(error.exception.status_code, 409)

    def test_vaciar_la_observacion(self):
        original = self.crear(observaciones="Primera")
        self.assertIsNone(self.actualizar(original["id"], "")["observaciones"])

    def test_queda_en_el_historial(self):
        original = self.crear(observaciones="Primera")
        nueva = self.actualizar(original["id"], "Segunda")
        evento = [h for h in self.db["historial_proyecto"] if h["accion"] == "cotizacion_actualizada"]
        self.assertEqual(len(evento), 1)
        self.assertEqual((evento[0]["entidad_id"], evento[0]["usuario_id"]), (nueva["id"], str(self.editor.id)))
        self.assertEqual((evento[0]["valores_anteriores"], evento[0]["valores_nuevos"]),
                         ({"observaciones": "Primera"}, {"observaciones": "Segunda"}))

    def test_endpoint(self):
        original = self.crear(observaciones="Primera")
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.editor
        self.addCleanup(app.dependency_overrides.clear)
        api = TestClient(app)
        ruta = f"/proyectos/{self.pid}/estimaciones/{original['id']}/actualizar-cotizacion"
        respuesta = api.post(ruta, json={"observaciones": "Desde la API"})
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()["observaciones"], "Desde la API")

        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.lector
        nueva = respuesta.json()["id"]
        respuesta = api.post(f"/proyectos/{self.pid}/estimaciones/{nueva}/actualizar-cotizacion",
                             json={"observaciones": "Lector"})
        self.assertEqual(respuesta.status_code, 403)

    def _datos_otro(self):
        from test_partidas_proyecto import datos_proyecto
        return datos_proyecto(nombre="Otro")


class Migracion006(unittest.TestCase):

    def test_columna_opcional_con_tope(self):
        self.assertIn("add column observaciones text", M006)
        self.assertIn("char_length(observaciones) <= 1000", M006)

    def test_historicas_inmutables(self):
        self.assertIn("before update of observaciones on public.estimaciones", M006)

    def test_crear_estimacion_guarda_la_observacion(self):
        cuerpo = re.search(r"function public\.crear_estimacion\(.*?\$\$;", M006, flags=re.S).group(0)
        self.assertIn("firma_partidas, completa, observaciones", cuerpo)
        self.assertIn("nullif(btrim(r.observaciones), '')", cuerpo)

    def test_rpc_solo_para_service_role(self):
        for firma in ("crear_estimacion(uuid, jsonb, jsonb)", "actualizar_cotizacion(uuid, uuid, text)"):
            self.assertIn(f"revoke execute on function public.{firma} from public, anon, authenticated;", M006)
            self.assertIn(f"grant execute on function public.{firma} to service_role;", M006)

    def test_actualizar_cotizacion_comprueba_permiso_y_vigencia(self):
        cuerpo = re.search(r"function public\.actualizar_cotizacion\(.*?\$\$;", M006, flags=re.S).group(0)
        self.assertIn("v_rol not in ('propietario', 'editor')", cuerpo)
        self.assertIn("order by e.fecha_creacion desc, e.id desc", cuerpo)
        self.assertIn("from public.estimacion_partidas l", cuerpo)


if __name__ == "__main__":
    unittest.main()
