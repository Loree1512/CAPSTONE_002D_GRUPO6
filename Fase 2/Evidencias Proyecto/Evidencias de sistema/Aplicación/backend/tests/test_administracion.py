"""Panel global de usuarios: listar, invitar y promover a administrador con aprobación 3/3.

El cliente falso reproduce las RPC de 005_administracion_usuarios.sql; Supabase Auth
se reemplaza por un falso. Las pruebas nunca salen a la red.

Ejecutar desde backend/:
    python -m pytest
"""

import contextlib
import copy
import logging
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi.testclient import TestClient  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402
from supabase_auth.errors import AuthApiError, AuthRetryableError  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.autenticacion import UsuarioActual  # noqa: E402
from app.services import (  # noqa: E402
    servicio_administracion, servicio_autenticacion, servicio_perfiles, servicio_proyectos,
)
from test_partidas_proyecto import ClienteFalso, _ahora, _error  # noqa: E402

MIGRACIONES = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
M005 = (MIGRACIONES / "005_administracion_usuarios.sql").read_text(encoding="utf-8")

ENLACE = "https://ejemplo.supabase.co/auth/v1/verify?type=invite&token=ENLACE-SECRETO"


# --- Supabase Auth falso -------------------------------------------------------------

class _AuthAdminFalso:
    """Imita a GoTrue: invitar a una cuenta existente sin confirmar reemplaza su token
    (el enlace anterior deja de servir); a una confirmada, 422 email_exists. Abrir un
    enlace confirma la cuenta (y le pone una contraseña aleatoria), sin tocar el perfil."""

    def __init__(self, db):
        self.db = db
        self.llamadas = []
        self.falla = None
        self.confirmados = set()
        # Contraseñas que Auth aceptó, por id. Nunca deben aparecer en db ni en logs.
        self.contrasenas = {}
        self.emitidos = 0
        # Enlace válido por correo: solo el último emitido.
        self.vigente = {}

    def _cuenta(self, email):
        return next((p for p in self.db["perfiles"] if (p["email"] or "").lower() == email.lower()), None)

    def _invitar(self, email):
        if self.falla:
            raise self.falla
        perfil = self._cuenta(email)
        if perfil is None:
            usuario = SimpleNamespace(id=uuid4(), email=email)
            # Trigger (002/008): profesional, sin nombre y con el acceso pendiente.
            self.db["perfiles"].append({"id": str(usuario.id), "email": email, "nombre": None,
                                        "rol_global": "profesional", "fecha_creacion": _ahora(),
                                        "acceso_configurado_at": None})
        elif perfil["id"] in self.confirmados:
            raise AuthApiError("A user with this email address has already been registered", 422, "email_exists")
        else:
            usuario = SimpleNamespace(id=perfil["id"], email=email)
        self.emitidos += 1
        self.vigente[email] = f"{ENLACE}-{self.emitidos}"
        return usuario

    def _recuperar(self, email):
        if self.falla:
            raise self.falla
        perfil = self._cuenta(email)
        if perfil is None:
            raise AuthApiError("User not found", 404, "user_not_found")
        self.emitidos += 1
        self.vigente[email] = f"{ENLACE}-recuperacion-{self.emitidos}"
        return SimpleNamespace(id=perfil["id"], email=email)

    def generate_link(self, params):
        self.llamadas.append(("generate_link", copy.deepcopy(params)))
        if params["type"] == "recovery":
            usuario = self._recuperar(params["email"])
        else:
            usuario = self._invitar(params["email"])
        return SimpleNamespace(user=usuario, properties=SimpleNamespace(action_link=self.vigente[params["email"]]))

    def reset_password_for_email(self, email, opciones=None):
        self.llamadas.append(("reset_password_for_email", email, copy.deepcopy(opciones)))
        self._recuperar(email)

    def abrir_enlace(self, email):
        """Lo que hace /verify: confirma la cuenta y la sesión queda válida. El perfil no cambia."""
        perfil = self._cuenta(email)
        self.confirmados.add(perfil["id"])
        self.vigente.pop(email, None)

    def update_user_by_id(self, uid, atributos):
        if self.falla:
            raise self.falla
        self.contrasenas[str(uid)] = atributos["password"]

    def invite_user_by_email(self, email, opciones=None):
        self.llamadas.append(("invite_user_by_email", email, copy.deepcopy(opciones)))
        return SimpleNamespace(user=self._invitar(email))

    def get_user_by_id(self, uid):
        if self.falla:
            raise self.falla
        perfil = next((p for p in self.db["perfiles"] if p["id"] == str(uid)), None)
        if perfil is None:
            raise AuthApiError("User not found", 404, "user_not_found")
        confirmado = "2026-10-01" if perfil["id"] in self.confirmados else None
        return SimpleNamespace(user=SimpleNamespace(id=perfil["id"], email=perfil["email"],
                                                    email_confirmed_at=confirmado, confirmed_at=None))

    def list_users(self, page=None, per_page=None):
        if self.falla:
            raise self.falla
        return [SimpleNamespace(id=p["id"], email_confirmed_at="2026-10-01" if p["id"] in self.confirmados else None,
                                confirmed_at=None)
                for p in self.db["perfiles"]]


