"""Lecturas en paralelo: mismo resultado y mismos errores que en serie, pero a la vez.

Ejecutar desde backend/:
    python -m pytest tests/test_concurrencia.py
"""

import os
import threading
import unittest
from datetime import date

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from app.services import servicio_estimaciones  # noqa: E402
from app.services.concurrencia import en_paralelo  # noqa: E402


class EnParaleloTest(unittest.TestCase):
    def test_devuelve_los_resultados_en_el_orden_recibido(self):
        self.assertEqual(en_paralelo(lambda: "a", lambda: "b", lambda: "c"), ["a", "b", "c"])
        self.assertEqual(en_paralelo(), [])
        self.assertEqual(en_paralelo(lambda: 1), [1])

    def test_corren_a_la_vez(self):
        # Cada tarea espera a la otra: en serie la barrera vencería por tiempo.
        barrera = threading.Barrier(3, timeout=5)
        resultado = en_paralelo(*[(lambda i=i: (barrera.wait(), i)[1]) for i in range(3)])
        self.assertEqual(resultado, [0, 1, 2])

    def test_si_varias_fallan_sale_el_error_de_la_primera_en_orden(self):
        def falla(mensaje):
            def tarea():
                raise ValueError(mensaje)
            return tarea

        with self.assertRaises(ValueError) as error:
            en_paralelo(lambda: 1, falla("primero"), falla("segundo"))
        self.assertEqual(str(error.exception), "primero")

    def test_el_error_conserva_su_tipo(self):
        from fastapi import HTTPException
        def tarea():
            raise HTTPException(status_code=409, detail="sin versión")
        with self.assertRaises(HTTPException) as error:
            en_paralelo(lambda: 1, tarea)
        self.assertEqual(error.exception.status_code, 409)


class UfPrecargadaTest(unittest.TestCase):
    HOY = date(2026, 11, 5)

    def test_hoy_usa_la_uf_ya_leida(self):
        self.assertEqual(servicio_estimaciones._uf_para(self.HOY, self.HOY, (41274.2, None)), 41274.2)

    def test_hoy_sin_uf_devuelve_none(self):
        self.assertIsNone(servicio_estimaciones._uf_para(self.HOY, self.HOY, (None, None)))

    def test_un_error_de_lectura_se_relanza_dentro_del_estimador(self):
        # El estimador captura cualquier excepción de buscar_uf: el plazo queda de respaldo.
        with self.assertRaises(RuntimeError):
            servicio_estimaciones._uf_para(self.HOY, self.HOY, (None, RuntimeError("base caída")))

    def test_precargar_no_lanza_y_entrega_el_error(self):
        from unittest.mock import patch
        with patch.object(servicio_estimaciones.estimador_plazo, "buscar_uf", side_effect=RuntimeError("x")):
            valor, error = servicio_estimaciones._precargar_uf(self.HOY)
        self.assertIsNone(valor)
        self.assertIsInstance(error, RuntimeError)


if __name__ == "__main__":
    unittest.main()
