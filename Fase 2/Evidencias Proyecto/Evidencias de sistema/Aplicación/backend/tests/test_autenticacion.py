"""Validación del token, refresco de sesión y errores no controlados.

Supabase Auth se reemplaza por un falso: las pruebas nunca salen a la red.

Ejecutar desde backend/:
    python -m pytest
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

import httpx  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from supabase_auth.errors import (  # noqa: E402
    AuthApiError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthSessionMissingError,
    AuthUnknownError,
)

from app.database import supabase as base_de_datos  # noqa: E402
from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.errores import MENSAJE_ERROR_INTERNO, ErroresInesperados  # noqa: E402
from app.main import app  # noqa: E402
from app.services import servicio_autenticacion, servicio_perfiles, servicio_proyectos  # noqa: E402

ORIGEN = {"Origin": "http://localhost:5173"}
TOKEN = "token-secreto-de-prueba"


def sesion(sufijo="nuevo"):
    return SimpleNamespace(session=SimpleNamespace(
        access_token=f"access-{sufijo}", refresh_token=f"refresh-{sufijo}", expires_in=3600))


class AuthFalso:
    """Imita supabase.auth: cada método devuelve o lanza lo que se le indique."""

    def __init__(self, get_user=None, refresh_session=None, sign_in=None):
        self.respuestas = {"get_user": get_user, "refresh_session": refresh_session,
                           "sign_in_with_password": sign_in}
        self.llamadas = []

    def _responder(self, metodo, *args):
        self.llamadas.append((metodo, args))
        respuesta = self.respuestas[metodo]
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta

    def get_user(self, token):
        return self._responder("get_user", token)

    def refresh_session(self, token):
        return self._responder("refresh_session", token)

    def sign_in_with_password(self, datos):
        return self._responder("sign_in_with_password", datos)


def cliente_auth(**respuestas):
    auth = AuthFalso(**respuestas)
    return SimpleNamespace(auth=auth), auth


def token_rechazado():
    # Lo que responde Supabase a un JWT malformado, vencido o firmado por otro.
    return AuthApiError("invalid JWT: unable to parse or verify signature", 403, "bad_jwt")


USUARIO = SimpleNamespace(user=SimpleNamespace(id=uuid4(), email="a@x.cl"))

ERRORES_TRANSITORIOS = {
    "auth reintentable (503)": AuthRetryableError("Service Unavailable", 503),
    "auth 500": AuthApiError("Internal error", 500, None),
    "límite de peticiones": AuthApiError("Rate limit", 429, "over_request_rate_limit"),
    "respuesta no JSON": AuthUnknownError("Bad Gateway", ValueError("no json")),
    "timeout": httpx.ConnectTimeout("timed out"),
    "sin conexión": httpx.ConnectError("connection refused"),
    "lectura cortada": httpx.ReadTimeout("read timed out"),
}


class ValidarToken(unittest.TestCase):

    def pedir(self, get_user):
        cliente, auth = cliente_auth(get_user=get_user)
        with patch.object(dependencias, "get_anon_client", return_value=cliente):
            respuesta = TestClient(app, raise_server_exceptions=False).get(
                "/proyectos", headers={**ORIGEN, "Authorization": f"Bearer {TOKEN}"})
        return respuesta, auth

    def test_token_rechazado_401(self):
        for nombre, error in {
            "jwt inválido": token_rechazado(),
            "jwt vencido": AuthApiError("JWT expired", 401, "bad_jwt"),
            "usuario borrado": AuthApiError("User not found", 404, "user_not_found"),
            "jwt mal formado": AuthInvalidJwtError("Invalid JWT structure"),
            "sin sesión": AuthSessionMissingError(),
        }.items():
            with self.subTest(nombre=nombre):
                respuesta, _ = self.pedir(error)
                self.assertEqual(respuesta.status_code, 401)
                self.assertEqual(respuesta.headers["www-authenticate"], "Bearer")

    def test_auth_sin_usuario_401(self):
        for respuesta_auth in (None, SimpleNamespace(user=None)):
            self.assertEqual(self.pedir(respuesta_auth)[0].status_code, 401)

    def test_error_transitorio_503(self):
        for nombre, error in ERRORES_TRANSITORIOS.items():
            with self.subTest(nombre=nombre):
                respuesta, _ = self.pedir(error)
                self.assertEqual(respuesta.status_code, 503)
                self.assertEqual(respuesta.json()["detail"], servicio_autenticacion.MENSAJE_AUTH_NO_DISPONIBLE)
                # El frontend debe poder leerla: lleva CORS.
                self.assertEqual(respuesta.headers.get("access-control-allow-origin"), ORIGEN["Origin"])

    def test_el_503_no_registra_el_token(self):
        with self.assertLogs(dependencias.logger, level="WARNING") as registro:
            self.pedir(httpx.ConnectTimeout(f"timed out con {TOKEN}"))
        self.assertNotIn(TOKEN, "\n".join(registro.output))

    def test_error_inesperado_en_auth_500(self):
        respuesta, _ = self.pedir(ValueError("algo raro"))
        self.assertEqual((respuesta.status_code, respuesta.json()), (500, {"detail": MENSAJE_ERROR_INTERNO}))

    def test_token_valido_pasa(self):
        configurado = servicio_perfiles.EstadoAcceso.configurado
        with patch.object(servicio_proyectos, "obtener_proyectos", return_value=[]), \
                patch.object(servicio_perfiles, "estado_acceso", return_value=configurado):
            respuesta, auth = self.pedir(USUARIO)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(auth.llamadas, [("get_user", (TOKEN,))])

    def test_cliente_del_servidor_sin_auto_refresco(self):
        # Si refrescara por su cuenta, gastaría el refresh token del navegador.
        cliente = base_de_datos.get_anon_client()
        self.assertFalse(cliente.auth._auto_refresh_token)
        self.assertFalse(cliente.auth._persist_session)


class ErroresNoControlados(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: SimpleNamespace(id=uuid4())
        self.addCleanup(app.dependency_overrides.clear)

    def pedir(self, error):
        with patch.object(servicio_proyectos, "obtener_proyectos", side_effect=error):
            return TestClient(app, raise_server_exceptions=False).get("/proyectos", headers=ORIGEN)

    def test_500_json_sin_detalle_tecnico(self):
        with self.assertLogs("buildcast.errores", level="ERROR") as registro:
            respuesta = self.pedir(RuntimeError("detalle interno: tabla x columna y"))
        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(respuesta.json(), {"detail": MENSAJE_ERROR_INTERNO})
        self.assertNotIn("tabla x", respuesta.text)
        # El detalle va al log, con la ruta.
        self.assertIn("GET /proyectos", registro.output[0])
        self.assertIn("tabla x columna y", "\n".join(registro.output))

    def test_500_conserva_cors(self):
        respuesta = self.pedir(RuntimeError("x"))
        self.assertEqual(respuesta.headers.get("access-control-allow-origin"), ORIGEN["Origin"])

    def test_500_sin_origen_permitido_no_agrega_cors(self):
        with patch.object(servicio_proyectos, "obtener_proyectos", side_effect=RuntimeError("x")):
            respuesta = TestClient(app, raise_server_exceptions=False).get(
                "/proyectos", headers={"Origin": "https://otro.example"})
        self.assertEqual(respuesta.status_code, 500)
        self.assertIsNone(respuesta.headers.get("access-control-allow-origin"))

    def test_errores_controlados_no_cambian(self):
        # Un error de validación sigue siendo 422, no pasa por el middleware.
        respuesta = TestClient(app).get("/proyectos/no-es-uuid", headers=ORIGEN)
        self.assertEqual(respuesta.status_code, 422)
        self.assertNotEqual(respuesta.json(), {"detail": MENSAJE_ERROR_INTERNO})

    def test_orden_de_middleware(self):
        # El primero de la lista es el más externo: CORS debe envolver al de errores.
        clases = [m.cls for m in app.user_middleware]
        self.assertLess(clases.index(CORSMiddleware), clases.index(ErroresInesperados))


class RefrescarSesion(unittest.TestCase):

    def refrescar(self, refresh_session, cuerpo=None):
        cliente, auth = cliente_auth(refresh_session=refresh_session)
        with patch.object(servicio_autenticacion, "get_anon_client", return_value=cliente):
            respuesta = TestClient(app, raise_server_exceptions=False).post(
                "/autenticacion/refrescar", json={"refresh_token": "refresh-viejo"} if cuerpo is None else cuerpo,
                headers=ORIGEN)
        return respuesta, auth

    def test_refresh_valido_devuelve_tokens_nuevos(self):
        respuesta, auth = self.refrescar(sesion())
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {"access_token": "access-nuevo", "refresh_token": "refresh-nuevo",
                                            "token_type": "bearer", "expires_in": 3600})
        self.assertEqual(auth.llamadas, [("refresh_session", ("refresh-viejo",))])

    def test_no_exige_access_token(self):
        # Se usa justamente cuando el access token venció.
        self.assertEqual(self.refrescar(sesion())[0].status_code, 200)

    def test_refresh_invalido_401(self):
        for nombre, error in {
            "vencido o revocado": AuthApiError("Invalid Refresh Token: Refresh Token Not Found", 400,
                                               "refresh_token_not_found"),
            "ya usado": AuthApiError("Invalid Refresh Token: Already Used", 400, "refresh_token_already_used"),
            "sin sesión": AuthSessionMissingError(),
        }.items():
            with self.subTest(nombre=nombre):
                respuesta, _ = self.refrescar(error)
                self.assertEqual(respuesta.status_code, 401)
                self.assertEqual(respuesta.json()["detail"], "La sesión expiró. Vuelve a iniciar sesión.")

    def test_auth_sin_sesion_401(self):
        self.assertEqual(self.refrescar(SimpleNamespace(session=None))[0].status_code, 401)

    def test_refresh_con_auth_caido_503(self):
        for nombre, error in ERRORES_TRANSITORIOS.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(self.refrescar(error)[0].status_code, 503)

    def test_cuerpo_invalido_422(self):
        for cuerpo in ({}, {"refresh_token": ""}, {"refresh_token": None}):
            with self.subTest(cuerpo=cuerpo):
                respuesta, auth = self.refrescar(sesion(), cuerpo)
                self.assertEqual(respuesta.status_code, 422)
                self.assertEqual(auth.llamadas, [])


class IniciarSesion(unittest.TestCase):

    def entrar(self, sign_in):
        cliente, _ = cliente_auth(sign_in=sign_in)
        with patch.object(servicio_autenticacion, "get_anon_client", return_value=cliente):
            return TestClient(app).post("/autenticacion/iniciar-sesion",
                                        json={"email": "a@x.cl", "password": "secreta"})

    def test_devuelve_ambos_tokens(self):
        respuesta = self.entrar(sesion("login"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual((respuesta.json()["access_token"], respuesta.json()["refresh_token"]),
                         ("access-login", "refresh-login"))

    def test_credenciales_invalidas_401_y_auth_caido_503(self):
        self.assertEqual(self.entrar(AuthApiError("Invalid login credentials", 400, "invalid_credentials"))
                         .status_code, 401)
        self.assertEqual(self.entrar(httpx.ConnectTimeout("timed out")).status_code, 503)


def token_rechazado_por_supabase():
    """Para otras pruebas: get_anon_client cuyo get_user rechaza el token, sin red."""
    return cliente_auth(get_user=token_rechazado())[0]