class ClienteAdministracion(ClienteFalso):
    """Service role con las RPC de la 005: cada una en una transacción."""

    def __init__(self, db):
        super().__init__(db, admin=True)
        admin = _AuthAdminFalso(db)
        self.auth = SimpleNamespace(admin=admin, reset_password_for_email=admin.reset_password_for_email)

    def _perfil(self, usuario_id):
        return next((p for p in self.db["perfiles"] if p["id"] == str(usuario_id)), None)

    def _auditar(self, accion, actor, objetivo, entidad, entidad_id, detalle):
        self.db["auditoria_administracion"].append({
            "id": str(uuid4()), "accion": accion, "actor_id": actor, "usuario_objetivo_id": objetivo,
            "entidad": entidad, "entidad_id": entidad_id, "detalle": detalle, "origen": "rpc", "fecha": _ahora(),
        })

    def _exigir_admin(self, actor):
        perfil = self._perfil(actor)
        if not perfil or perfil["rol_global"] != "administrador":
            raise _error("42501", "Solo un administrador puede realizar esta acción.")

    def _principales(self):
        return [a["perfil_id"] for a in self.db["administradores_principales"]]

    def _rpc_registrar_usuario_creado(self, p_actor_id, p_usuario_id, p_nombre, p_modo):
        def operacion():
            self._exigir_admin(p_actor_id)
            perfil = self._perfil(p_usuario_id)
            if perfil is None:
                raise _error("P0002", "El usuario no existe.")
            perfil["nombre"] = (p_nombre or "").strip() or None
            self._auditar("usuario_creado", p_actor_id, p_usuario_id, "perfil", p_usuario_id,
                          {"email": perfil["email"], "nombre": perfil["nombre"], "rol_global": perfil["rol_global"],
                           "modo": p_modo})
            return copy.deepcopy(perfil)
        return self._transaccion(operacion)

    def _rpc_completar_acceso(self, p_usuario_id):
        def operacion():
            perfil = self._perfil(p_usuario_id)
            if perfil is None:
                raise _error("P0002", "El usuario no existe.")
            if perfil.get("acceso_configurado_at") is None:
                perfil["acceso_configurado_at"] = _ahora()
                self._auditar("acceso_configurado", p_usuario_id, p_usuario_id, "perfil", p_usuario_id,
                              {"email": perfil["email"]})
            return perfil["acceso_configurado_at"]
        return self._transaccion(operacion)

    def _rpc_registrar_invitacion_renovada(self, p_actor_id, p_usuario_id, p_modo):
        def operacion():
            self._exigir_admin(p_actor_id)
            perfil = self._perfil(p_usuario_id)
            if perfil is None:
                raise _error("P0002", "El usuario no existe.")
            self._auditar("invitacion_renovada", p_actor_id, p_usuario_id, "perfil", p_usuario_id,
                          {"email": perfil["email"], "modo": p_modo})
        return self._transaccion(operacion)

    def _rpc_solicitar_administrador(self, p_actor_id, p_usuario_id):
        def operacion():
            self._exigir_admin(p_actor_id)
            perfil = self._perfil(p_usuario_id)
            if perfil is None:
                raise _error("P0002", "El usuario no existe.")
            if perfil["rol_global"] == "administrador":
                raise _error("55000", "El usuario ya es administrador.")
            if any(s["usuario_id"] == p_usuario_id and s["estado"] == "pendiente"
                   for s in self.db["solicitudes_administrador"]):
                raise _error("23505", "Ya hay una solicitud pendiente para este usuario.")
            fila = {"id": str(uuid4()), "usuario_id": p_usuario_id, "solicitado_por": p_actor_id,
                    "estado": "pendiente", "fecha_creacion": _ahora(), "fecha_resolucion": None}
            self.db["solicitudes_administrador"].append(fila)
            self._auditar("solicitud_administrador_creada", p_actor_id, p_usuario_id,
                          "solicitud_administrador", fila["id"], {"email": perfil["email"]})
            return copy.deepcopy(fila)
        return self._transaccion(operacion)

    def _rpc_aprobar_solicitud_administrador(self, p_actor_id, p_solicitud_id):
        def operacion():
            solicitud = next((s for s in self.db["solicitudes_administrador"] if s["id"] == p_solicitud_id), None)
            if solicitud is None:
                raise _error("P0002", "La solicitud no existe.")
            if solicitud["estado"] != "pendiente":
                raise _error("55000", "La solicitud ya fue completada.")
            if p_actor_id == solicitud["usuario_id"] or p_actor_id not in self._principales():
                raise _error("42501", "Solo los administradores principales aprueban promociones.")
            if len(self._principales()) != 3:
                raise _error("55000", "El grupo de administradores principales debe tener tres integrantes.")
            if any(a["solicitud_id"] == p_solicitud_id and a["administrador_id"] == p_actor_id
                   for a in self.db["aprobaciones_administrador"]):
                raise _error("23505", "Ya aprobaste esta solicitud.")
            self.db["aprobaciones_administrador"].append({
                "id": str(uuid4()), "solicitud_id": p_solicitud_id, "administrador_id": p_actor_id, "fecha": _ahora(),
            })
            total = sum(a["solicitud_id"] == p_solicitud_id for a in self.db["aprobaciones_administrador"])
            self._auditar("administrador_aprobado", p_actor_id, solicitud["usuario_id"], "solicitud_administrador",
                          p_solicitud_id, {"aprobaciones": total, "requeridas": 3})
            if total >= 3:
                self._perfil(solicitud["usuario_id"])["rol_global"] = "administrador"
                solicitud.update(estado="aprobada", fecha_resolucion=_ahora())
                self._auditar("usuario_promovido_administrador", p_actor_id, solicitud["usuario_id"], "perfil",
                              solicitud["usuario_id"], {"rol_anterior": "profesional", "rol_nuevo": "administrador"})
            return copy.deepcopy(solicitud)
        return self._transaccion(operacion)


@contextlib.contextmanager
def registros():
    """Todo lo que se registre, en cualquier logger y nivel."""
    mensajes = []

    class _Captura(logging.Handler):
        def emit(self, record):
            mensajes.append(record.getMessage())

    raiz = logging.getLogger()
    captura, nivel = _Captura(level=logging.DEBUG), raiz.level
    raiz.addHandler(captura)
    raiz.setLevel(logging.DEBUG)
    try:
        yield mensajes
    finally:
        raiz.removeHandler(captura)
        raiz.setLevel(nivel)


# --- Pruebas -------------------------------------------------------------------------

