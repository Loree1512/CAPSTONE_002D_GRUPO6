"""DELETE /proyectos/{id}: solo el propietario elimina.

Ejecutar desde backend/:
    python -m pytest
"""

import copy
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import autenticacion as dependencias
from app.main import app
from app.services import servicio_estimaciones, servicio_proyectos
from test_autenticacion import token_rechazado_por_supabase
from test_partidas_proyecto import datos_proyecto
from test_permisos_proyecto import _Base


class EliminarProyecto(_Base):

    def setUp(self):
        super().setUp()
        self.db["historial_proyecto"] = []
        servicio_estimaciones.crear_estimacion(self.propietario, self.pid, None)
        self.estimacion = self.db["estimaciones"][0]["id"]
        self.assertTrue(self.ids("estimacion_partidas", "estimacion_id"))
        self.db["historial_proyecto"].append({"id": str(uuid4()), "proyecto_id": self.pid, "accion": "proyecto_creado"})

        # Otro proyecto del mismo propietario.
        self.otro = servicio_proyectos.crear_proyecto(self.propietario, datos_proyecto(nombre="Otro"))["id"]
        self.agregar(self.otro, self.editor, "lector")
        servicio_estimaciones.crear_estimacion(self.propietario, self.otro, None)
        self.db["historial_proyecto"].append({"id": str(uuid4()), "proyecto_id": self.otro, "accion": "proyecto_creado"})

        self.ruta = f"/proyectos/{self.pid}"

    def api(self, usuario):
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def ids(self, tabla, campo="proyecto_id"):
        return {f[campo] for f in self.db[tabla]}

    # --- Propietario ------------------------------------------------------------------------

    def test_propietario_elimina_con_204(self):
        respuesta = self.api(self.propietario).delete(self.ruta)

        self.assertEqual(respuesta.status_code, 204)
        self.assertEqual(respuesta.content, b"")
        self.assertNotIn(self.pid, {p["id"] for p in self.db["proyectos"]})

    def test_el_proyecto_deja_de_existir(self):
        self.api(self.propietario).delete(self.ruta)

        cliente = self.api(self.propietario)
        self.assertEqual(cliente.get(self.ruta).status_code, 404)
        self.assertEqual(cliente.delete(self.ruta).status_code, 404)
        self.assertNotIn(self.pid, {p["id"] for p in cliente.get("/proyectos").json()})
        # También para quienes eran miembros.
        for usuario in (self.editor, self.lector):
            self.assertEqual(self.api(usuario).get(self.ruta).status_code, 404)

    def test_se_van_los_datos_relacionados(self):
        self.api(self.propietario).delete(self.ruta)

        for tabla in ("proyecto_partidas", "estimaciones", "proyecto_miembros", "historial_proyecto"):
            with self.subTest(tabla=tabla):
                self.assertNotIn(self.pid, self.ids(tabla))
        self.assertNotIn(self.estimacion, self.ids("estimacion_partidas", "estimacion_id"))

    def test_otro_proyecto_del_mismo_usuario_no_se_afecta(self):
        antes = {t: copy.deepcopy([f for f in self.db[t] if f.get("proyecto_id") == self.otro])
                 for t in ("proyecto_partidas", "estimaciones", "proyecto_miembros", "historial_proyecto")}
        partidas_estimacion = copy.deepcopy(
            [f for f in self.db["estimacion_partidas"] if f["estimacion_id"] != self.estimacion])
        self.assertTrue(partidas_estimacion)
        proyecto_antes = copy.deepcopy(next(p for p in self.db["proyectos"] if p["id"] == self.otro))

        self.api(self.propietario).delete(self.ruta)

        for tabla, filas in antes.items():
            with self.subTest(tabla=tabla):
                self.assertTrue(filas)
                self.assertEqual([f for f in self.db[tabla] if f.get("proyecto_id") == self.otro], filas)
        self.assertEqual(self.db["estimacion_partidas"], partidas_estimacion)
        self.assertEqual(next(p for p in self.db["proyectos"] if p["id"] == self.otro), proyecto_antes)
        self.assertEqual([p["id"] for p in self.api(self.propietario).get("/proyectos").json()], [self.otro])

    def test_creador_sin_fila_de_miembro_elimina(self):
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]

        self.assertEqual(self.api(self.propietario).delete(self.ruta).status_code, 204)

    # --- Sin permiso --------------------------------------------------------------------------

    def test_editor_y_lector_reciben_403_y_no_cambia_nada(self):
        antes = copy.deepcopy(self.db)

        for usuario in (self.editor, self.lector):
            with self.subTest(usuario=usuario.email):
                respuesta = self.api(usuario).delete(self.ruta)
                self.assertEqual(respuesta.status_code, 403)
                self.assertIn("permiso", respuesta.json()["detail"])
        self.assertEqual(self.db, antes)

    def test_no_miembro_recibe_404_y_no_cambia_nada(self):
        antes = copy.deepcopy(self.db)

        self.assertEqual(self.api(self.ajeno).delete(self.ruta).status_code, 404)
        self.assertEqual(self.api(self.propietario).delete(f"/proyectos/{uuid4()}").status_code, 404)
        self.assertEqual(self.db, antes)

    def test_sin_token_recibe_401(self):
        antes = copy.deepcopy(self.db)

        self.assertEqual(TestClient(app).delete(self.ruta).status_code, 401)
        # Supabase rechaza el token: sin salir a la red.
        with patch.object(dependencias, "get_anon_client", return_value=token_rechazado_por_supabase()):
            self.assertEqual(
                TestClient(app).delete(self.ruta, headers={"Authorization": "Bearer malo"}).status_code, 401)
        self.assertEqual(self.db, antes)

    def test_si_la_base_no_borra_nada_responde_404(self):
        # RLS rechaza el DELETE (0 filas) aunque la API lo haya autorizado.
        proyecto = {**next(p for p in self.db["proyectos"] if p["id"] == self.pid)}
        with self.assertRaises(HTTPException) as error:
            servicio_proyectos.eliminar_proyecto(self.editor, proyecto)

        self.assertEqual(error.exception.status_code, 404)
        self.assertIn(self.pid, {p["id"] for p in self.db["proyectos"]})
