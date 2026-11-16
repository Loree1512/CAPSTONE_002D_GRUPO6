"""Permisos por proyecto: propietario, editor y lector.

Quien no pertenece al proyecto recibe 404; quien pertenece sin permiso suficiente, 403.
El cliente falso imita las políticas de membresía de la 003 (con_miembros=True), salvo en
SinLaMigracion003, que usa las de la 001.

Ejecutar desde backend/:
    python -m pytest
"""

import copy
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.dependencies import permisos_proyecto  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.autenticacion import UsuarioActual  # noqa: E402
from app.schemas.partida_proyecto import (  # noqa: E402
    PartidaProyectoCrear,
    PartidaProyectoEditar,
    PartidasOrdenar,
    PlantillaAplicar,
)
from app.schemas.proyecto import ProyectoActualizar, ProyectoRespuesta, RolProyecto  # noqa: E402
from app.services import (  # noqa: E402
    servicio_estimaciones,
    servicio_historial,
    servicio_partidas_proyecto,
    servicio_plantillas,
    servicio_proyectos,
)
from test_partidas_proyecto import ClienteFalso, base_de_datos, datos_proyecto  # noqa: E402

MODULOS = (servicio_proyectos, servicio_partidas_proyecto, servicio_plantillas, servicio_estimaciones,
           servicio_historial, permisos_proyecto)


class _Base(unittest.TestCase):
    con_miembros = True

    def setUp(self):
        self.db = base_de_datos()
        self.db["estimaciones"], self.db["estimacion_partidas"] = [], []
        self.db["parametros_calculo"] = [
            {"clave": "gastos_generales_pct", "valor": 10},
            {"clave": "utilidad_pct", "valor": 10},
            {"clave": "factores_comuna", "valor": {"Quilpué": 1.0}},
            {"clave": "tramos_pisos", "valor": [{"desde": 1, "hasta": 99, "factor": 1.0}]},
        ]
        self.faenas, self.radier, _ = self.db["partidas"]
        self.consultas = []

        def cliente_de(token):
            cliente = ClienteFalso(self.db, uid=token.removeprefix("token-"), con_miembros=self.con_miembros)
            tabla = cliente.table
            cliente.table = lambda nombre: (self.consultas.append(nombre), tabla(nombre))[1]
            return cliente

        for modulo in MODULOS:
            parche = patch.object(modulo, "get_user_scoped_client", side_effect=cliente_de)
            parche.start()
            self.addCleanup(parche.stop)

        admin = ClienteFalso(self.db, admin=True, con_miembros=self.con_miembros)
        for modulo in (servicio_plantillas, servicio_estimaciones, servicio_historial):
            parche = patch.object(modulo, "supabase_admin", admin)
            parche.start()
            self.addCleanup(parche.stop)

        self.propietario = self.usuario("propietario")
        self.editor = self.usuario("editor")
        self.lector = self.usuario("lector")
        self.ajeno = self.usuario("ajeno")

        # Proyecto con dos partidas de la plantilla (faenas con 1 gl, radier sin cantidad).
        self.proyecto = servicio_proyectos.crear_proyecto(self.propietario, datos_proyecto())
        self.pid = self.proyecto["id"]
        self.agregar(self.pid, self.editor, "editor")
        self.agregar(self.pid, self.lector, "lector")
        servicio_partidas_proyecto.editar(self.propietario, self.pid, self.partidas()[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 20}))

    def usuario(self, nombre):
        usuario = UsuarioActual(id=uuid4(), email=f"{nombre}@x.cl", access_token="")
        usuario.access_token = f"token-{usuario.id}"
        return usuario

    def agregar(self, proyecto_id, usuario, rol):
        self.db["proyecto_miembros"].append({
            "id": str(uuid4()), "proyecto_id": proyecto_id, "usuario_id": str(usuario.id), "rol": rol,
        })

    def partidas(self, proyecto_id=None):
        return sorted((f for f in self.db["proyecto_partidas"] if f["proyecto_id"] == (proyecto_id or self.pid)),
                      key=lambda f: f["orden"])

    def escrituras(self, usuario, proyecto_id=None):
        """Todas las operaciones que exigen ser propietario o editor."""
        pid = proyecto_id or self.pid
        # Se leen al ejecutar: cada operación cambia la lista de partidas.
        primera = lambda: self.partidas(pid)[0]["id"]
        ids = lambda: [f["id"] for f in self.partidas(pid)]
        return {
            "editar proyecto": lambda: servicio_proyectos.actualizar_proyecto(
                usuario, pid, ProyectoActualizar.model_validate({"nombre": "Otro nombre"})),
            "crear partida": lambda: servicio_partidas_proyecto.crear(
                usuario, pid, PartidaProyectoCrear.model_validate({"origen": "catalogo", "partida_id": self.radier["id"]})),
            "editar partida": lambda: servicio_partidas_proyecto.editar(
                usuario, pid, primera(), PartidaProyectoEditar.model_validate({"cantidad": 7})),
            "eliminar partida": lambda: servicio_partidas_proyecto.eliminar(usuario, pid, primera()),
            "ordenar partidas": lambda: servicio_partidas_proyecto.ordenar(
                usuario, pid, PartidasOrdenar(ids=list(reversed(ids())))),
            "aplicar plantilla": lambda: servicio_partidas_proyecto.aplicar_plantilla(
                usuario, pid, PlantillaAplicar(reemplazar=True)),
            "generar estimación": lambda: servicio_estimaciones.crear_estimacion(usuario, pid, None),
        }

    def lecturas(self, usuario, proyecto_id=None, estimacion_id=None):
        """Todas las operaciones que solo exigen pertenecer al proyecto."""
        pid = proyecto_id or self.pid
        lecturas = {
            "ver proyecto": lambda: servicio_proyectos.obtener_proyecto_por_id(usuario, pid),
            "ver partidas": lambda: servicio_partidas_proyecto.listar(usuario, pid),
            "listar estimaciones": lambda: servicio_estimaciones.listar_estimaciones(usuario, pid),
        }
        if estimacion_id:
            lecturas["ver estimación"] = lambda: servicio_estimaciones.obtener_estimacion(usuario, pid, estimacion_id)
        return lecturas

    def assert_estado(self, operaciones, codigo):
        for nombre, operacion in operaciones.items():
            with self.subTest(operacion=nombre):
                with self.assertRaises(HTTPException) as error:
                    operacion()
                self.assertEqual(error.exception.status_code, codigo)