class _Base(unittest.TestCase):

    def setUp(self):
        self.db = {
            "perfiles": [], "administradores_principales": [], "solicitudes_administrador": [],
            "aprobaciones_administrador": [], "auditoria_administracion": [],
        }
        self.admin_db = ClienteAdministracion(self.db)
        self.auth = self.admin_db.auth.admin

        parche = patch.object(servicio_perfiles, "get_user_scoped_client",
                              side_effect=lambda t: ClienteFalso(self.db, uid=t.removeprefix("token-")))
        parche.start()
        self.addCleanup(parche.stop)
        parche = patch.object(servicio_administracion, "supabase_admin", self.admin_db)
        parche.start()
        self.addCleanup(parche.stop)
        parche = patch.dict(os.environ, {"INVITACION_MODO": "", "FRONTEND_URL": ""})
        parche.start()
        self.addCleanup(parche.stop)

        self.angel = self.usuario("Ángel", "administrador", principal=True)
        self.loreto = self.usuario("Loreto", "administrador", principal=True)
        self.camila = self.usuario("Camila", "administrador", principal=True)
        self.nuevo_admin = self.usuario("Nora", "administrador")
        self.juan = self.usuario("Juan", "profesional")
        self.ana = self.usuario("Ana", "profesional")

        self.cliente = TestClient(app)
        self.addCleanup(app.dependency_overrides.clear)

    def usuario(self, nombre, rol, principal=False, pendiente=False):
        usuario = UsuarioActual(id=uuid4(), email=f"{nombre.lower()}@x.cl", access_token="")
        usuario.access_token = f"token-{usuario.id}"
        self.db["perfiles"].append({"id": str(usuario.id), "email": usuario.email, "nombre": nombre,
                                    "rol_global": rol, "fecha_creacion": _ahora(),
                                    "acceso_configurado_at": None if pendiente else _ahora()})
        if principal:
            self.db["administradores_principales"].append({"perfil_id": str(usuario.id), "fecha_creacion": _ahora()})
        return usuario

    def como(self, usuario, control_de_acceso=False):
        """Sesión de `usuario`. Con control_de_acceso corre el control real de invitación pendiente."""
        app.dependency_overrides[dependencias.obtener_sesion] = lambda: usuario
        if control_de_acceso:
            app.dependency_overrides.pop(dependencias.obtener_usuario_actual, None)
        else:
            app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        return self.cliente

    def perfil(self, usuario):
        return next(p for p in self.db["perfiles"] if p["id"] == str(usuario.id))

    def rol(self, usuario):
        return next(p["rol_global"] for p in self.db["perfiles"] if p["id"] == str(usuario.id))

    def auditoria(self, accion, objetivo=None):
        return [a for a in self.db["auditoria_administracion"]
                if a["accion"] == accion and (objetivo is None or a["usuario_objetivo_id"] == str(objetivo.id))]

    def solicitar(self, objetivo, por=None):
        return self.como(por or self.angel).post(f"/administracion/usuarios/{objetivo.id}/solicitar-administrador")

    def aprobar(self, solicitud_id, por):
        return self.como(por).post(f"/administracion/solicitudes-administrador/{solicitud_id}/aprobar")


class Autorizacion(_Base):

    def rutas(self):
        uid, sid = uuid4(), uuid4()
        return [
            ("get", "/administracion/usuarios", None),
            ("post", "/administracion/usuarios", {"nombre": "X", "email": "x@x.cl"}),
            ("post", f"/administracion/usuarios/{uid}/solicitar-administrador", None),
            ("post", f"/administracion/usuarios/{uid}/renovar-invitacion", None),
            ("get", "/administracion/configuracion", None),
            ("get", "/administracion/solicitudes-administrador", None),
            ("post", f"/administracion/solicitudes-administrador/{sid}/aprobar", None),
        ]

    def test_profesional_no_lista_ni_administra(self):
        api = self.como(self.juan)
        for metodo, ruta, cuerpo in self.rutas():
            respuesta = getattr(api, metodo)(ruta, **({"json": cuerpo} if cuerpo else {}))
            self.assertEqual(respuesta.status_code, 403, ruta)
            self.assertNotIn("loreto@x.cl", respuesta.text)
        self.assertEqual(self.auth.llamadas, [])

    def test_sin_token_401(self):
        for metodo, ruta, cuerpo in self.rutas():
            respuesta = getattr(TestClient(app), metodo)(ruta, **({"json": cuerpo} if cuerpo else {}))
            self.assertEqual(respuesta.status_code, 401, ruta)

    def test_administrador_lista_usuarios(self):
        self.perfil(self.ana)["acceso_configurado_at"] = None
        respuesta = self.como(self.nuevo_admin).get("/administracion/usuarios")
        self.assertEqual(respuesta.status_code, 200)
        filas = respuesta.json()
        # Principales primero, luego administradores y profesionales.
        self.assertEqual([f["nombre"] for f in filas], ["Ángel", "Camila", "Loreto", "Nora", "Ana", "Juan"])
        juan = filas[-1]
        self.assertEqual((juan["email"], juan["rol_global"], juan["estado"], juan["es_administrador_principal"]),
                         ("juan@x.cl", "profesional", "activo", False))
        self.assertTrue(juan["puede_solicitar_administrador"])
        self.assertEqual(filas[-2]["estado"], "pendiente")
        self.assertTrue(all(f["es_administrador_principal"] for f in filas[:3]))
        self.assertFalse(any(f["puede_solicitar_administrador"] for f in filas[:4]))
        self.assertIsNotNone(juan["fecha_creacion"])

    def test_el_estado_sale_del_perfil_no_de_auth(self):
        # Supabase confirma el correo al abrir el enlace; eso no activa la cuenta.
        self.perfil(self.ana)["acceso_configurado_at"] = None
        self.auth.confirmados.add(str(self.ana.id))
        self.auth.falla = AuthRetryableError("caído", 503)
        filas = {f["nombre"]: f["estado"] for f in self.como(self.angel).get("/administracion/usuarios").json()}
        self.assertEqual(filas["Ana"], "pendiente")
        self.assertEqual(filas["Juan"], "activo")

    def test_sin_la_migracion_008_usa_el_estado_de_auth(self):
        for perfil in self.db["perfiles"]:
            perfil.pop("acceso_configurado_at")
        self.auth.confirmados.add(str(self.juan.id))
        filas = {f["nombre"]: f["estado"] for f in self.como(self.angel).get("/administracion/usuarios").json()}
        self.assertEqual((filas["Juan"], filas["Ana"]), ("activo", "pendiente"))


