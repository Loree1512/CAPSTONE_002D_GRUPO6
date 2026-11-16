"""Plazo para la cotización: el modelo sugiere y el profesional decide (migración 010).

Las RPC se simulan con el cliente falso de test_partidas_proyecto (mismo comportamiento
que las funciones SQL de la 010). Ninguna prueba se conecta a Supabase.

Ejecutar desde backend/:
    python -m pytest
"""

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from datetime import date  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.estimacion import CotizacionActualizar, EstimacionCrear, PlazoProfesionalDefinir  # noqa: E402
from app.schemas.partida_proyecto import PartidaProyectoEditar  # noqa: E402
from app.services import estimador_plazo as ep  # noqa: E402
from app.services import servicio_estimaciones, servicio_partidas_proyecto, servicio_proyectos  # noqa: E402
from app.services.snapshot_estimacion import armar_plazo, armar_profesional, armar_resumen  # noqa: E402
from test_permisos_proyecto import _Base  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
M010 = (RAIZ / "supabase" / "migrations" / "010_plazo_profesional.sql").read_text(encoding="utf-8")
VERIFICAR_010 = RAIZ / "supabase" / "tests" / "verificar_010_plazo_profesional.sql"

VERSION = "v1.0-2026-11-01"
HOY = date(2026, 11, 3)
MAE = 5.597655503039676
# Como la fila de versiones_modelo de la 009: metricas = metricas_loo del JSON del backend.
VERSION_MODELO = {"version": VERSION, "metodo": "P2", "estado": "provisional",
                  "metricas": {"mae": MAE, "rmse": 7.697974088577048}}