class PermisosPorProyecto(_Base):

    # --- Propietario y editor -----------------------------------------------------------

    def test_propietario_puede_todo(self):
        self.assertEqual(self.proyecto["mi_rol"], RolProyecto.propietario)
        for nombre, operacion in self.escrituras(self.propietario).items():
            with self.subTest(operacion=nombre):
                operacion()
        self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.propietario, self.pid)["nombre"], "Otro nombre")

    def test_editor_puede_editar_y_generar(self):
        for nombre, operacion in self.escrituras(self.editor).items():
            with self.subTest(operacion=nombre):
                operacion()

        proyecto = servicio_proyectos.obtener_proyecto_por_id(self.editor, self.pid)
        self.assertEqual((proyecto["nombre"], proyecto["mi_rol"]), ("Otro nombre", RolProyecto.editor))
        # La estimación queda a nombre de quien la generó; el proyecto sigue siendo de su creador.
        self.assertEqual(self.db["estimaciones"][0]["usuario_id"], str(self.editor.id))
        self.assertEqual(proyecto["usuario_id"], str(self.propietario.id))

    # --- Lector ---------------------------------------------------------------------------

    def test_lector_puede_consultar(self):
        estimacion = servicio_estimaciones.crear_estimacion(self.propietario, self.pid, None)

        proyecto = servicio_proyectos.obtener_proyecto_por_id(self.lector, self.pid)
        self.assertEqual(proyecto["mi_rol"], RolProyecto.lector)
        self.assertEqual(proyecto["ultima_estimacion_id"], estimacion["id"])
        self.assertEqual(len(servicio_partidas_proyecto.listar(self.lector, self.pid)["partidas"]), 2)
        self.assertEqual([e["id"] for e in servicio_estimaciones.listar_estimaciones(self.lector, self.pid)],
                         [estimacion["id"]])
        self.assertEqual(servicio_estimaciones.obtener_estimacion(self.lector, self.pid, estimacion["id"]), estimacion)

    def test_lector_que_modifica_recibe_403(self):
        antes = copy.deepcopy(self.db)
        self.assert_estado(self.escrituras(self.lector), 403)
        self.assertEqual(self.db, antes)  # nada cambió

    # --- Sin membresía ----------------------------------------------------------------------

    def test_quien_no_pertenece_recibe_404(self):
        estimacion = servicio_estimaciones.crear_estimacion(self.propietario, self.pid, None)
        antes = copy.deepcopy(self.db)

        self.assert_estado(self.lecturas(self.ajeno, estimacion_id=estimacion["id"]), 404)
        self.assert_estado(self.escrituras(self.ajeno), 404)
        self.assertEqual(servicio_proyectos.obtener_proyectos(self.ajeno), [])
        self.assertEqual(self.db, antes)

    def test_proyecto_inexistente_404(self):
        self.assert_estado(self.lecturas(self.propietario, proyecto_id=str(uuid4())), 404)

    def test_quitar_la_membresia_quita_el_acceso(self):
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.editor.id)]
        self.assert_estado(self.lecturas(self.editor), 404)
        self.assert_estado(self.escrituras(self.editor), 404)

    # --- Un rol por proyecto ------------------------------------------------------------------

    def test_mismo_usuario_editor_en_un_proyecto_y_lector_en_otro(self):
        otro = servicio_proyectos.crear_proyecto(self.propietario, datos_proyecto(nombre="Otro"))
        self.agregar(otro["id"], self.editor, "lector")

        self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.editor, self.pid)["mi_rol"], RolProyecto.editor)
        self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.editor, otro["id"])["mi_rol"], RolProyecto.lector)

        servicio_partidas_proyecto.editar(self.editor, self.pid, self.partidas()[0]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 3}))
        self.assert_estado(self.escrituras(self.editor, otro["id"]), 403)
        for operacion in self.lecturas(self.editor, otro["id"]).values():
            operacion()

    def test_listado_trae_mi_rol_en_cada_proyecto(self):
        propio = servicio_proyectos.crear_proyecto(self.editor, datos_proyecto(nombre="Propio"))
        otro = servicio_proyectos.crear_proyecto(self.propietario, datos_proyecto(nombre="Otro"))
        self.agregar(otro["id"], self.editor, "lector")

        self.consultas.clear()
        lista = servicio_proyectos.obtener_proyectos(self.editor)
        self.assertEqual({p["id"]: p["mi_rol"] for p in lista}, {
            self.pid: RolProyecto.editor, otro["id"]: RolProyecto.lector, propio["id"]: RolProyecto.propietario,
        })
        # Una sola consulta de membresías, sin importar cuántos proyectos haya.
        self.assertEqual(self.consultas, ["proyectos", "proyecto_miembros", "versiones_precios"])
        for fila in lista:
            ProyectoRespuesta.model_validate(fila)

        # Quien solo tiene proyectos creados por él no consulta membresías.
        self.consultas.clear()
        servicio_proyectos.obtener_proyectos(self.propietario)
        self.assertEqual(self.consultas, ["proyectos", "versiones_precios"])

    # --- Compatibilidad -------------------------------------------------------------------------

    def test_creador_sin_membresia_sigue_siendo_propietario(self):
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]

        self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.propietario, self.pid)["mi_rol"],
                         RolProyecto.propietario)
        self.assertEqual(servicio_proyectos.obtener_proyectos(self.propietario)[0]["mi_rol"], RolProyecto.propietario)
        for nombre, operacion in self.escrituras(self.propietario).items():
            with self.subTest(operacion=nombre):
                operacion()

    def test_el_creador_no_consulta_membresias(self):
        self.consultas.clear()
        servicio_proyectos.leer_proyecto(self.propietario, self.pid, RolProyecto.propietario)
        self.assertEqual(self.consultas, ["proyectos"])

    def test_rol_desconocido_no_da_acceso(self):
        self.agregar(self.pid, self.ajeno, "administrador")
        self.assert_estado(self.lecturas(self.ajeno), 404)

    def test_leer_proyecto_valida_el_minimo(self):
        self.assertEqual(servicio_proyectos.leer_proyecto(self.lector, self.pid)["mi_rol"], RolProyecto.lector)
        self.assertEqual(servicio_proyectos.leer_proyecto(self.editor, self.pid, RolProyecto.editor)["id"], self.pid)
        self.assert_estado({
            "lector como editor": lambda: servicio_proyectos.leer_proyecto(self.lector, self.pid, RolProyecto.editor),
            "editor como propietario": lambda: servicio_proyectos.leer_proyecto(
                self.editor, self.pid, RolProyecto.propietario),
        }, 403)