class CrearUsuario(_Base):

    def crear(self, cuerpo=None, por=None):
        return self.como(por or self.angel).post(
            "/administracion/usuarios", json=cuerpo or {"nombre": "  Marta   Díaz ", "email": "Marta@X.cl"})

    def test_crea_profesional_con_enlace(self):
        with registros() as mensajes:
            respuesta = self.crear()
        # El enlace no pasa por ningún log.
        self.assertFalse([m for m in mensajes if "ENLACE-SECRETO" in m])
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.headers["cache-control"], "no-store")
        cuerpo = respuesta.json()
        self.assertEqual((cuerpo["modo"], cuerpo["enlace"]), ("enlace", self.auth.vigente["marta@x.cl"]))
        usuario = cuerpo["usuario"]
        self.assertEqual((usuario["nombre"], usuario["email"], usuario["rol_global"], usuario["estado"]),
                         ("Marta Díaz", "marta@x.cl", "profesional", "pendiente"))

        # Supabase Auth crea la cuenta: BuildCast no recibe ni guarda contraseñas.
        nombre, params = self.auth.llamadas[0]
        self.assertEqual((nombre, params["type"], params["email"]), ("generate_link", "invite", "marta@x.cl"))
        self.assertNotIn("password", params)
        self.assertEqual(params["options"]["data"], {"nombre": "Marta Díaz"})

        auditados = self.auditoria("usuario_creado")
        self.assertEqual(len(auditados), 1)
        self.assertEqual(auditados[0]["actor_id"], str(self.angel.id))
        # El enlace no queda en la auditoría.
        self.assertNotIn("ENLACE-SECRETO", repr(self.db))

    def test_el_enlace_no_vuelve_a_aparecer(self):
        self.crear()
        listado = self.como(self.angel).get("/administracion/usuarios")
        self.assertNotIn("ENLACE-SECRETO", listado.text)
        marta = next(f for f in listado.json() if f["email"] == "marta@x.cl")
        self.assertEqual((marta["nombre"], marta["rol_global"]), ("Marta Díaz", "profesional"))

    def test_modo_correo_no_devuelve_enlace(self):
        with patch.dict(os.environ, {"INVITACION_MODO": "correo", "FRONTEND_URL": "https://app.cl/"}):
            respuesta = self.crear()
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual((respuesta.json()["modo"], respuesta.json()["enlace"]), ("correo", None))
        nombre, email, opciones = self.auth.llamadas[0]
        self.assertEqual((nombre, email), ("invite_user_by_email", "marta@x.cl"))
        self.assertEqual(opciones["redirect_to"], "https://app.cl/acceso.html")

    def test_modo_desconocido_usa_enlace(self):
        with patch.dict(os.environ, {"INVITACION_MODO": "sms"}):
            with self.assertLogs(servicio_administracion.logger, level="WARNING"):
                self.assertEqual(self.crear().json()["modo"], "enlace")

    def test_correo_existente_409(self):
        respuesta = self.crear({"nombre": "Juan", "email": " JUAN@x.cl "})
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(self.auth.llamadas, [])

    def test_auth_rechaza_correo_existente_409(self):
        self.auth.falla = AuthApiError("A user with this email address has already been registered", 422, "email_exists")
        with self.assertLogs(servicio_administracion.logger, level="WARNING") as registro:
            respuesta = self.crear()
        self.assertEqual(respuesta.status_code, 409)
        self.assertNotIn("marta", "\n".join(registro.output).lower())

    def test_auth_caido_503(self):
        self.auth.falla = AuthRetryableError("caído", 503)
        with self.assertLogs(servicio_administracion.logger, level="WARNING"):
            self.assertEqual(self.crear().status_code, 503)

    def test_datos_invalidos_422(self):
        self.assertEqual(self.crear({"nombre": "   ", "email": "marta@x.cl"}).status_code, 422)
        self.assertEqual(self.crear({"nombre": "Marta", "email": "no-es-correo"}).status_code, 422)
        self.assertEqual(self.crear({"nombre": "M" * 121, "email": "marta@x.cl"}).status_code, 422)
        self.assertEqual(self.auth.llamadas, [])

    def test_un_administrador_no_principal_tambien_crea(self):
        self.assertEqual(self.crear(por=self.nuevo_admin).status_code, 201)

    def test_si_falla_la_auditoria_igual_entrega_el_enlace(self):
        self.admin_db._rpc_registrar_usuario_creado = lambda **_: (_ for _ in ()).throw(_error("XX000", "falla"))
        with self.assertLogs(servicio_administracion.logger, level="ERROR") as registro:
            respuesta = self.crear()
        self.assertEqual(respuesta.json()["enlace"], self.auth.vigente["marta@x.cl"])
        self.assertNotIn("ENLACE-SECRETO", "\n".join(registro.output))


