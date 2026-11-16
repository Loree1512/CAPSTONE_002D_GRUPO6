"""GET /proyectos/{id}/historial y los eventos que registra el backend.

Ejecutar desde backend/:
    python -m pytest
"""

from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import autenticacion as dependencias
from app.main import app
from app.schemas.estimacion import PlazoProfesionalDefinir
from app.schemas.partida_proyecto import PartidaProyectoCrear, PartidaProyectoEditar, PlantillaAplicar
from app.schemas.proyecto import ProyectoActualizar
from app.services import servicio_estimaciones, servicio_partidas_proyecto, servicio_proyectos
from test_partidas_proyecto import datos_proyecto
from test_permisos_proyecto import _Base

CAMPOS = {"id", "accion", "entidad", "entidad_id", "usuario_id", "usuario_email", "usuario_nombre",
          "valores_anteriores", "valores_nuevos", "origen", "fecha"}


class HistorialDelProyecto(_Base):

    def setUp(self):
        super().setUp()
        # Se parte de cero: el setUp de la base ya editó una partida.
        self.db["historial_proyecto"] = []
        self.db["perfiles"] = [{"id": str(self.propietario.id), "email": self.propietario.email,
                                "nombre": "Paula Propietaria"}]
        self.ruta = f"/proyectos/{self.pid}/historial"

    def api(self, usuario=None):
        if usuario is not None:
            app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
            self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def eventos(self):
        return [(e["accion"], e["entidad"], e["valores_anteriores"], e["valores_nuevos"])
                for e in self.db["historial_proyecto"]]

    def editar_proyecto(self, usuario, **cambios):
        return servicio_proyectos.actualizar_proyecto(usuario, self.pid, ProyectoActualizar.model_validate(cambios))

    # --- Permisos -----------------------------------------------------------------------

    def test_todos_los_miembros_consultan(self):
        self.editar_proyecto(self.propietario, nombre="Otro nombre")
        for usuario in (self.propietario, self.editor, self.lector):
            with self.subTest(usuario=usuario.email):
                respuesta = self.api(usuario).get(self.ruta)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual([e["accion"] for e in respuesta.json()], ["proyecto_editado"])

    def test_quien_no_pertenece_recibe_404(self):
        self.assertEqual(self.api(self.ajeno).get(self.ruta).status_code, 404)
        self.assertEqual(self.api(self.propietario).get(f"/proyectos/{uuid4()}/historial").status_code, 404)

    def test_sin_token_401(self):
        self.assertEqual(self.api().get(self.ruta).status_code, 401)

    def test_no_se_modifica_ni_se_borra(self):
        self.editar_proyecto(self.propietario, nombre="Otro nombre")
        api = self.api(self.propietario)
        for metodo in ("post", "put", "delete", "patch"):
            with self.subTest(metodo=metodo):
                self.assertEqual(getattr(api, metodo)(self.ruta).status_code, 405)
        self.assertEqual(len(self.db["historial_proyecto"]), 1)

    # --- Respuesta ------------------------------------------------------------------------

    def test_mas_reciente_primero(self):
        self.editar_proyecto(self.propietario, nombre="Primero")
        servicio_partidas_proyecto.eliminar(self.editor, self.pid, self.partidas()[0]["id"])
        servicio_estimaciones.crear_estimacion(self.editor, self.pid, None)

        eventos = self.api(self.lector).get(self.ruta).json()
        self.assertEqual([e["accion"] for e in eventos],
                         ["estimacion_generada", "partida_eliminada", "proyecto_editado"])
        fechas = [e["fecha"] for e in eventos]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_estructura_del_evento(self):
        self.editar_proyecto(self.propietario, nombre="Otro nombre")
        servicio_partidas_proyecto.eliminar(self.editor, self.pid, self.partidas()[0]["id"])

        editado, eliminada = reversed(self.api(self.lector).get(self.ruta).json())
        self.assertEqual(set(editado), CAMPOS)
        self.assertEqual(
            {k: editado[k] for k in CAMPOS - {"id", "fecha"}},
            {"accion": "proyecto_editado", "entidad": "proyecto", "entidad_id": self.pid,
             "usuario_id": str(self.propietario.id), "usuario_email": "propietario@x.cl",
             "usuario_nombre": "Paula Propietaria",
             "valores_anteriores": {"nombre": "Ampliación Quiroz"}, "valores_nuevos": {"nombre": "Otro nombre"},
             "origen": "api"},
        )
        # Sin perfil con nombre: queda el correo para mostrar.
        self.assertEqual((eliminada["usuario_nombre"], eliminada["usuario_email"]), (None, "editor@x.cl"))

    def test_solo_eventos_del_proyecto(self):
        otro = servicio_proyectos.crear_proyecto(self.propietario, datos_proyecto(nombre="Otro"))["id"]
        servicio_proyectos.actualizar_proyecto(self.propietario, otro, ProyectoActualizar(nombre="Cambiado"))
        self.assertEqual(self.api(self.propietario).get(self.ruta).json(), [])

    def test_limite(self):
        for n in range(4):
            self.editar_proyecto(self.propietario, nombre=f"Nombre {n}")
        api = self.api(self.propietario)
        self.assertEqual(len(api.get(self.ruta).json()), 4)
        eventos = api.get(f"{self.ruta}?limite=2").json()
        self.assertEqual([e["valores_nuevos"]["nombre"] for e in eventos], ["Nombre 3", "Nombre 2"])
        for limite in (0, 201, "x"):
            self.assertEqual(api.get(f"{self.ruta}?limite={limite}").status_code, 422)

    # --- Eventos que registra el backend -----------------------------------------------------

    def test_proyecto_editado_solo_con_lo_que_cambia(self):
        self.editar_proyecto(self.editor, nombre="Casa Nueva", superficie_m2=48, comuna="Quilpué", numero_pisos=2)
        self.assertEqual(self.eventos(), [(
            "proyecto_editado", "proyecto",
            {"nombre": "Ampliación Quiroz", "numero_pisos": 1},
            {"nombre": "Casa Nueva", "numero_pisos": 2},
        )])

        # Guardar lo mismo no deja registro.
        self.editar_proyecto(self.editor, nombre="Casa Nueva", superficie_m2=48.0)
        self.assertEqual(len(self.eventos()), 1)

    def test_partida_agregada_editada_y_eliminada(self):
        creada = servicio_partidas_proyecto.crear(self.editor, self.pid, PartidaProyectoCrear.model_validate(
            {"origen": "manual", "categoria_id": 1, "nombre": "Cierre provisorio", "unidad": "ml",
             "cantidad": 12, "precio_unitario_override": 9000}))
        servicio_partidas_proyecto.editar(self.editor, self.pid, creada["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 15, "unidad": "ml"}))
        servicio_partidas_proyecto.eliminar(self.editor, self.pid, creada["id"])

        self.assertEqual(self.eventos(), [
            ("partida_agregada", "proyecto_partida", None,
             {"nombre": "Cierre provisorio", "unidad": "ml", "cantidad": "12", "origen": "manual"}),
            ("partida_editada", "proyecto_partida", {"cantidad": "12"}, {"cantidad": "15", "nombre": "Cierre provisorio"}),
            ("partida_eliminada", "proyecto_partida",
             {"nombre": "Cierre provisorio", "unidad": "ml", "cantidad": "15", "origen": "manual"}, None),
        ])
        self.assertTrue(all(e["entidad_id"] == creada["id"] for e in self.db["historial_proyecto"]))

    def test_editar_sin_cambios_no_registra(self):
        partida = self.partidas()[1]
        servicio_partidas_proyecto.editar(self.editor, self.pid, partida["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": partida["cantidad"]}))
        self.assertEqual(self.eventos(), [])

    def test_plantilla_aplicada(self):
        servicio_partidas_proyecto.aplicar_plantilla(self.editor, self.pid, PlantillaAplicar(reemplazar=True))
        plantilla = self.db["plantillas_presupuesto"][0]
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual((evento["accion"], evento["entidad"], evento["entidad_id"]),
                         ("plantilla_aplicada", "plantilla", plantilla["id"]))
        self.assertEqual((evento["valores_anteriores"], evento["valores_nuevos"]),
                         ({"partidas": 2}, {"nombre": plantilla["nombre"], "partidas": 2}))

        # Sin partidas previas no hay nada reemplazado.
        self.db["proyecto_partidas"] = [f for f in self.db["proyecto_partidas"] if f["proyecto_id"] != self.pid]
        servicio_partidas_proyecto.aplicar_plantilla(self.editor, self.pid, PlantillaAplicar())
        self.assertIsNone(self.db["historial_proyecto"][-1]["valores_anteriores"])

    def test_estimacion_generada(self):
        creada = servicio_estimaciones.crear_estimacion(self.editor, self.pid, None)
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual((evento["accion"], evento["entidad"], evento["entidad_id"]),
                         ("estimacion_generada", "estimacion", creada["id"]))
        self.assertEqual(set(evento["valores_nuevos"]),
                         {"costo_total", "costo_m2", "version_precio", "completa", "plazo_dias", "version_modelo"})
        self.assertEqual(float(evento["valores_nuevos"]["costo_total"]), float(creada["total"]))

    def test_estimacion_guarda_el_costo_que_reemplaza(self):
        # La primera no tiene costo previo: queda en null, no se inventa.
        primera = servicio_estimaciones.crear_estimacion(self.editor, self.pid, None)
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual(evento["valores_anteriores"], {"costo_total": None, "costo_m2": None})

        # Al recalcular, el anterior es el costo de la estimación previa.
        servicio_partidas_proyecto.editar(self.editor, self.pid, self.partidas()[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 40}))
        segunda = servicio_estimaciones.crear_estimacion(self.editor, self.pid, None)
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual(float(evento["valores_anteriores"]["costo_total"]), float(primera["total"]))
        self.assertEqual(float(evento["valores_nuevos"]["costo_total"]), float(segunda["total"]))
        self.assertNotEqual(primera["total"], segunda["total"])

    def test_plazo_profesional_definido(self):
        creada = servicio_estimaciones.crear_estimacion(self.editor, self.pid, None)
        definida = servicio_estimaciones.definir_plazo_profesional(
            self.editor, self.pid, creada["id"], PlazoProfesionalDefinir(dias=135))
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual((evento["accion"], evento["entidad"], evento["entidad_id"]),
                         ("plazo_profesional_definido", "estimacion", definida["id"]))
        self.assertEqual((evento["valores_anteriores"], evento["valores_nuevos"]),
                         ({"plazo_profesional_dias": None, "plazo_profesional_estado": "sin_definir"},
                          {"plazo_profesional_dias": 135, "plazo_profesional_origen": "manual"}))

        # El lector no lo define y no queda evento.
        with self.assertRaises(HTTPException) as error:
            servicio_estimaciones.definir_plazo_profesional(
                self.lector, self.pid, definida["id"], PlazoProfesionalDefinir(dias=150))
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(len([h for h in self.db["historial_proyecto"]
                              if h["accion"] == "plazo_profesional_definido"]), 1)

    def test_sin_permiso_no_hay_evento(self):
        self.assert_estado(self.escrituras(self.lector), 403)
        self.assert_estado(self.escrituras(self.ajeno), 404)
        self.assertEqual(self.eventos(), [])


del _Base  # la base no se ejecuta como prueba en este módulo