class DependenciasYEndpoints(_Base):

    def api(self, usuario):
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_dependencias_por_rol(self):
        casos = [
            (permisos_proyecto.exigir_miembro_proyecto, {"propietario": 200, "editor": 200, "lector": 200, "ajeno": 404}),
            (permisos_proyecto.exigir_editor_proyecto, {"propietario": 200, "editor": 200, "lector": 403, "ajeno": 404}),
            (permisos_proyecto.exigir_propietario_proyecto, {"propietario": 200, "editor": 403, "lector": 403, "ajeno": 404}),
        ]
        for exigir, esperado in casos:
            for nombre, codigo in esperado.items():
                with self.subTest(dependencia=exigir, usuario=nombre):
                    usuario = getattr(self, nombre)
                    if codigo == 200:
                        proyecto = exigir(self.pid, usuario)
                        self.assertEqual((proyecto["id"], proyecto["mi_rol"].value), (self.pid, nombre))
                    else:
                        with self.assertRaises(HTTPException) as error:
                            exigir(self.pid, usuario)
                        self.assertEqual(error.exception.status_code, codigo)

    def test_sin_token_401(self):
        api = TestClient(app)
        ruta = f"/proyectos/{self.pid}"
        for metodo, url in (("get", ruta), ("put", ruta), ("get", ruta + "/partidas"), ("post", ruta + "/partidas"),
                            ("get", ruta + "/estimaciones"), ("post", ruta + "/estimaciones")):
            with self.subTest(metodo=metodo, url=url):
                self.assertEqual(getattr(api, metodo)(url).status_code, 401)

    def test_codigos_por_rol(self):
        ruta = f"/proyectos/{self.pid}"
        partida = self.partidas()[0]["id"]
        esperado = {"lector": (200, 403), "ajeno": (404, 404)}
        for nombre, (lectura, escritura) in esperado.items():
            api = self.api(getattr(self, nombre))
            with self.subTest(usuario=nombre):
                self.assertEqual(api.get(ruta).status_code, lectura)
                self.assertEqual(api.get(ruta + "/partidas").status_code, lectura)
                self.assertEqual(api.get(ruta + "/estimaciones").status_code, lectura)
                self.assertEqual(api.put(ruta, json={"nombre": "X"}).status_code, escritura)
                self.assertEqual(api.put(f"{ruta}/partidas/{partida}", json={"cantidad": 9}).status_code, escritura)
                self.assertEqual(api.delete(f"{ruta}/partidas/{partida}").status_code, escritura)
                self.assertEqual(api.post(ruta + "/partidas/aplicar-plantilla", json={"reemplazar": True}).status_code,
                                 escritura)
                self.assertEqual(api.post(ruta + "/estimaciones").status_code, escritura)

    def test_respuestas_con_mi_rol(self):
        api = self.api(self.editor)
        self.assertEqual(api.get(f"/proyectos/{self.pid}").json()["mi_rol"], "editor")
        self.assertEqual([p["mi_rol"] for p in api.get("/proyectos").json()], ["editor"])
        self.assertEqual(api.put(f"/proyectos/{self.pid}", json={"comuna": "Viña del Mar"}).json()["mi_rol"], "editor")
        self.assertEqual(api.post(f"/proyectos/{self.pid}/estimaciones").status_code, 201)

        creado = api.post("/proyectos", json=datos_proyecto(nombre="Nuevo").model_dump(mode="json"))
        self.assertEqual((creado.status_code, creado.json()["mi_rol"]), (201, "propietario"))


class SinLaMigracion003(_Base):
    """Mientras la 003 no esté aplicada, RLS solo deja ver cada proyecto a su creador."""

    con_miembros = False

    def test_el_creador_trabaja_igual_que_antes(self):
        for nombre, operacion in self.escrituras(self.propietario).items():
            with self.subTest(operacion=nombre):
                operacion()
        self.assertEqual(servicio_proyectos.obtener_proyectos(self.propietario)[0]["mi_rol"], RolProyecto.propietario)

    def test_un_miembro_que_no_es_el_creador_todavia_recibe_404(self):
        # RLS le oculta el proyecto: su membresía no alcanza hasta que la 003 cambie las políticas.
        for usuario in (self.editor, self.lector):
            self.assert_estado(self.lecturas(usuario), 404)
            self.assert_estado(self.escrituras(usuario), 404)
            self.assertEqual(servicio_proyectos.obtener_proyectos(usuario), [])


if __name__ == "__main__":
    unittest.main()