class RenovarInvitacion(_Base):
    """Ana no completó su invitación; Juan ya entró."""

    def setUp(self):
        super().setUp()
        self.perfil(self.ana)["acceso_configurado_at"] = None
        self.auth.confirmados.update({str(self.juan.id), str(self.angel.id)})

    def renovar(self, objetivo, por=None):
        return self.como(por or self.angel).post(f"/administracion/usuarios/{objetivo.id}/renovar-invitacion")

    def test_pendiente_recibe_un_enlace_nuevo(self):
        perfiles = copy.deepcopy(self.db["perfiles"])
        respuesta = self.renovar(self.ana)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers["cache-control"], "no-store")
        cuerpo = respuesta.json()
        self.assertEqual((cuerpo["modo"], cuerpo["enlace"]), ("enlace", self.auth.vigente["ana@x.cl"]))
        usuario = cuerpo["usuario"]
        self.assertEqual((usuario["id"], usuario["estado"], usuario["rol_global"], usuario["nombre"]),
                         (str(self.ana.id), "pendiente", "profesional", "Ana"))

        # La misma cuenta: sin usuario ni perfil nuevo, sin cambios de nombre ni rol.
        nombre, params = self.auth.llamadas[0]
        self.assertEqual((nombre, params["type"], params["email"]), ("generate_link", "invite", "ana@x.cl"))
        self.assertNotIn("data", params["options"])
        self.assertNotIn("password", params)
        self.assertEqual(self.db["perfiles"], perfiles)
        self.assertEqual(self.auditoria("usuario_creado"), [])

        [auditado] = self.auditoria("invitacion_renovada", self.ana)
        self.assertEqual((auditado["actor_id"], auditado["detalle"]),
                         (str(self.angel.id), {"email": "ana@x.cl", "modo": "enlace"}))

    def test_el_enlace_no_va_a_logs_ni_auditoria_ni_listado(self):
        with registros() as mensajes:
            enlace = self.renovar(self.ana).json()["enlace"]
            listado = self.como(self.angel).get("/administracion/usuarios")
        self.assertIn("ENLACE-SECRETO", enlace)
        self.assertFalse([m for m in mensajes if "ENLACE-SECRETO" in m or "verify" in m])
        self.assertNotIn("ENLACE-SECRETO", repr(self.db))
        self.assertNotIn("ENLACE-SECRETO", listado.text)

    def test_si_falla_la_auditoria_igual_entrega_el_enlace_sin_registrarlo(self):
        self.admin_db._rpc_registrar_invitacion_renovada = lambda **_: (_ for _ in ()).throw(_error("XX000", "falla"))
        with registros() as mensajes:
            respuesta = self.renovar(self.ana)
        self.assertEqual(respuesta.json()["enlace"], self.auth.vigente["ana@x.cl"])
        self.assertTrue([m for m in mensajes if "sin auditoría" in m])
        self.assertFalse([m for m in mensajes if "ENLACE-SECRETO" in m])

    def test_doble_solicitud_deja_valido_solo_el_ultimo(self):
        primera = self.renovar(self.ana)
        segunda = self.renovar(self.ana)
        self.assertEqual((primera.status_code, segunda.status_code), (200, 200))
        self.assertNotEqual(primera.json()["enlace"], segunda.json()["enlace"])
        # Supabase reemplaza el token: el primer enlace ya no sirve.
        self.assertEqual(self.auth.vigente["ana@x.cl"], segunda.json()["enlace"])
        self.assertEqual(len(self.auditoria("invitacion_renovada", self.ana)), 2)
        self.assertEqual(sum(p["email"] == "ana@x.cl" for p in self.db["perfiles"]), 1)
        self.assertEqual(self.rol(self.ana), "profesional")

    def test_usuario_activo_409_sin_tocar_auth(self):
        respuesta = self.renovar(self.juan)
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn("activa", respuesta.json()["detail"])
        self.assertEqual(self.auth.llamadas, [])
        self.assertEqual(self.auditoria("invitacion_renovada"), [])

    def test_abre_el_enlace_entre_la_lectura_y_el_envio(self):
        # La lectura la ve sin confirmar; al generar, Supabase ya la confirmó (422) y se
        # pasa a un enlace de recuperación. Sigue pendiente hasta crear su contraseña.
        leer = self.auth.get_user_by_id

        def lectura_vieja(uid):
            cuenta = leer(uid)
            cuenta.user.email_confirmed_at = None
            return cuenta

        self.auth.get_user_by_id = lectura_vieja
        self.auth.confirmados.add(str(self.ana.id))
        respuesta = self.renovar(self.ana)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([(n, p["type"]) for n, p in self.auth.llamadas], [("generate_link", "invite"),
                                                                        ("generate_link", "recovery")])
        self.assertEqual(respuesta.json()["enlace"], self.auth.vigente["ana@x.cl"])
        self.assertIsNone(self.perfil(self.ana)["acceso_configurado_at"])

    def test_confirmada_en_auth_modo_correo_reenvia_recuperacion(self):
        self.auth.confirmados.add(str(self.ana.id))
        with patch.dict(os.environ, {"INVITACION_MODO": "correo", "FRONTEND_URL": "https://app.cl"}):
            respuesta = self.renovar(self.ana)
        self.assertEqual((respuesta.status_code, respuesta.json()["enlace"]), (200, None))
        self.assertEqual(self.auth.llamadas, [("reset_password_for_email", "ana@x.cl",
                                               {"redirect_to": "https://app.cl/acceso.html"})])

    def test_profesional_sin_permisos_403(self):
        respuesta = self.renovar(self.ana, por=self.juan)
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.auth.llamadas, [])
        self.assertEqual(self.auditoria("invitacion_renovada"), [])
        self.assertNotIn("ENLACE-SECRETO", respuesta.text)

    def test_un_administrador_no_principal_tambien_renueva(self):
        self.assertEqual(self.renovar(self.ana, por=self.nuevo_admin).status_code, 200)

    def test_usuario_inexistente_404(self):
        respuesta = self.como(self.angel).post(f"/administracion/usuarios/{uuid4()}/renovar-invitacion")
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(self.auth.llamadas, [])

    def test_perfil_sin_cuenta_en_auth_404(self):
        self.auth.get_user_by_id = lambda uid: (_ for _ in ()).throw(
            AuthApiError("User not found", 404, "user_not_found"))
        self.assertEqual(self.renovar(self.ana).status_code, 404)
        self.assertEqual(self.auth.llamadas, [])

    def test_modo_correo_reenvia_sin_devolver_enlace(self):
        with patch.dict(os.environ, {"INVITACION_MODO": "correo", "FRONTEND_URL": "https://app.cl"}):
            respuesta = self.renovar(self.ana)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual((respuesta.json()["modo"], respuesta.json()["enlace"]), ("correo", None))
        self.assertEqual(self.auth.llamadas[0], ("invite_user_by_email", "ana@x.cl",
                                                 {"redirect_to": "https://app.cl/acceso.html"}))
        [auditado] = self.auditoria("invitacion_renovada", self.ana)
        self.assertEqual(auditado["detalle"]["modo"], "correo")

    def test_limite_de_envio_429(self):
        self.auth.invite_user_by_email = lambda *a, **k: (_ for _ in ()).throw(
            AuthApiError("email rate limit exceeded", 429, "over_email_send_rate_limit"))
        with patch.dict(os.environ, {"INVITACION_MODO": "correo"}), \
                self.assertLogs(servicio_administracion.logger, level="WARNING"):
            self.assertEqual(self.renovar(self.ana).status_code, 429)

    def test_auth_caido_503(self):
        self.auth.falla = AuthRetryableError("caído", 503)
        with self.assertLogs(servicio_administracion.logger, level="WARNING"):
            self.assertEqual(self.renovar(self.ana).status_code, 503)

    def test_configuracion_informa_el_modo(self):
        api = self.como(self.angel)
        self.assertEqual(api.get("/administracion/configuracion").json(), {"modo_invitacion": "enlace"})
        with patch.dict(os.environ, {"INVITACION_MODO": "correo"}):
            self.assertEqual(api.get("/administracion/configuracion").json(), {"modo_invitacion": "correo"})


