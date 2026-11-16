"""Miembros del proyecto: el propietario agrega, cambia y quita; todos los miembros consultan.

Cada cambio queda en historial_proyecto.

Ejecutar desde backend/:
    python -m pytest
"""

import copy
import os
from unittest.mock import patch
from urllib.parse import quote
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.miembro import MiembroAgregar, MiembroCambiarRol  # noqa: E402
from app.services import servicio_historial, servicio_miembros  # noqa: E402
from test_partidas_proyecto import ClienteFalso  # noqa: E402
from test_permisos_proyecto import _Base  # noqa: E402


class MiembrosDelProyecto(_Base):

    def setUp(self):
        super().setUp()
        self.nuevo = self.usuario("nuevo")
        self.db["historial_proyecto"] = []
        self.db["perfiles"] = [
            {"id": str(u.id), "email": u.email, "nombre": nombre, "rol_global": "profesional"}
            for u, nombre in ((self.propietario, "Paula Propietaria"), (self.editor, "Elías Editor"),
                              (self.lector, None), (self.ajeno, None), (self.nuevo, "Nora Nueva"))
        ]

        self.admin = ClienteFalso(self.db, admin=True, con_miembros=True)
        for modulo in (servicio_miembros, servicio_historial):
            parche = patch.object(modulo, "supabase_admin", self.admin)
            parche.start()
            self.addCleanup(parche.stop)

        self.ruta = f"/proyectos/{self.pid}/miembros"

    def api(self, usuario):
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def roles(self):
        return {m["usuario_id"]: m["rol"] for m in self.db["proyecto_miembros"] if m["proyecto_id"] == self.pid}

    def historial(self):
        return [{k: e[k] for k in ("accion", "entidad", "entidad_id", "valores_anteriores", "valores_nuevos")}
                for e in self.db["historial_proyecto"]]

    # --- Consultar ----------------------------------------------------------------------

    def test_propietario_lista_miembros(self):
        respuesta = self.api(self.propietario).get(self.ruta)
        self.assertEqual(respuesta.status_code, 200)
        # Propietario primero; el resto por rol y correo.
        self.assertEqual([(m["email"], m["nombre"], m["rol"]) for m in respuesta.json()], [
            ("propietario@x.cl", "Paula Propietaria", "propietario"),
            ("editor@x.cl", "Elías Editor", "editor"),
            ("lector@x.cl", None, "lector"),
        ])
        self.assertEqual(respuesta.json()[0]["usuario_id"], str(self.propietario.id))
        self.assertEqual(set(respuesta.json()[0]), {"usuario_id", "email", "nombre", "rol", "fecha_creacion"})

    def test_editor_y_lector_ven_la_lista(self):
        for usuario in (self.editor, self.lector):
            respuesta = self.api(usuario).get(self.ruta)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(len(respuesta.json()), 3)

    def test_quien_no_pertenece_no_ve_ni_modifica(self):
        api = self.api(self.ajeno)
        self.assertEqual(api.get(self.ruta).status_code, 404)
        self.assertEqual(api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": "lector"}).status_code, 404)
        self.assertEqual(api.put(f"{self.ruta}/{self.editor.id}", json={"rol": "lector"}).status_code, 404)
        self.assertEqual(api.delete(f"{self.ruta}/{self.editor.id}").status_code, 404)

    def test_sin_token_401(self):
        api = TestClient(app)
        self.assertEqual(api.get(self.ruta).status_code, 401)
        self.assertEqual(api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": "lector"}).status_code, 401)
        self.assertEqual(api.put(f"{self.ruta}/{self.editor.id}", json={"rol": "lector"}).status_code, 401)
        self.assertEqual(api.delete(f"{self.ruta}/{self.editor.id}").status_code, 401)

    def test_creador_sin_fila_aparece_como_propietario(self):
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]
        miembros = self.api(self.propietario).get(self.ruta).json()
        self.assertEqual([(m["email"], m["rol"]) for m in miembros][0], ("propietario@x.cl", "propietario"))
        self.assertEqual(len(miembros), 3)

    def test_solo_muestra_los_miembros_de_ese_proyecto(self):
        self.db["proyecto_miembros"].append(
            {"id": str(uuid4()), "proyecto_id": str(uuid4()), "usuario_id": str(self.nuevo.id), "rol": "editor"})
        self.assertEqual(len(self.api(self.propietario).get(self.ruta).json()), 3)

    # --- Agregar ------------------------------------------------------------------------

    def test_propietario_agrega_editor(self):
        respuesta = self.api(self.propietario).post(self.ruta, json={"email": "nuevo@x.cl", "rol": "editor"})
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(
            {k: respuesta.json()[k] for k in ("usuario_id", "email", "nombre", "rol")},
            {"usuario_id": str(self.nuevo.id), "email": "nuevo@x.cl", "nombre": "Nora Nueva", "rol": "editor"},
        )

        fila = next(m for m in self.db["proyecto_miembros"] if m["usuario_id"] == str(self.nuevo.id))
        self.assertEqual((fila["proyecto_id"], fila["rol"], fila["agregado_por"]),
                         (self.pid, "editor", str(self.propietario.id)))
        # Ya puede trabajar en el proyecto.
        self.assertEqual(self.api(self.nuevo).put(f"/proyectos/{self.pid}", json={"nombre": "X"}).status_code, 200)

    def test_propietario_agrega_lector(self):
        # El correo se compara sin mayúsculas ni espacios sobrantes.
        respuesta = self.api(self.propietario).post(self.ruta, json={"email": "Nuevo@X.cl", "rol": "lector"})
        self.assertEqual((respuesta.status_code, respuesta.json()["rol"]), (201, "lector"))
        self.assertEqual(self.roles()[str(self.nuevo.id)], "lector")

        api = self.api(self.nuevo)
        self.assertEqual(api.get(f"/proyectos/{self.pid}").json()["mi_rol"], "lector")
        self.assertEqual(api.put(f"/proyectos/{self.pid}", json={"nombre": "X"}).status_code, 403)

    def test_correo_sin_distinguir_mayusculas(self):
        # El perfil guarda el correo con mayúsculas: no se depende de cómo lo almacene Supabase.
        perfil = next(p for p in self.db["perfiles"] if p["id"] == str(self.nuevo.id))
        perfil["email"] = "Nora.Nueva@Ejemplo.CL"
        api = self.api(self.propietario)

        for escrito in ("nora.nueva@ejemplo.cl", "NORA.NUEVA@EJEMPLO.CL", "  Nora.nueva@Ejemplo.cl "):
            with self.subTest(escrito=escrito):
                respuesta = api.post(self.ruta, json={"email": escrito, "rol": "lector"})
                self.assertEqual((respuesta.status_code, respuesta.json().get("usuario_id")), (201, str(self.nuevo.id)))
                # Se responde y se registra el correo tal como está en el perfil.
                self.assertEqual(respuesta.json()["email"], "Nora.Nueva@Ejemplo.CL")
                self.assertEqual(self.db["historial_proyecto"][-1]["valores_nuevos"]["email"], "Nora.Nueva@Ejemplo.CL")
                self.assertEqual(api.delete(f"{self.ruta}/{self.nuevo.id}").status_code, 204)

    def test_el_correo_es_literal_no_un_patron(self):
        # _ % y * son comodines de ilike: no deben encontrar a otro usuario.
        perfil = lambda: next(p for p in self.db["perfiles"] if p["id"] == str(self.nuevo.id))
        perfil()["email"] = "anaxperez@x.cl"

        for escrito in ("ana_perez@x.cl", "ana%@x.cl", "*@x.cl", "ana*@x.cl"):
            with self.subTest(escrito=escrito):
                datos = MiembroAgregar(email=escrito, rol="lector")
                with self.assertRaises(HTTPException) as error:
                    servicio_miembros.agregar(self.propietario, self.proyecto, datos)
                self.assertEqual(error.exception.status_code, 404)
        self.assertNotIn(str(self.nuevo.id), self.roles())

        # Un correo que sí lleva guion bajo se encuentra, también con otras mayúsculas.
        perfil()["email"] = "Ana_Perez@x.cl"
        respuesta = self.api(self.propietario).post(self.ruta, json={"email": "ana_perez@X.cl", "rol": "lector"})
        self.assertEqual((respuesta.status_code, respuesta.json().get("usuario_id")), (201, str(self.nuevo.id)))

    def test_editor_y_lector_no_modifican_miembros(self):
        antes = copy.deepcopy(self.db)
        for usuario in (self.editor, self.lector):
            api = self.api(usuario)
            self.assertEqual(api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": "lector"}).status_code, 403)
            self.assertEqual(api.put(f"{self.ruta}/{self.lector.id}", json={"rol": "editor"}).status_code, 403)
            self.assertEqual(api.delete(f"{self.ruta}/{self.editor.id}").status_code, 403)
        self.assertEqual(self.db, antes)
        # El service role no se usó: el permiso se comprueba antes.
        self.assertEqual(self.admin.rpcs, [])

    def test_usuario_inexistente(self):
        respuesta = self.api(self.propietario).post(self.ruta, json={"email": "nadie@x.cl", "rol": "editor"})
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(respuesta.json()["detail"], "No hay un usuario registrado con ese correo.")
        self.assertEqual(self.historial(), [])

    def test_usuario_duplicado(self):
        api = self.api(self.propietario)
        # Ya es miembro, con el mismo rol o con otro.
        self.assertEqual(api.post(self.ruta, json={"email": "editor@x.cl", "rol": "editor"}).status_code, 409)
        self.assertEqual(api.post(self.ruta, json={"email": "editor@x.cl", "rol": "lector"}).status_code, 409)
        # El propietario tampoco se agrega a sí mismo, ni siquiera si le falta la fila.
        self.assertEqual(api.post(self.ruta, json={"email": "propietario@x.cl", "rol": "lector"}).status_code, 409)
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]
        self.assertEqual(api.post(self.ruta, json={"email": "propietario@x.cl", "rol": "lector"}).status_code, 409)

        self.assertEqual(self.roles(), {str(self.editor.id): "editor", str(self.lector.id): "lector"})
        self.assertEqual(self.historial(), [])

    def test_rol_invalido(self):
        api = self.api(self.propietario)
        for rol in ("propietario", "administrador", "", None):
            with self.subTest(rol=rol):
                self.assertEqual(api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": rol}).status_code, 422)
                self.assertEqual(api.put(f"{self.ruta}/{self.editor.id}", json={"rol": rol}).status_code, 422)
        self.assertEqual(api.post(self.ruta, json={"email": "no-es-correo", "rol": "lector"}).status_code, 422)
        self.assertEqual(api.post(self.ruta, json={"rol": "lector"}).status_code, 422)
        self.assertNotIn(str(self.nuevo.id), self.roles())
        self.assertEqual(self.historial(), [])

    # --- Cambiar permiso ------------------------------------------------------------------

    def test_cambio_entre_editor_y_lector(self):
        api = self.api(self.propietario)

        respuesta = api.put(f"{self.ruta}/{self.editor.id}", json={"rol": "lector"})
        self.assertEqual((respuesta.status_code, respuesta.json()["rol"], respuesta.json()["email"]),
                         (200, "lector", "editor@x.cl"))
        self.assertEqual(self.api(self.editor).put(f"/proyectos/{self.pid}", json={"nombre": "X"}).status_code, 403)

        respuesta = self.api(self.propietario).put(f"{self.ruta}/{self.editor.id}", json={"rol": "editor"})
        self.assertEqual((respuesta.status_code, respuesta.json()["rol"]), (200, "editor"))
        self.assertEqual(self.api(self.editor).put(f"/proyectos/{self.pid}", json={"nombre": "X"}).status_code, 200)

        # Dejar el mismo permiso no cambia nada ni deja registro.
        respuesta = self.api(self.propietario).put(f"{self.ruta}/{self.editor.id}", json={"rol": "editor"})
        self.assertEqual((respuesta.status_code, respuesta.json()["rol"]), (200, "editor"))
        self.assertEqual([e["accion"] for e in self.historial() if e["entidad"] == "miembro"],
                         ["miembro_rol_cambiado", "miembro_rol_cambiado"])

    def test_no_se_convierte_a_nadie_en_propietario(self):
        api = self.api(self.propietario)
        self.assertEqual(api.put(f"{self.ruta}/{self.editor.id}", json={"rol": "propietario"}).status_code, 422)
        self.assertEqual(self.roles()[str(self.editor.id)], "editor")

    def test_el_propietario_no_cambia_de_permiso(self):
        api = self.api(self.propietario)
        self.assertEqual(api.put(f"{self.ruta}/{self.propietario.id}", json={"rol": "editor"}).status_code, 409)
        self.assertEqual(self.roles()[str(self.propietario.id)], "propietario")

        # Tampoco si le falta la fila de miembro.
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]
        self.assertEqual(api.put(f"{self.ruta}/{self.propietario.id}", json={"rol": "editor"}).status_code, 409)
        self.assertEqual(self.historial(), [])

    def test_cambiar_o_quitar_a_quien_no_es_miembro(self):
        api = self.api(self.propietario)
        self.assertEqual(api.put(f"{self.ruta}/{self.nuevo.id}", json={"rol": "editor"}).status_code, 404)
        self.assertEqual(api.delete(f"{self.ruta}/{self.nuevo.id}").status_code, 404)
        self.assertEqual(api.delete(f"{self.ruta}/no-es-uuid").status_code, 422)

    def test_miembro_de_otro_proyecto_no_se_toca(self):
        otro = str(uuid4())
        self.db["proyecto_miembros"].append(
            {"id": str(uuid4()), "proyecto_id": otro, "usuario_id": str(self.nuevo.id), "rol": "editor"})
        api = self.api(self.propietario)
        self.assertEqual(api.put(f"{self.ruta}/{self.nuevo.id}", json={"rol": "lector"}).status_code, 404)
        self.assertEqual(api.delete(f"{self.ruta}/{self.nuevo.id}").status_code, 404)
        self.assertEqual(self.db["proyecto_miembros"][-1]["rol"], "editor")

    # --- Quitar -----------------------------------------------------------------------------

    def test_quitar_miembro(self):
        respuesta = self.api(self.propietario).delete(f"{self.ruta}/{self.editor.id}")
        self.assertEqual((respuesta.status_code, respuesta.content), (204, b""))
        self.assertNotIn(str(self.editor.id), self.roles())

        # Pierde el acceso; los demás no cambian.
        self.assertEqual(self.api(self.editor).get(f"/proyectos/{self.pid}").status_code, 404)
        self.assertEqual(self.roles(), {str(self.propietario.id): "propietario", str(self.lector.id): "lector"})
        # Se puede volver a agregar.
        self.assertEqual(
            self.api(self.propietario).post(self.ruta, json={"email": "editor@x.cl", "rol": "lector"}).status_code, 201)

    def test_el_propietario_no_se_quita(self):
        api = self.api(self.propietario)
        self.assertEqual(api.delete(f"{self.ruta}/{self.propietario.id}").status_code, 409)
        self.assertEqual(self.roles()[str(self.propietario.id)], "propietario")
        self.assertEqual(self.api(self.propietario).get(f"/proyectos/{self.pid}").status_code, 200)
        self.assertEqual(self.historial(), [])

    # --- Historial ----------------------------------------------------------------------------

    def test_eventos_en_el_historial(self):
        api = self.api(self.propietario)
        api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": "lector"})
        api.put(f"{self.ruta}/{self.nuevo.id}", json={"rol": "editor"})
        api.delete(f"{self.ruta}/{self.nuevo.id}")

        nuevo = str(self.nuevo.id)
        self.assertEqual(self.historial(), [
            {"accion": "miembro_agregado", "entidad": "miembro", "entidad_id": nuevo,
             "valores_anteriores": None,
             "valores_nuevos": {"usuario_id": nuevo, "email": "nuevo@x.cl", "rol": "lector"}},
            {"accion": "miembro_rol_cambiado", "entidad": "miembro", "entidad_id": nuevo,
             "valores_anteriores": {"rol": "lector"},
             "valores_nuevos": {"rol": "editor", "email": "nuevo@x.cl"}},
            {"accion": "miembro_eliminado", "entidad": "miembro", "entidad_id": nuevo,
             "valores_anteriores": {"usuario_id": nuevo, "email": "nuevo@x.cl", "rol": "editor"},
             "valores_nuevos": None},
        ])
        # Quién lo hizo, en qué proyecto y por dónde.
        for evento in self.db["historial_proyecto"]:
            self.assertEqual(
                (evento["proyecto_id"], evento["usuario_id"], evento["usuario_email"], evento["origen"]),
                (self.pid, str(self.propietario.id), "propietario@x.cl", "rpc"),
            )

    def test_si_falla_el_historial_no_queda_el_cambio(self):
        antes = copy.deepcopy(self.db)
        self.admin.falla_historial = True
        cambios = {
            "agregar": lambda: servicio_miembros.agregar(
                self.propietario, self.proyecto, MiembroAgregar(email="nuevo@x.cl", rol="lector")),
            "cambiar": lambda: servicio_miembros.cambiar_rol(
                self.propietario, self.proyecto, self.editor.id, MiembroCambiarRol(rol="lector")),
            "quitar": lambda: servicio_miembros.quitar(self.propietario, self.proyecto, self.lector.id),
        }
        for nombre, cambio in cambios.items():
            with self.subTest(cambio=nombre):
                # No es un error previsto: se ve como 500, no como un cambio a medias.
                with self.assertRaises(APIError):
                    cambio()
                self.assertEqual(self.db, antes)

    def test_la_tabla_solo_se_escribe_con_las_rpc(self):
        # Ni siquiera con service role (003): sin RPC no hay cambio de membresía.
        fila = {"proyecto_id": self.pid, "usuario_id": str(self.nuevo.id), "rol": "editor"}
        intentos = {
            "insert": lambda: self.admin.table("proyecto_miembros").insert(fila).execute(),
            "update": lambda: self.admin.table("proyecto_miembros").update({"rol": "editor"})
                                  .eq("usuario_id", str(self.lector.id)).execute(),
            "delete": lambda: self.admin.table("proyecto_miembros").delete()
                                  .eq("usuario_id", str(self.lector.id)).execute(),
        }
        for nombre, intento in intentos.items():
            with self.subTest(intento=nombre):
                with self.assertRaises(APIError) as error:
                    intento()
                self.assertEqual(error.exception.code, "42501")

        api = self.api(self.propietario)
        api.post(self.ruta, json={"email": "nuevo@x.cl", "rol": "editor"})
        api.put(f"{self.ruta}/{self.nuevo.id}", json={"rol": "lector"})
        api.delete(f"{self.ruta}/{self.nuevo.id}")
        self.assertEqual([nombre for nombre, _ in self.admin.rpcs], [
            "agregar_miembro_proyecto", "cambiar_rol_miembro_proyecto", "quitar_miembro_proyecto",
        ])
        # El solicitante viaja desde el token validado, no desde el cuerpo de la petición.
        self.assertTrue(all(p["p_solicitante_id"] == str(self.propietario.id) for _, p in self.admin.rpcs))

    def test_la_rpc_vuelve_a_comprobar_al_propietario(self):
        # Aunque el servicio se llamara sin pasar por el router, la RPC no deja pasar a otro.
        for usuario, codigo in ((self.editor, 403), (self.lector, 403), (self.ajeno, 404)):
            with self.subTest(usuario=usuario.email):
                with self.assertRaises(HTTPException) as error:
                    servicio_miembros.agregar(usuario, self.proyecto, MiembroAgregar(email="nuevo@x.cl", rol="lector"))
                self.assertEqual(error.exception.status_code, codigo)
        self.assertNotIn(str(self.nuevo.id), self.roles())
        self.assertEqual(self.historial(), [])

    def test_historial_desde_el_backend_no_interrumpe_la_operacion(self):
        # Para los eventos que el backend registra aparte (no los de miembros).
        def falla(*_a, **_k):
            raise APIError({"code": "XX000", "message": "sin conexión", "hint": None, "details": None})

        with patch.object(servicio_historial, "supabase_admin") as admin:
            admin.table.side_effect = falla
            with self.assertLogs(servicio_historial.logger, level="ERROR"):
                servicio_historial.registrar(self.propietario, self.pid, "proyecto_modificado", "proyecto", self.pid)

        servicio_historial.registrar(self.propietario, self.pid, "proyecto_modificado", "proyecto", self.pid,
                                     valores_nuevos={"nombre": "X"})
        evento = self.db["historial_proyecto"][-1]
        self.assertEqual((evento["accion"], evento["usuario_email"], evento["origen"]),
                         ("proyecto_modificado", "propietario@x.cl", "api"))

    # --- Candidatos ---------------------------------------------------------------------------

    def candidatos(self, usuario=None, consulta=""):
        return self.api(usuario or self.propietario).get(f"{self.ruta}/candidatos{consulta}")

    def test_candidatos_excluye_propietario_y_miembros(self):
        respuesta = self.candidatos()
        self.assertEqual(respuesta.status_code, 200)
        # Propietario, editor y lector ya están; quedan el ajeno y el nuevo, por nombre o correo.
        self.assertEqual(respuesta.json(), [
            {"usuario_id": str(self.ajeno.id), "nombre": None, "email": "ajeno@x.cl"},
            {"usuario_id": str(self.nuevo.id), "nombre": "Nora Nueva", "email": "nuevo@x.cl"},
        ])

    def test_creador_sin_fila_tampoco_es_candidato(self):
        self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"]
                                        if m["usuario_id"] != str(self.propietario.id)]
        ids = [c["usuario_id"] for c in self.candidatos().json()]
        self.assertNotIn(str(self.propietario.id), ids)

    def test_candidatos_de_otro_proyecto_siguen_disponibles(self):
        self.db["proyecto_miembros"].append(
            {"id": str(uuid4()), "proyecto_id": str(uuid4()), "usuario_id": str(self.nuevo.id), "rol": "editor"})
        self.assertIn(str(self.nuevo.id), [c["usuario_id"] for c in self.candidatos().json()])

    def test_buscar_por_nombre_o_correo_sin_mayusculas(self):
        for consulta, esperado in (("?buscar=NORA", ["nuevo@x.cl"]), ("?buscar=Ajeno@X", ["ajeno@x.cl"]),
                                   ("?buscar=%20nueva%20", ["nuevo@x.cl"]), ("?buscar=x.cl", ["ajeno@x.cl", "nuevo@x.cl"]),
                                   ("?buscar=nadie", []), ("?buscar=", ["ajeno@x.cl", "nuevo@x.cl"])):
            with self.subTest(consulta=consulta):
                self.assertEqual([c["email"] for c in self.candidatos(consulta=consulta).json()], esperado)

    def test_buscar_es_literal(self):
        # Ni comodines ni sintaxis de filtros de PostgREST.
        for texto in ("%", "*", "_", ",email.neq.x", ")"):
            with self.subTest(texto=texto):
                self.assertEqual(self.candidatos(consulta=f"?buscar={quote(texto)}").json(), [])
        self.assertEqual(self.candidatos(consulta="?buscar=" + "x" * 101).status_code, 422)

    def test_candidatos_ordenados_y_limitados(self):
        self.db["perfiles"] += [{"id": str(uuid4()), "email": f"u{n:02d}@x.cl", "nombre": None} for n in range(30)]
        self.db["perfiles"].append({"id": str(uuid4()), "email": "zeta@x.cl", "nombre": "aurora"})
        # Sin correo no se puede agregar: no se ofrece.
        self.db["perfiles"].append({"id": str(uuid4()), "email": None, "nombre": "Sin correo"})
        candidatos = self.candidatos().json()
        self.assertEqual(len(candidatos), servicio_miembros.LIMITE_CANDIDATOS)
        claves = [(c["nombre"] or c["email"]).casefold() for c in candidatos]
        self.assertEqual(claves, sorted(claves))
        self.assertEqual(candidatos[1]["nombre"], "aurora")
        self.assertNotIn("Sin correo", [c["nombre"] for c in candidatos])

    def test_agregado_deja_de_ser_candidato(self):
        self.api(self.propietario).post(self.ruta, json={"email": "nuevo@x.cl", "rol": "lector"})
        self.assertEqual([c["email"] for c in self.candidatos().json()], ["ajeno@x.cl"])

    def test_candidatos_solo_para_el_propietario(self):
        self.assertEqual(self.candidatos(self.editor).status_code, 403)
        self.assertEqual(self.candidatos(self.lector).status_code, 403)
        self.assertEqual(self.candidatos(self.ajeno).status_code, 404)
        app.dependency_overrides.clear()
        self.assertEqual(TestClient(app).get(f"{self.ruta}/candidatos").status_code, 401)

    def test_sin_permiso_no_se_leen_perfiles(self):
        # El service role se usa solo después de confirmar al propietario.
        with patch.object(servicio_miembros, "candidatos") as candidatos:
            for usuario in (self.editor, self.lector, self.ajeno):
                self.candidatos(usuario)
        candidatos.assert_not_called()


del _Base  # la base no se ejecuta como prueba en este módulo