class _Plazo(_Base):

    def setUp(self):
        super().setUp()
        self.db["valores_uf"] = [{"fecha": HOY.isoformat(), "valor": "41263.57", "fuente": "cmf"}]
        self.db["versiones_modelo"] = [dict(VERSION_MODELO)]
        self.db["perfiles"] = [{"id": str(self.editor.id), "email": self.editor.email, "nombre": "Elena Editora"}]
        parche = patch.object(ep, "fecha_chile", return_value=HOY)
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(ep.cargar_modelo.cache_clear)

    def crear(self, usuario=None, **datos):
        return servicio_estimaciones.crear_estimacion(usuario or self.propietario, self.pid, EstimacionCrear(**datos))

    def definir(self, estimacion_id, usuario=None, **datos):
        return servicio_estimaciones.definir_plazo_profesional(
            usuario or self.editor, self.pid, estimacion_id, PlazoProfesionalDefinir(**datos))

    def fila(self, estimacion_id):
        return next(e for e in self.db["estimaciones"] if e["id"] == estimacion_id)

    def recalcular(self, cantidad=40):
        servicio_partidas_proyecto.editar(self.propietario, self.pid, self.partidas()[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": cantidad}))
        return self.crear()

    def eventos(self, accion="plazo_profesional_definido"):
        return [h for h in self.db["historial_proyecto"] if h["accion"] == accion]


class EstimacionNueva(_Plazo):

    def test_genera_sugerencia_pero_no_plazo_profesional(self):
        creada = self.crear()
        self.assertIsNotNone(creada["plazo"]["dias"])
        self.assertEqual(creada["plazo_profesional"]["estado"], "sin_definir")
        for campo in ("dias", "origen", "fecha", "usuario_id", "usuario_nombre"):
            self.assertIsNone(creada["plazo_profesional"][campo], campo)
        fila = self.fila(creada["id"])
        self.assertIsNone(fila["plazo_profesional_dias"])
        self.assertEqual(fila["plazo_profesional_estado"], "sin_definir")

    def test_el_payload_no_define_el_plazo_profesional(self):
        # Aunque un cliente lo intente, crear_estimacion no toma el plazo profesional del payload.
        cabecera_original = servicio_estimaciones.a_filas

        def con_intento(*args, **kwargs):
            cabecera, lineas = cabecera_original(*args, **kwargs)
            cabecera.update(plazo_profesional_dias=999, plazo_profesional_estado="definido",
                            plazo_profesional_origen="manual")
            return cabecera, lineas

        with patch.object(servicio_estimaciones, "a_filas", side_effect=con_intento):
            creada = self.crear()
        self.assertEqual(self.fila(creada["id"])["plazo_profesional_estado"], "sin_definir")
        self.assertIsNone(self.fila(creada["id"])["plazo_profesional_dias"])


class DefinirPlazo(_Plazo):

    def test_plazo_manual(self):
        original = self.crear()
        definida = self.definir(original["id"], dias=135)

        self.assertNotEqual(definida["id"], original["id"])
        pp = definida["plazo_profesional"]
        self.assertEqual((pp["dias"], pp["estado"], pp["origen"]), (135, "definido", "manual"))
        self.assertEqual(str(pp["usuario_id"]), str(self.editor.id))
        self.assertEqual(pp["usuario_nombre"], "Elena Editora")
        self.assertIsNotNone(pp["fecha"])
        # La sugerencia del modelo y los montos no cambian.
        self.assertEqual(definida["plazo"], original["plazo"])
        self.assertEqual(definida["total"], original["total"])
        # La anterior conserva su estado: el snapshot es inmutable.
        releida = servicio_estimaciones.obtener_estimacion(self.propietario, self.pid, original["id"])
        self.assertEqual(releida["plazo_profesional"]["estado"], "sin_definir")

    def test_no_ejecuta_el_modelo(self):
        original = self.crear()
        with patch.object(ep, "estimar", side_effect=AssertionError("no debe recalcular")), \
                patch.object(ep, "cargar_modelo", side_effect=AssertionError("no debe cargar")):
            definida = self.definir(original["id"], dias=60)
        for columna in ("plazo_dias", "plazo_min_dias", "plazo_max_dias", "plazo_metodo", "plazo_estado",
                        "version_modelo", "uf_valor", "uf_fecha", "costo_total", "observaciones"):
            self.assertEqual(self.fila(definida["id"])[columna], self.fila(original["id"])[columna], columna)

    def test_usar_sugerencia(self):
        original = self.crear()
        definida = self.definir(original["id"], usar_sugerencia=True)
        pp = definida["plazo_profesional"]
        self.assertEqual((pp["dias"], pp["origen"], pp["estado"]), (original["plazo"]["dias"], "sugerencia", "definido"))
        # El valor lo toma la RPC de la fila, no el cliente.
        nombre, parametros = self.admin_rpcs()[-1]
        self.assertEqual((nombre, parametros["p_dias"], parametros["p_origen"]),
                         ("definir_plazo_profesional", None, "sugerencia"))

    def test_usar_sugerencia_sin_sugerencia_409(self):
        with patch.object(ep, "cargar_modelo", side_effect=OSError("sin modelo")), \
                self.assertLogs(ep.logger, level="ERROR"):
            sin_plazo = self.crear()
        self.assertIsNone(sin_plazo["plazo"]["dias"])
        with self.assertRaises(HTTPException) as error:
            self.definir(sin_plazo["id"], usar_sugerencia=True)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("plazo sugerido", error.exception.detail)
        # Escribirlo a mano sí se puede.
        self.assertEqual(self.definir(sin_plazo["id"], dias=30)["plazo_profesional"]["dias"], 30)

    def test_modificar_el_plazo(self):
        primera = self.definir(self.crear()["id"], dias=135)
        segunda = self.definir(primera["id"], dias=150)
        self.assertEqual(segunda["plazo_profesional"]["dias"], 150)
        self.assertEqual(self.fila(primera["id"])["plazo_profesional_dias"], 135)

    def test_mismo_valor_409_y_solo_la_mas_reciente(self):
        primera = self.definir(self.crear()["id"], dias=135)
        with self.assertRaises(HTTPException) as error:
            self.definir(primera["id"], dias=135)
        self.assertEqual(error.exception.status_code, 409)

        self.definir(primera["id"], dias=140)
        with self.assertRaises(HTTPException) as error:
            self.definir(primera["id"], dias=160)
        self.assertEqual(error.exception.status_code, 409)

    def test_validacion_del_cuerpo(self):
        for datos in ({}, {"dias": 0}, {"dias": 3651}, {"dias": 10, "usar_sugerencia": True}):
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                PlazoProfesionalDefinir(**datos)
        self.assertTrue(PlazoProfesionalDefinir.model_validate({"usarSugerencia": True}).usar_sugerencia)
        self.assertEqual(PlazoProfesionalDefinir(dias=3650).dias, 3650)

    def admin_rpcs(self):
        return servicio_estimaciones.supabase_admin.rpcs


class Permisos(_Plazo):

    def test_propietario_y_editor_lo_definen(self):
        primera = self.definir(self.crear()["id"], self.propietario, dias=100)
        self.assertEqual(self.definir(primera["id"], self.editor, dias=110)["plazo_profesional"]["dias"], 110)

    def test_lector_403_y_ajeno_404(self):
        creada = self.crear()
        antes = len(self.db["estimaciones"])
        self.assert_estado({
            "manual": lambda: self.definir(creada["id"], self.lector, dias=135),
            "sugerencia": lambda: self.definir(creada["id"], self.lector, usar_sugerencia=True),
        }, 403)
        self.assert_estado({"ajeno": lambda: self.definir(creada["id"], self.ajeno, dias=135)}, 404)
        self.assert_estado({"inexistente": lambda: self.definir(uuid4(), self.propietario, dias=135)}, 404)
        self.assertEqual(len(self.db["estimaciones"]), antes)
        self.assertEqual(self.eventos(), [])
        # El lector sí lo ve.
        definida = self.definir(creada["id"], dias=135)
        leida = servicio_estimaciones.obtener_estimacion(self.lector, self.pid, definida["id"])
        self.assertEqual(leida["plazo_profesional"]["dias"], 135)

    def test_endpoint(self):
        creada = self.crear()
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.editor
        self.addCleanup(app.dependency_overrides.clear)
        api = TestClient(app)
        ruta = f"/proyectos/{self.pid}/estimaciones/{creada['id']}/plazo-profesional"

        self.assertEqual(api.post(ruta, json={"dias": 0}).status_code, 422)
        respuesta = api.post(ruta, json={"usarSugerencia": True})
        self.assertEqual(respuesta.status_code, 201)
        cuerpo = respuesta.json()
        self.assertEqual(set(cuerpo["plazoProfesional"]),
                         {"dias", "estado", "origen", "fecha", "usuarioId", "usuarioNombre"})
        self.assertEqual((cuerpo["plazoProfesional"]["estado"], cuerpo["plazoProfesional"]["origen"]),
                         ("definido", "sugerencia"))

        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: self.lector
        ruta = f"/proyectos/{self.pid}/estimaciones/{cuerpo['id']}/plazo-profesional"
        self.assertEqual(api.post(ruta, json={"dias": 90}).status_code, 403)


class RecalcularYActualizar(_Plazo):

    def test_recalcular_deja_por_revisar_conservando_el_valor(self):
        definida = self.definir(self.crear()["id"], dias=135)
        recalculada = self.recalcular()

        pp = recalculada["plazo_profesional"]
        self.assertEqual((pp["dias"], pp["estado"], pp["origen"]), (135, "por_revisar", "manual"))
        self.assertEqual(pp["fecha"], definida["plazo_profesional"]["fecha"])
        self.assertEqual(str(pp["usuario_id"]), str(self.editor.id))
        # Hay una sugerencia nueva del modelo, distinta del plazo profesional.
        self.assertNotEqual(recalculada["total"], definida["total"])
        self.assertIsNotNone(recalculada["plazo"]["dias"])

        # Sigue por revisar en otro recálculo, y se resuelve con «Mantener».
        otra = self.recalcular(60)
        self.assertEqual(otra["plazo_profesional"]["estado"], "por_revisar")
        confirmada = self.definir(otra["id"], dias=135)
        self.assertEqual(confirmada["plazo_profesional"]["estado"], "definido")

    def test_recalcular_sin_definir_sigue_sin_definir(self):
        self.crear()
        self.assertEqual(self.recalcular()["plazo_profesional"]["estado"], "sin_definir")

    def test_actualizar_cotizacion_copia_el_plazo_profesional(self):
        definida = self.definir(self.crear()["id"], usar_sugerencia=True)
        copia = servicio_estimaciones.actualizar_cotizacion(
            self.propietario, self.pid, definida["id"], CotizacionActualizar(observaciones="Nueva nota"))
        for columna in ("plazo_profesional_dias", "plazo_profesional_estado", "plazo_profesional_origen",
                        "plazo_profesional_fecha", "plazo_profesional_usuario_id"):
            self.assertEqual(self.fila(copia["id"])[columna], self.fila(definida["id"])[columna], columna)
        self.assertEqual(copia["plazo_profesional"]["usuario_nombre"], "Elena Editora")


class Historial(_Plazo):

    def test_definido_actualizado_y_confirmado(self):
        primera = self.definir(self.crear()["id"], dias=135)
        segunda = self.definir(primera["id"], usar_sugerencia=True)
        recalculada = self.recalcular()
        self.definir(recalculada["id"], dias=segunda["plazo_profesional"]["dias"])

        eventos = self.eventos()
        self.assertEqual(len(eventos), 3)
        self.assertEqual((eventos[0]["entidad"], eventos[0]["entidad_id"], eventos[0]["usuario_id"]),
                         ("estimacion", primera["id"], str(self.editor.id)))
        self.assertEqual(
            [(e["valores_anteriores"], e["valores_nuevos"]) for e in eventos],
            [
                ({"plazo_profesional_dias": None, "plazo_profesional_estado": "sin_definir"},
                 {"plazo_profesional_dias": 135, "plazo_profesional_origen": "manual"}),
                ({"plazo_profesional_dias": 135, "plazo_profesional_estado": "definido"},
                 {"plazo_profesional_dias": segunda["plazo_profesional"]["dias"],
                  "plazo_profesional_origen": "sugerencia"}),
                ({"plazo_profesional_dias": segunda["plazo_profesional"]["dias"],
                  "plazo_profesional_estado": "por_revisar"},
                 {"plazo_profesional_dias": segunda["plazo_profesional"]["dias"],
                  "plazo_profesional_origen": "manual"}),
            ],
        )
        # Sin datos técnicos del modelo en el evento.
        for e in eventos + self.eventos("plazo_profesional_por_revisar"):
            self.assertNotIn("version_modelo", {**e["valores_anteriores"], **e["valores_nuevos"]})


    def test_recalcular_registra_por_revisar_una_sola_vez(self):
        definida = self.definir(self.crear()["id"], dias=135)
        recalculada = self.recalcular()

        eventos = self.eventos("plazo_profesional_por_revisar")
        self.assertEqual(len(eventos), 1)
        self.assertEqual((eventos[0]["entidad"], eventos[0]["entidad_id"], eventos[0]["usuario_id"]),
                         ("estimacion", recalculada["id"], str(self.propietario.id)))
        self.assertEqual(
            (eventos[0]["valores_anteriores"], eventos[0]["valores_nuevos"]),
            ({"plazo_profesional_dias": 135, "plazo_profesional_estado": "definido"},
             {"plazo_profesional_dias": 135, "plazo_profesional_estado": "por_revisar"}),
        )
        self.assertEqual(definida["plazo_profesional"]["dias"], 135)

        # Otro recálculo sobre uno ya por revisar no repite el aviso.
        self.recalcular(60)
        self.assertEqual(len(self.eventos("plazo_profesional_por_revisar")), 1)
        # El evento de la estimación sigue guardando solo el costo como anterior.
        generada = self.eventos("estimacion_generada")[-1]
        self.assertEqual(set(generada["valores_anteriores"]), {"costo_total", "costo_m2"})

    def test_recalcular_sin_plazo_definido_no_registra_por_revisar(self):
        self.crear()
        self.recalcular()
        self.assertEqual(self.eventos("plazo_profesional_por_revisar"), [])


class FilasHistoricas(unittest.TestCase):

    def test_fila_anterior_a_la_010_queda_sin_definir(self):
        # Una estimación anterior a la 010 con plazo del modelo: no se convierte en plazo profesional.
        fila = {"plazo_estado": "dentro_dominio", "plazo_dias": 41, "plazo_metodo": "P2"}
        self.assertEqual(armar_profesional(fila), {"estado": "sin_definir"})

    def test_fila_anterior_a_la_009(self):
        self.assertEqual(armar_profesional({"id": "x"}), {"estado": "sin_definir"})
        self.assertEqual(armar_plazo({"id": "x"})["estado"], "no_disponible")

    def test_migrada_sin_definir_no_inventa_autor(self):
        fila = {"plazo_profesional_estado": "sin_definir", "plazo_profesional_dias": None,
                "plazo_profesional_usuario_id": None}
        self.assertIsNone(armar_profesional(fila, "Nombre")["usuario_nombre"])


class ErrorMedioDelModelo(_Plazo):

    def test_sale_de_la_version_del_modelo(self):
        plazo = self.crear()["plazo"]
        self.assertEqual(plazo["metodo"], "P2")
        self.assertAlmostEqual(plazo["error_medio_dias"], MAE)
        self.assertEqual(plazo["estado_modelo"], "provisional")
        # También en el listado de estimaciones.
        listado = servicio_estimaciones.listar_estimaciones(self.lector, self.pid)
        self.assertAlmostEqual(listado[0]["plazo"]["error_medio_dias"], MAE)

    def test_cambia_si_cambian_las_metricas_de_la_version(self):
        self.db["versiones_modelo"][0]["metricas"] = {"mae": 4.2}
        self.assertEqual(self.crear()["plazo"]["error_medio_dias"], 4.2)

    def test_respaldo_sin_metrica(self):
        self.db["valores_uf"] = []
        plazo = self.crear()["plazo"]
        self.assertEqual(plazo["metodo"], ep.METODO_RESPALDO)
        self.assertIsNone(plazo["error_medio_dias"])
        self.assertEqual(plazo["estado_modelo"], "provisional")

    def test_version_sin_metricas_o_sin_embebido(self):
        self.db["versiones_modelo"][0]["metricas"] = None
        self.assertIsNone(self.crear()["plazo"]["error_medio_dias"])
        fila = {"plazo_estado": "dentro_dominio", "plazo_dias": 41, "plazo_metodo": "P2"}
        self.assertIsNone(armar_plazo(fila)["error_medio_dias"])

    def test_resumen_sin_versiones_modelo_no_falla(self):
        resumen = armar_resumen({
            "id": "e", "proyecto_id": "p", "fecha_creacion": "2026-11-03T10:00:00+00:00", "version_motor": "m",
            "version_precio_id": "v", "version_precio": "2026-T3", "costo_directo": 1, "costo_total": 1,
            "costo_m2": 1, "completa": True, "partidas_calculadas": 1, "partidas_sin_precio": 0,
            "partidas_sin_cantidad": 0, "plazo_estado": "dentro_dominio", "plazo_dias": 41, "plazo_metodo": "P2",
            "versiones_modelo": None,
        })
        self.assertIsNone(resumen["plazo"]["error_medio_dias"])
        self.assertEqual(resumen["plazo_profesional"], {"estado": "sin_definir"})


class ResumenDelListado(_Plazo):

    def resumen(self):
        return servicio_proyectos.obtener_proyecto_por_id(self.propietario, self.pid)

    def test_sin_estimacion(self):
        p = self.resumen()
        self.assertEqual((p["plazo_profesional_dias"], p["plazo_profesional_estado"]), (None, None))

    def test_sin_definir_definido_y_por_revisar(self):
        creada = self.crear()
        p = self.resumen()
        self.assertEqual((p["plazo_profesional_dias"], p["plazo_profesional_estado"]), (None, "sin_definir"))
        # La sugerencia del modelo sigue disponible por separado, pero no es el plazo del listado.
        self.assertEqual(p["plazo_dias"], creada["plazo"]["dias"])

        self.definir(creada["id"], dias=135)
        p = self.resumen()
        self.assertEqual((p["plazo_profesional_dias"], p["plazo_profesional_estado"]), (135, "definido"))

        self.recalcular()
        p = self.resumen()
        self.assertEqual((p["plazo_profesional_dias"], p["plazo_profesional_estado"]), (135, "por_revisar"))


class Migracion010(unittest.TestCase):

    def cuerpo(self, funcion):
        return re.search(rf"function public\.{funcion}\(.*?\$\$;", M010, flags=re.S).group(0)

    def test_columnas_y_restricciones(self):
        for texto in ("add column plazo_profesional_dias integer",
                      "plazo_profesional_dias between 1 and 3650",
                      "add column plazo_profesional_estado text not null default 'sin_definir'",
                      "plazo_profesional_estado in ('sin_definir', 'definido', 'por_revisar')",
                      "plazo_profesional_origen in ('sugerencia', 'manual')",
                      "add column plazo_profesional_fecha timestamptz",
                      "references auth.users(id) on delete set null",
                      "constraint estimaciones_plazo_profesional_estado_chk"):
            self.assertIn(texto, M010)

    def test_no_renombra_ni_destruye(self):
        sin_comentarios = re.sub(r"--[^\n]*", "", M010).lower()
        for prohibido in ("rename", "drop column", "drop table", "delete from", "truncate"):
            self.assertNotIn(prohibido, sin_comentarios)
        # No convierte la sugerencia histórica en plazo profesional.
        self.assertNotRegex(sin_comentarios, r"update public\.estimaciones")
        self.assertNotRegex(sin_comentarios, r"plazo_profesional_dias\s*=\s*plazo_dias")

    def test_trigger_cubre_el_plazo_profesional(self):
        cuerpo = self.cuerpo("bloquear_cambio_plazo")
        self.assertIn("new.plazo_profesional_dias, new.plazo_profesional_estado", cuerpo)
        self.assertIn("new.plazo_profesional_usuario_id is not null", cuerpo)
        # Mantiene las columnas de la 009.
        self.assertIn("new.plazo_dias, new.plazo_min_dias, new.plazo_max_dias", cuerpo)

    def test_crear_estimacion_ignora_el_payload(self):
        cuerpo = self.cuerpo("crear_estimacion")
        self.assertNotIn("r.plazo_profesional", cuerpo)
        self.assertIn("'por_revisar' else 'sin_definir'", cuerpo)
        self.assertIn("order by e.fecha_creacion desc, e.id desc", cuerpo)

    def test_actualizar_cotizacion_copia_el_plazo_profesional(self):
        cuerpo = self.cuerpo("actualizar_cotizacion")
        self.assertIn("v_origen.plazo_profesional_dias, v_origen.plazo_profesional_estado", cuerpo)

    def test_definir_plazo_profesional(self):
        cuerpo = self.cuerpo("definir_plazo_profesional")
        self.assertIn("v_rol not in ('propietario', 'editor')", cuerpo)
        self.assertIn("v_dias := v_origen.plazo_dias", cuerpo)
        self.assertIn("v_dias, 'definido', p_origen, now(), p_usuario_id", cuerpo)
        self.assertIn("from public.estimacion_partidas l", cuerpo)

    def test_rpc_solo_para_service_role(self):
        for firma in ("crear_estimacion(uuid, jsonb, jsonb)", "actualizar_cotizacion(uuid, uuid, text)",
                      "definir_plazo_profesional(uuid, uuid, integer, text)"):
            self.assertIn(f"revoke execute on function public.{firma} from public, anon, authenticated;", M010)
            self.assertIn(f"grant execute on function public.{firma} to service_role;", M010)

    def test_script_de_verificacion_termina_en_rollback(self):
        texto = VERIFICAR_010.read_text(encoding="utf-8")
        self.assertTrue(texto.rstrip().endswith("rollback;"))


del _Plazo  # la base no se ejecuta como prueba en este módulo


if __name__ == "__main__":
    unittest.main()