class Promocion(_Base):

    def setUp(self):
        super().setUp()
        respuesta = self.solicitar(self.juan, por=self.nuevo_admin)
        self.assertEqual(respuesta.status_code, 201)
        self.solicitud = respuesta.json()

    def test_solicitud_queda_en_0_de_3(self):
        s = self.solicitud
        self.assertEqual((s["estado"], s["aprobaciones_recibidas"], s["aprobaciones_requeridas"]), ("pendiente", 0, 3))
        self.assertEqual([a["nombre"] for a in s["aprobaciones"]], ["Ángel", "Loreto", "Camila"])
        self.assertFalse(any(a["aprobada"] for a in s["aprobaciones"]))
        self.assertEqual(s["solicitado_por"], str(self.nuevo_admin.id))
        # Quien solicita no es principal: no puede aprobar.
        self.assertFalse(s["puedo_aprobar"])
        self.assertEqual(self.rol(self.juan), "profesional")
        self.assertEqual(len(self.auditoria("solicitud_administrador_creada", self.juan)), 1)

    def test_solicitud_duplicada_409(self):
        self.assertEqual(self.solicitar(self.juan).status_code, 409)
        self.assertEqual(len(self.db["solicitudes_administrador"]), 1)

    def test_no_se_solicita_para_un_administrador(self):
        self.assertEqual(self.solicitar(self.nuevo_admin).status_code, 409)
        self.assertEqual(self.solicitar(self.loreto).status_code, 409)

    def test_usuario_inexistente_404(self):
        respuesta = self.como(self.angel).post(f"/administracion/usuarios/{uuid4()}/solicitar-administrador")
        self.assertEqual(respuesta.status_code, 404)

    def test_1_y_2_de_3_no_promueven_y_3_de_3_promueve_una_vez(self):
        sid = self.solicitud["id"]

        uno = self.aprobar(sid, self.angel).json()
        self.assertEqual((uno["estado"], uno["aprobaciones_recibidas"]), ("pendiente", 1))
        self.assertEqual(self.rol(self.juan), "profesional")

        dos = self.aprobar(sid, self.loreto).json()
        self.assertEqual((dos["estado"], dos["aprobaciones_recibidas"]), ("pendiente", 2))
        self.assertEqual([a["aprobada"] for a in dos["aprobaciones"]], [True, True, False])
        self.assertEqual(self.rol(self.juan), "profesional")

        tres = self.aprobar(sid, self.camila)
        self.assertEqual(tres.status_code, 200)
        self.assertEqual((tres.json()["estado"], tres.json()["aprobaciones_recibidas"]), ("aprobada", 3))
        self.assertEqual(self.rol(self.juan), "administrador")

        # Completada: no admite más aprobaciones ni vuelve a promover.
        self.assertEqual(self.aprobar(sid, self.angel).status_code, 409)
        self.assertEqual(len(self.auditoria("usuario_promovido_administrador", self.juan)), 1)
        self.assertEqual(len(self.auditoria("administrador_aprobado", self.juan)), 3)

        # El nuevo administrador no se vuelve principal.
        self.assertNotIn(str(self.juan.id), [a["perfil_id"] for a in self.db["administradores_principales"]])
        self.assertEqual(len(self.db["administradores_principales"]), 3)
        juan = next(f for f in self.como(self.juan).get("/administracion/usuarios").json() if f["nombre"] == "Juan")
        self.assertEqual((juan["rol_global"], juan["es_administrador_principal"]), ("administrador", False))

    def test_aprobacion_duplicada_409(self):
        self.aprobar(self.solicitud["id"], self.angel)
        respuesta = self.aprobar(self.solicitud["id"], self.angel)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(len(self.db["aprobaciones_administrador"]), 1)

    def test_no_principal_no_aprueba(self):
        respuesta = self.aprobar(self.solicitud["id"], self.nuevo_admin)
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.db["aprobaciones_administrador"], [])
        # Un profesional ni siquiera llega a la RPC.
        self.assertEqual(self.aprobar(self.solicitud["id"], self.ana).status_code, 403)

    def test_quien_solicita_y_es_principal_tambien_aprueba(self):
        solicitud = self.solicitar(self.ana, por=self.camila).json()
        self.assertTrue(solicitud["puedo_aprobar"])
        self.assertEqual(self.aprobar(solicitud["id"], self.camila).json()["aprobaciones_recibidas"], 1)

    def test_puedo_aprobar_solo_para_principales_que_no_votaron(self):
        self.aprobar(self.solicitud["id"], self.angel)
        for usuario, esperado in ((self.angel, False), (self.loreto, True), (self.camila, True),
                                  (self.nuevo_admin, False)):
            [s] = self.como(usuario).get("/administracion/solicitudes-administrador").json()
            self.assertEqual(s["puedo_aprobar"], esperado, usuario.email)
        # El listado de usuarios trae la misma solicitud embebida.
        juan = next(f for f in self.como(self.loreto).get("/administracion/usuarios").json() if f["nombre"] == "Juan")
        self.assertEqual(juan["solicitud_pendiente"]["aprobaciones_recibidas"], 1)
        self.assertFalse(juan["puede_solicitar_administrador"])

    def test_solicitud_inexistente_404(self):
        self.assertEqual(self.aprobar(uuid4(), self.angel).status_code, 404)

    def test_grupo_incompleto_no_promueve(self):
        self.db["administradores_principales"].pop()
        self.assertEqual(self.aprobar(self.solicitud["id"], self.angel).status_code, 409)
        self.assertEqual(self.db["aprobaciones_administrador"], [])

    def test_principales_sin_rutas_para_degradar_ni_eliminar(self):
        api = self.como(self.angel)
        for metodo, ruta in (("delete", f"/administracion/usuarios/{self.loreto.id}"),
                             ("put", f"/administracion/usuarios/{self.loreto.id}"),
                             ("post", f"/administracion/usuarios/{self.loreto.id}/degradar")):
            self.assertIn(getattr(api, metodo)(ruta).status_code, (404, 405), ruta)
        self.assertEqual(self.rol(self.loreto), "administrador")


