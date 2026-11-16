"""UF vigente del Panel: sale de valores_uf y nunca de una fecha que aún no llega.

Ejecutar desde backend/:
    python -m pytest tests/test_uf_vigente.py
"""

import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import autenticacion as dependencias  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.autenticacion import RolGlobal, UsuarioActual  # noqa: E402
from app.services import servicio_configuracion  # noqa: E402


class ClienteUf:
    """Imita la consulta a valores_uf: filtro lte, orden descendente, límite."""

    def __init__(self, filas):
        self.filas, self.consultas, self._tope, self._limite = filas, [], None, None

    def table(self, nombre):
        self.consultas.append(nombre)
        return self

    def select(self, _columnas):
        return self

    def lte(self, columna, valor):
        assert columna == "fecha"
        self._tope = valor
        return self

    def order(self, columna, desc=False):
        assert columna == "fecha" and desc
        return self

    def limit(self, n):
        self._limite = n
        return self

    def execute(self):
        filas = [f for f in self.filas if self._tope is None or f["fecha"] <= self._tope]
        filas.sort(key=lambda f: f["fecha"], reverse=True)
        return SimpleNamespace(data=filas[: self._limite])


SERIE = [
    {"fecha": "2026-11-03", "valor": "41263.57"},
    {"fecha": "2026-11-05", "valor": "41274.20"},
    {"fecha": "2026-11-09", "valor": "41300.00"},  # ya cargada, pero todavía no corresponde
]


class UfVigenteTest(unittest.TestCase):
    def test_elige_la_uf_del_dia(self):
        uf = servicio_configuracion.buscar_uf_vigente(ClienteUf(SERIE), date(2026, 11, 5))
        self.assertEqual(uf, {"valor": 41274.20, "fecha": "2026-11-05"})

    def test_no_usa_una_uf_futura_aunque_sea_la_fecha_maxima(self):
        uf = servicio_configuracion.buscar_uf_vigente(ClienteUf(SERIE), date(2026, 11, 7))
        self.assertEqual(uf["fecha"], "2026-11-05")
        self.assertEqual(uf["valor"], 41274.20)

    def test_un_dia_sin_fila_usa_la_anterior(self):
        uf = servicio_configuracion.buscar_uf_vigente(ClienteUf(SERIE), date(2026, 11, 4))
        self.assertEqual(uf["fecha"], "2026-11-03")

    def test_llega_el_dia_de_una_uf_ya_cargada(self):
        uf = servicio_configuracion.buscar_uf_vigente(ClienteUf(SERIE), date(2026, 11, 9))
        self.assertEqual(uf["valor"], 41300.00)

    def test_sin_uf_disponible(self):
        self.assertEqual(servicio_configuracion.buscar_uf_vigente(ClienteUf([]), date(2026, 11, 5)),
                         {"valor": None, "fecha": None})
        solo_futura = ClienteUf([{"fecha": "2026-12-01", "valor": "41500"}])
        self.assertEqual(servicio_configuracion.buscar_uf_vigente(solo_futura, date(2026, 11, 5)),
                         {"valor": None, "fecha": None})

    def test_lee_solo_valores_uf(self):
        cliente = ClienteUf(SERIE)
        servicio_configuracion.buscar_uf_vigente(cliente, date(2026, 11, 5))
        self.assertEqual(cliente.consultas, ["valores_uf"])


class EndpointUfVigenteTest(unittest.TestCase):
    def setUp(self):
        usuario = UsuarioActual(id="00000000-0000-0000-0000-000000000001", email="a@b.cl", access_token="t", rol_global=RolGlobal.profesional)
        app.dependency_overrides[dependencias.obtener_sesion] = lambda: usuario
        app.dependency_overrides[dependencias.obtener_usuario_actual] = lambda: usuario
        self.http = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _pedir(self, filas, hoy):
        with patch.object(servicio_configuracion, "get_user_scoped_client", return_value=ClienteUf(filas)), \
             patch.object(servicio_configuracion, "fecha_chile", return_value=hoy):
            return self.http.get("/configuracion/uf-vigente")

    def test_responde_valor_fecha_y_fuente(self):
        r = self._pedir(SERIE, date(2026, 11, 7))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"valor": 41274.2, "fecha": "2026-11-05", "fuente": "CMF"})

    def test_sin_uf_responde_nulos_sin_error(self):
        r = self._pedir([], date(2026, 11, 7))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"valor": None, "fecha": None, "fuente": "CMF"})

    def test_exige_sesion(self):
        app.dependency_overrides.clear()
        self.assertIn(TestClient(app).get("/configuracion/uf-vigente").status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
