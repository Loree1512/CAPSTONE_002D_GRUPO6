"""Roles globales: administrador y profesional. Solo rol_global = administrador administra.

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

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.autenticacion import RolGlobal, UsuarioActual  # noqa: E402
from app.services import servicio_perfiles  # noqa: E402
from test_partidas_proyecto import ClienteFalso  # noqa: E402

MIGRACION = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
             / "002_roles_permisos_auditoria.sql").read_text(encoding="utf-8")

EXIGENCIAS = (
    dependencias.exigir_editor_banco,
    dependencias.exigir_editor_configuracion,
    dependencias.exigir_editor_plantillas,
)


class _ClienteSinTabla:
    """Base sin la migración 002: PostgREST no conoce la tabla perfiles."""

    def table(self, _nombre):
        raise APIError({"code": "PGRST205", "message": "Could not find the table 'public.perfiles'",
                        "hint": None, "details": None})


class RolesGlobales(unittest.TestCase):

    def setUp(self):
        self.db = {"perfiles": [], "administradores_principales": []}
        self.tokens = []

        def cliente_de(token):
            self.tokens.append(token)
            return ClienteFalso(self.db, uid=token.removeprefix("token-"))

        parche = patch.object(servicio_perfiles, "get_user_scoped_client", side_effect=cliente_de)
        parche.start()
        self.addCleanup(parche.stop)

    def usuario(self, rol=None):
        usuario = UsuarioActual(id=uuid4(), email="u@x.cl", access_token="")
        usuario.access_token = f"token-{usuario.id}"
        if rol is not None:
            self.db["perfiles"].append({"id": str(usuario.id), "rol_global": rol,
                                        "acceso_configurado_at": "2026-01-01T00:00:00Z"})
        return usuario

    def assert_403(self, usuario):
        for exigir in EXIGENCIAS:
            with self.assertRaises(HTTPException) as error:
                exigir(usuario)
            self.assertEqual(error.exception.status_code, 403)

    def assert_administra(self, usuario):
        for exigir in EXIGENCIAS:
            self.assertIs(exigir(usuario), usuario)

    # --- Rol del perfil -------------------------------------------------------------

    def test_rol_del_perfil(self):
        self.assertEqual(servicio_perfiles.rol_global(self.usuario("administrador")), RolGlobal.administrador)
        self.assertEqual(servicio_perfiles.rol_global(self.usuario("profesional")), RolGlobal.profesional)

    def test_sin_perfil_es_profesional(self):
        self.assertEqual(servicio_perfiles.rol_global(self.usuario()), RolGlobal.profesional)

    def test_el_perfil_de_otro_no_da_rol(self):
        self.usuario("administrador")
        self.assertEqual(servicio_perfiles.rol_global(self.usuario("profesional")), RolGlobal.profesional)

    def test_lee_el_perfil_con_el_token_del_usuario(self):
        usuario = self.usuario("administrador")
        servicio_perfiles.rol_global(usuario)
        self.assertEqual(self.tokens, [usuario.access_token])
        self.assertFalse(hasattr(servicio_perfiles, "supabase_admin"))

    def test_sin_la_tabla_nadie_es_administrador(self):
        with patch.object(servicio_perfiles, "get_user_scoped_client", return_value=_ClienteSinTabla()):
            with self.assertLogs(servicio_perfiles.logger, level="WARNING"):
                self.assertEqual(servicio_perfiles.rol_global(self.usuario()), RolGlobal.profesional)

    # --- Banco, plantillas y configuración --------------------------------------------

    def test_administrador_administra(self):
        self.assert_administra(self.usuario("administrador"))

    def test_profesional_no_administra(self):
        self.assert_403(self.usuario("profesional"))
        self.assert_403(self.usuario())

    def test_sin_la_tabla_nadie_administra(self):
        with patch.object(servicio_perfiles, "get_user_scoped_client", return_value=_ClienteSinTabla()):
            with self.assertLogs(servicio_perfiles.logger, level="WARNING"):
                self.assert_403(self.usuario())

    # --- Endpoints --------------------------------------------------------------------

    def _api(self, usuario):
        app.dependency_overrides[dependencias.obtener_sesion] = lambda: usuario
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_yo_informa_el_rol_y_no_expone_el_token(self):
        usuario = self.usuario("administrador")
        respuesta = self._api(usuario).get("/autenticacion/yo")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {"id": str(usuario.id), "email": "u@x.cl", "rol_global": "administrador",
                                            "es_administrador_principal": False, "acceso_configurado": True,
                                            "nombre": None})

        respuesta = self._api(self.usuario()).get("/autenticacion/yo")
        self.assertEqual(respuesta.json()["rol_global"], "profesional")

    def test_yo_informa_el_nombre_del_perfil(self):
        usuario = self.usuario("profesional")
        self.db["perfiles"][-1]["nombre"] = "  Ángel González "
        self.assertEqual(self._api(usuario).get("/autenticacion/yo").json()["nombre"], "Ángel González")
        # Nombre vacío en el perfil: no se inventa uno.
        self.db["perfiles"][-1]["nombre"] = "   "
        self.assertIsNone(self._api(usuario).get("/autenticacion/yo").json()["nombre"])

    def test_yo_informa_si_es_principal(self):
        usuario = self.usuario("administrador")
        self.db["administradores_principales"].append({"perfil_id": str(usuario.id)})
        # Otro principal no cuenta: solo la fila propia.
        self.db["administradores_principales"].append({"perfil_id": str(uuid4())})
        self.assertTrue(self._api(usuario).get("/autenticacion/yo").json()["es_administrador_principal"])
        self.assertFalse(self._api(self.usuario("administrador")).get("/autenticacion/yo")
                         .json()["es_administrador_principal"])

    def test_sin_token_401(self):
        api = TestClient(app)
        self.assertEqual(api.get("/autenticacion/yo").status_code, 401)
        self.assertEqual(api.post("/banco/versiones", json={"version": "2026-T4"}).status_code, 401)

    def test_profesional_recibe_403_al_escribir(self):
        api = self._api(self.usuario("profesional"))
        self.assertEqual(api.post("/banco/versiones", json={"version": "2026-T4"}).status_code, 403)
        self.assertEqual(api.post("/plantillas", json={}).status_code, 403)
        self.assertEqual(api.put("/configuracion", json={}).status_code, 403)


class Migracion002(unittest.TestCase):

    def test_no_toca_las_politicas_existentes(self):
        self.assertNotIn("drop policy", MIGRACION.lower())
        tablas = set(re.findall(r"create policy[^;]*?\bon public\.(\w+)", MIGRACION, flags=re.S))
        self.assertEqual(tablas, {"perfiles", "proyecto_miembros", "historial_proyecto"})

    def test_no_modifica_tablas_ni_funciones_de_001(self):
        self.assertNotIn("drop table", MIGRACION.lower())
        self.assertNotIn("drop function", MIGRACION.lower())
        alteradas = set(re.findall(r"alter table public\.(\w+)", MIGRACION))
        self.assertEqual(alteradas, {"perfiles", "proyecto_miembros", "historial_proyecto"})
        funciones = set(re.findall(r"create or replace function public\.(\w+)", MIGRACION))
        self.assertEqual(funciones, {
            "crear_perfil_usuario", "proteger_miembros_proyecto", "agregar_propietario_proyecto",
            "rol_en_proyecto", "tiene_rol_proyecto", "es_administrador", "bloquear_cambios_historial",
        })

    def test_privilegios_explicitos_de_las_tablas_nuevas(self):
        service_role = {
            "perfiles": "select, insert, update",
            "proyecto_miembros": "select, insert, update, delete",
            "historial_proyecto": "select, insert",
        }
        for tabla, privilegios in service_role.items():
            self.assertIn(f"alter table public.{tabla} enable row level security", MIGRACION)
            self.assertIn(f"revoke all on public.{tabla} from public, anon, authenticated, service_role;", MIGRACION)
            # Lo único que se concede: lectura al usuario (con RLS) y lo justo al backend.
            concedido = re.findall(rf"grant ([\w, ]+) on public\.{tabla} to ([\w, ]+);", MIGRACION)
            self.assertEqual(concedido, [("select", "authenticated"), (privilegios, "service_role")])
        self.assertEqual(re.findall(r"for (insert|update|delete|all)\s+to authenticated", MIGRACION), [])
        self.assertNotRegex(MIGRACION, r"grant [^;]*\bto [^;]*\b(anon|public)\b")

    def test_funciones_con_security_definer_y_sin_acceso_publico(self):
        cuerpos = dict(re.findall(r"create or replace function public\.(\w+)\(.*?\)(.*?)\bas \$\$", MIGRACION, flags=re.S))
        for nombre, cabecera in cuerpos.items():
            self.assertIn("security definer", cabecera, nombre)
            self.assertIn("set search_path = ''", cabecera, nombre)
            self.assertRegex(MIGRACION, rf"revoke execute on function public\.{nombre}\([^)]*\) from public, anon\b", nombre)
        # Las de trigger no se ejecutan a mano.
        for nombre in ("crear_perfil_usuario", "agregar_propietario_proyecto",
                       "proteger_miembros_proyecto", "bloquear_cambios_historial"):
            self.assertIn(f"revoke execute on function public.{nombre}() from public, anon, authenticated;", MIGRACION)


if __name__ == "__main__":
    unittest.main()