class AccesoInvitacion(_Base):
    """Invitación → enlace → «Crea tu contraseña» → activo. Activo solo con acceso_configurado_at."""

    CLAVE = "una-clave-larga-123"

    def setUp(self):
        super().setUp()
        # establecer-contrasena usa el mismo service role falso (Auth y RPC).
        parche = patch.object(servicio_autenticacion, "supabase_admin", self.admin_db)
        parche.start()
        self.addCleanup(parche.stop)
        parche = patch.object(servicio_proyectos, "obtener_proyectos", return_value=[])
        parche.start()
        self.addCleanup(parche.stop)

    def invitar(self, email="marta@x.cl"):
        cuerpo = self.como(self.angel).post("/administracion/usuarios", json={"nombre": "Marta", "email": email}).json()
        datos = cuerpo["usuario"]
        marta = UsuarioActual(id=datos["id"], email=email, access_token=f"token-{datos['id']}")
        return marta, cuerpo

    def estado_en_listado(self, usuario):
        return next(f["estado"] for f in self.como(self.angel).get("/administracion/usuarios").json()
                    if f["id"] == str(usuario.id))

    def establecer(self, usuario, clave=None):
        return self.como(usuario, control_de_acceso=True).post(
            "/autenticacion/establecer-contrasena", json={"password": clave or self.CLAVE})

    def test_crear_invitado_queda_pendiente(self):
        marta, cuerpo = self.invitar()
        self.assertEqual(cuerpo["usuario"]["estado"], "pendiente")
        self.assertIsNone(self.perfil(marta)["acceso_configurado_at"])
        self.assertEqual(self.estado_en_listado(marta), "pendiente")

    def test_abrir_el_enlace_sin_contrasena_sigue_pendiente(self):
        marta, _ = self.invitar()
        self.auth.abrir_enlace("marta@x.cl")
        # Supabase ya la confirmó, pero BuildCast no la da por activa.
        self.assertEqual(self.estado_en_listado(marta), "pendiente")
        yo = self.como(marta, control_de_acceso=True).get("/autenticacion/yo")
        self.assertEqual(yo.status_code, 200)
        self.assertFalse(yo.json()["acceso_configurado"])

    def test_pendiente_no_usa_la_api_normal(self):
        marta, _ = self.invitar()
        self.auth.abrir_enlace("marta@x.cl")
        api = self.como(marta, control_de_acceso=True)
        for metodo, ruta in (("get", "/proyectos"), ("get", "/administracion/usuarios"), ("get", "/banco/versiones")):
            respuesta = getattr(api, metodo)(ruta, headers={"Origin": "http://localhost:5173"})
            self.assertEqual(respuesta.status_code, 403, ruta)
            self.assertEqual(respuesta.headers.get(dependencias.CABECERA_ACCESO), "pendiente", ruta)
            self.assertEqual(respuesta.json()["detail"], dependencias.ACCESO_PENDIENTE)
            # El navegador puede leer la cabecera desde otro origen.
            self.assertIn(dependencias.CABECERA_ACCESO.lower(),
                          respuesta.headers.get("access-control-expose-headers", "").lower())

    def test_sin_perfil_no_usa_la_api(self):
        fantasma = UsuarioActual(id=uuid4(), email="f@x.cl", access_token="")
        fantasma.access_token = f"token-{fantasma.id}"
        self.assertEqual(self.como(fantasma, control_de_acceso=True).get("/proyectos").status_code, 403)

    def test_establecer_contrasena_activa_la_cuenta(self):
        marta, _ = self.invitar()
        self.auth.abrir_enlace("marta@x.cl")
        with registros() as mensajes:
            respuesta = self.establecer(marta)
        self.assertEqual(respuesta.status_code, 200)
        # Supabase guarda la contraseña; BuildCast no.
        self.assertEqual(self.auth.contrasenas, {str(marta.id): self.CLAVE})
        self.assertNotIn(self.CLAVE, repr(self.db))
        self.assertFalse([m for m in mensajes if self.CLAVE in m])

        self.assertIsNotNone(self.perfil(marta)["acceso_configurado_at"])
        self.assertEqual(self.estado_en_listado(marta), "activo")
        self.assertEqual(len(self.auditoria("acceso_configurado", marta)), 1)
        # Ya entra a la API normal.
        self.assertEqual(self.como(marta, control_de_acceso=True).get("/proyectos").status_code, 200)
        self.assertTrue(self.como(marta, control_de_acceso=True).get("/autenticacion/yo").json()["acceso_configurado"])

    def test_si_auth_rechaza_la_contrasena_sigue_pendiente(self):
        marta, _ = self.invitar()
        self.auth.falla = AuthApiError("Password should be at least 12 characters", 422, "weak_password")
        respuesta = self.establecer(marta)
        self.assertEqual(respuesta.status_code, 422)
        self.assertIsNone(self.perfil(marta)["acceso_configurado_at"])
        self.assertEqual(self.auditoria("acceso_configurado"), [])
        self.auth.falla = AuthRetryableError("caído", 503)
        self.assertEqual(self.establecer(marta).status_code, 503)
        self.assertIsNone(self.perfil(marta)["acceso_configurado_at"])

    def test_si_falla_la_activacion_sigue_pendiente_y_puede_reintentar(self):
        marta, _ = self.invitar()
        original = self.admin_db._rpc_completar_acceso
        self.admin_db._rpc_completar_acceso = lambda **_: (_ for _ in ()).throw(_error("XX000", "falla"))
        with registros() as mensajes:
            respuesta = self.establecer(marta)
        self.assertEqual(respuesta.status_code, 503)
        self.assertIsNone(self.perfil(marta)["acceso_configurado_at"])
        self.assertFalse([m for m in mensajes if self.CLAVE in m])

        self.admin_db._rpc_completar_acceso = original
        self.assertEqual(self.establecer(marta).status_code, 200)
        self.assertEqual(self.estado_en_listado(marta), "activo")

    def test_usuario_activo_no_repite_el_flujo(self):
        respuesta = self.establecer(self.juan)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(self.auth.contrasenas, {})

    def test_usuarios_existentes_siguen_activos(self):
        api = self.como(self.juan, control_de_acceso=True)
        self.assertEqual(api.get("/proyectos").status_code, 200)
        self.assertTrue(api.get("/autenticacion/yo").json()["acceso_configurado"])

    def test_sin_la_migracion_008_no_se_bloquea_a_nadie(self):
        sin_columna = APIError({"code": "42703", "message": "column perfiles.acceso_configurado_at does not exist",
                                "hint": None, "details": None})
        with patch.object(servicio_perfiles, "get_user_scoped_client",
                          return_value=SimpleNamespace(table=lambda _t: (_ for _ in ()).throw(sin_columna))), \
                self.assertLogs(servicio_perfiles.logger, level="WARNING"):
            self.assertEqual(self.como(self.juan, control_de_acceso=True).get("/proyectos").status_code, 200)

    def test_renovar_no_activa_la_cuenta(self):
        marta, _ = self.invitar()
        self.auth.abrir_enlace("marta@x.cl")
        respuesta = self.como(self.angel).post(f"/administracion/usuarios/{marta.id}/renovar-invitacion")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["usuario"]["estado"], "pendiente")
        self.assertIsNone(self.perfil(marta)["acceso_configurado_at"])
        # Ya confirmada en Auth: invite no aplica, se usa un enlace de recuperación.
        nombre, params = self.auth.llamadas[-1]
        self.assertEqual((nombre, params["type"], params["email"]), ("generate_link", "recovery", "marta@x.cl"))
        self.assertEqual(respuesta.json()["enlace"], self.auth.vigente["marta@x.cl"])

    def test_activa_ya_no_se_renueva(self):
        marta, _ = self.invitar()
        self.establecer(marta)
        respuesta = self.como(self.angel).post(f"/administracion/usuarios/{marta.id}/renovar-invitacion")
        self.assertEqual(respuesta.status_code, 409)

    def test_sin_token_401(self):
        respuesta = TestClient(app).post("/autenticacion/establecer-contrasena", json={"password": self.CLAVE})
        self.assertEqual(respuesta.status_code, 401)

    def test_contrasena_corta_422_sin_llamar_a_auth(self):
        marta, _ = self.invitar()
        self.assertEqual(self.establecer(marta, "corta").status_code, 422)
        self.assertEqual(self.auth.contrasenas, {})


class Migracion008(unittest.TestCase):

    def test_estado_explicito_y_solo_por_rpc(self):
        sql = (MIGRACIONES / "008_acceso_configurado.sql").read_text(encoding="utf-8")
        self.assertIn("add column acceso_configurado_at timestamptz;", sql)
        # Existentes: activos.
        self.assertIn("set acceso_configurado_at = coalesce(fecha_creacion, now())", sql)
        # Cuentas nuevas sin contraseña (invitadas): pendientes.
        self.assertIn("new.invited_at is null and coalesce(new.encrypted_password, '') <> ''", sql)
        self.assertNotIn("email_confirmed_at", sql.split("-- 2.")[1])
        self.assertRegex(sql, r"revoke execute on function public\.completar_acceso\(uuid\) from public, anon, authenticated;")
        self.assertRegex(sql, r"grant execute on function public\.completar_acceso\(uuid\) to service_role;")
        # Ningún grant nuevo sobre perfiles: la columna solo se escribe con la RPC.
        self.assertNotRegex(sql, r"grant [^;]*on public\.perfiles")
        self.assertNotRegex(sql, r"jsonb_build_object\([^;]*(password|token)")


class RegistroPublico(unittest.TestCase):

    def test_cerrado_responde_403_sin_llamar_a_supabase(self):
        with patch.dict(os.environ, {"REGISTRO_PUBLICO": "false"}), \
                patch.object(servicio_autenticacion, "get_anon_client") as cliente:
            respuesta = TestClient(app).post("/autenticacion/registro", json={"email": "a@x.cl", "password": "123456"})
        self.assertEqual(respuesta.status_code, 403)
        cliente.assert_not_called()

    def test_abierto_por_defecto_durante_la_transicion(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REGISTRO_PUBLICO", None)
            self.assertTrue(servicio_autenticacion.registro_publico_abierto())
        for valor, abierto in (("false", False), ("0", False), ("NO", False), ("true", True)):
            with patch.dict(os.environ, {"REGISTRO_PUBLICO": valor}):
                self.assertEqual(servicio_autenticacion.registro_publico_abierto(), abierto, valor)


class Migracion005(unittest.TestCase):

    def test_sin_nombres_ni_correos_en_el_codigo(self):
        self.assertNotIn("@", M005)
        for nombre in ("Ángel", "Angel", "Loreto", "Camila"):
            self.assertNotIn(nombre, M005)

    def test_tablas_con_rls_y_sin_escritura_directa(self):
        for tabla in ("administradores_principales", "solicitudes_administrador",
                      "aprobaciones_administrador", "auditoria_administracion"):
            self.assertIn(f"alter table public.{tabla} enable row level security", M005)
            self.assertIn(f"revoke all on public.{tabla} from public, anon, authenticated, service_role;", M005)
            concedido = re.findall(rf"grant ([\w, ]+) on public\.{tabla} to ([\w, ]+);", M005)
            self.assertTrue(all(privilegio == "select" for privilegio, _ in concedido), tabla)
        # Única política: cada usuario ve si él mismo es principal.
        self.assertEqual(re.findall(r'create policy "(\w+)"', M005), ["administradores_principales_seleccionar_propio"])

    def test_el_backend_no_escribe_el_rol_global(self):
        self.assertIn("revoke insert, update on public.perfiles from service_role;", M005)
        self.assertIn("grant update (email, nombre) on public.perfiles to service_role;", M005)

    def test_rpc_security_definer_solo_para_service_role(self):
        cuerpos = dict(re.findall(r"create or replace function public\.(\w+)\(.*?\)(.*?)\bas \$\$", M005, flags=re.S))
        for nombre, cabecera in cuerpos.items():
            self.assertIn("security definer", cabecera, nombre)
            self.assertIn("set search_path = ''", cabecera, nombre)
        for rpc in ("registrar_usuario_creado", "solicitar_administrador", "aprobar_solicitud_administrador"):
            self.assertRegex(M005, rf"revoke execute on function public\.{rpc}\([^)]*\) from public, anon, authenticated;")
            self.assertRegex(M005, rf"grant execute on function public\.{rpc}\([^)]*\) to service_role;")
        self.assertNotRegex(M005, r"grant execute [^;]*\bto [^;]*\b(anon|authenticated|public)\b")

    def test_aprobacion_atomica_y_unica(self):
        self.assertIn("for update;", M005)
        self.assertIn("unique (solicitud_id, administrador_id)", M005)
        self.assertIn("where estado = 'pendiente';", M005)
        self.assertIn("c_requeridas constant integer := 3;", M005)
        self.assertEqual(servicio_administracion.APROBACIONES_REQUERIDAS, 3)

    def test_principales_protegidos(self):
        self.assertIn("references public.perfiles(id) on delete restrict", M005)
        self.assertIn("before update or delete on public.perfiles", M005)
        self.assertIn("before insert or update or delete on public.administradores_principales", M005)
        self.assertIn("before truncate on public.administradores_principales", M005)


class Migracion007(unittest.TestCase):

    def test_auditoria_sin_enlace_y_solo_service_role(self):
        sql = (MIGRACIONES / "007_renovar_invitacion.sql").read_text(encoding="utf-8")
        self.assertIn("'invitacion_renovada'", sql)
        self.assertIn("security definer", sql)
        self.assertIn("set search_path = ''", sql)
        self.assertIn("perform public.exigir_administrador_global(p_actor_id);", sql)
        self.assertRegex(sql, r"revoke execute on function public\.registrar_invitacion_renovada\([^)]*\) "
                              r"from public, anon, authenticated;")
        self.assertRegex(sql, r"grant execute on function public\.registrar_invitacion_renovada\([^)]*\) "
                              r"to service_role;")
        self.assertNotRegex(sql, r"jsonb_build_object\([^;]*(enlace|token|otp|link)")


if __name__ == "__main__":
    unittest.main()
