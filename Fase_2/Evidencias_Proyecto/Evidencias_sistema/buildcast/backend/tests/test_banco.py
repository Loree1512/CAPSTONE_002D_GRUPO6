"""Banco de precios: versiones publicadas inmutables y unidad de partidas con precios.

Las RPC del falso reproducen crear_version_precios y publicar_version_precios de 001_schema_buildcast.sql.

Ejecutar desde backend/:
    python -m pytest
"""

import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402

from app.schemas.banco import PartidaEditar, PrecioEditar, VersionPreciosCrear  # noqa: E402
from app.schemas.autenticacion import UsuarioActual  # noqa: E402
from app.services import servicio_banco  # noqa: E402
from app.services.resumen_proyecto import RECALCULAR, VIGENTE, con_resumen, firma_partidas  # noqa: E402
from test_partidas_proyecto import ClienteFalso  # noqa: E402

MIGRACION = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
             / "001_schema_buildcast.sql").read_text(encoding="utf-8")

PUBLICADA = "2026-07-01T10:00:00+00:00"


class BancoFalso(ClienteFalso):

    def _rpc_crear_version_precios(self, p_version, p_copiar_de=None):
        # Una versión nueva siempre nace borrador (sin fecha de publicación).
        nueva = self.insertar("versiones_precios", {"version": p_version, "vigente": False,
                                                    "fecha_publicacion": None, "fuente": None})
        if p_copiar_de:
            for fila in [f for f in self.db["precios_partida"] if f["version_precio_id"] == p_copiar_de]:
                self.insertar("precios_partida", {**copy.deepcopy(fila), "version_precio_id": nueva["id"]})
        return copy.deepcopy(nueva)

    def _rpc_publicar_version_precios(self, p_version_id):
        for v in self.db["versiones_precios"]:
            v["vigente"] = v["id"] == p_version_id
            if v["vigente"] and not v.get("fecha_publicacion"):
                v["fecha_publicacion"] = "2026-09-27T12:00:00+00:00"
        return copy.deepcopy(next(v for v in self.db["versiones_precios"] if v["id"] == p_version_id))


class Banco(unittest.TestCase):

    def setUp(self):
        self.radier = {"id": str(uuid4()), "categoria_id": 4, "codigo": "04.01", "nombre": "Radier",
                       "unidad": "m2", "es_base": True, "vigente": True}
        self.nueva = {"id": str(uuid4()), "categoria_id": 4, "codigo": "04.10", "nombre": "Muro cortina",
                      "unidad": "m2", "es_base": False, "vigente": True}
        self.historica = {"id": str(uuid4()), "version": "2026-T2", "vigente": False, "fecha_publicacion": PUBLICADA}
        self.vigente = {"id": str(uuid4()), "version": "2026-T3", "vigente": True, "fecha_publicacion": PUBLICADA}
        self.borrador = {"id": str(uuid4()), "version": "2026-T4", "vigente": False, "fecha_publicacion": None}
        self.db = {
            "partidas": [self.radier, self.nueva],
            "versiones_precios": [self.historica, self.vigente, self.borrador],
            "categorias_partida": [{"id": 4, "codigo": "04", "vigente": True}, {"id": 6, "codigo": "06", "vigente": True}],
            "precios_partida": [
                {"partida_id": self.radier["id"], "version_precio_id": v["id"], "precio_unitario": 16500,
                 "rendimiento_mo": 0.9, "fuente": "Referencial"}
                for v in (self.historica, self.vigente, self.borrador)
            ],
        }
        self.cliente = BancoFalso(self.db, admin=True)
        parche = patch.object(servicio_banco, "supabase_admin", self.cliente)
        parche.start()
        self.addCleanup(parche.stop)

    def precio(self, version):
        return next(f for f in self.db["precios_partida"]
                    if f["version_precio_id"] == version["id"] and f["partida_id"] == self.radier["id"])

    def editar_precio(self, version, precio=20000):
        return servicio_banco.guardar_precio(version["id"], self.radier["id"],
                                             PrecioEditar(precio_unitario=precio, rendimiento_mo=0.9))

    # --- Versiones -----------------------------------------------------------------

    def test_estados_de_version(self):
        self.assertEqual([servicio_banco.estado_version(v) for v in self.db["versiones_precios"]],
                         ["historica", "vigente", "borrador"])

    def test_borrador_editable(self):
        fila = self.editar_precio(self.borrador)
        self.assertEqual(fila["precio_unitario"], 20000)
        self.assertEqual(self.precio(self.borrador)["precio_unitario"], 20000)

    def test_vigente_no_editable(self):
        antes = dict(self.precio(self.vigente))
        casos = {
            "precio": PrecioEditar(precio_unitario=20000, rendimiento_mo=0.9),
            "rendimiento": PrecioEditar(precio_unitario=16500, rendimiento_mo=2),
            "vaciar": PrecioEditar(precio_unitario=None, rendimiento_mo=None),
        }
        for nombre, datos in casos.items():
            with self.subTest(cambio=nombre):
                with self.assertRaises(HTTPException) as error:
                    servicio_banco.guardar_precio(self.vigente["id"], self.radier["id"], datos)
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn("nueva versión", error.exception.detail)
        self.assertEqual(self.precio(self.vigente), antes)

    def test_la_que_dejo_de_ser_vigente_sigue_bloqueada(self):
        # El borrador se publica: la vigente anterior pasa a histórica y sigue sin editarse.
        servicio_banco.publicar_version(self.borrador["id"])
        self.assertEqual(servicio_banco.estado_version(self.vigente), "historica")
        with self.assertRaises(HTTPException) as error:
            self.editar_precio(self.vigente)
        self.assertEqual(error.exception.status_code, 409)
        # La recién publicada tampoco se edita ya.
        with self.assertRaises(HTTPException):
            self.editar_precio(self.borrador)

    def test_historica_no_editable_y_se_puede_volver_a_marcar_vigente(self):
        with self.assertRaises(HTTPException):
            self.editar_precio(self.historica)
        respuesta = servicio_banco.publicar_version(self.historica["id"])
        self.assertEqual((respuesta["estado"], respuesta["fecha_publicacion"]), ("vigente", PUBLICADA))
        self.assertEqual(self.precio(self.historica)["precio_unitario"], 16500)

    def test_copiar_una_version_publicada_crea_un_borrador_editable(self):
        copia = servicio_banco.crear_version(VersionPreciosCrear(version="2026-T5", copiar_de=self.vigente["id"]))
        self.assertEqual((copia["estado"], copia["fecha_publicacion"], copia["vigente"]), ("borrador", None, False))
        nueva = {"id": str(copia["id"])}
        self.assertEqual(self.precio(nueva)["precio_unitario"], 16500)

        self.editar_precio(nueva, precio=17000)
        self.assertEqual(self.precio(nueva)["precio_unitario"], 17000)
        self.assertEqual(self.precio(self.vigente)["precio_unitario"], 16500)

    def test_publicar_otra_version_pide_recalcular(self):
        proyecto = {"comuna": "Quilpué", "tipo_obra": "Ampliación", "materialidad": "Hormigón armado",
                    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "medio"}
        estimacion = {"id": "e", "fecha_creacion": "2026-09-01", "costo_total": 1, "costo_m2": 1,
                      "version_precio_id": self.vigente["id"], "firma_partidas": firma_partidas([]), **proyecto}
        fila = {**proyecto, "estimaciones": [estimacion], "proyecto_partidas": []}
        self.assertEqual(con_resumen(dict(fila), self.vigente["id"])["estado_estimacion"], VIGENTE)
        self.assertEqual(con_resumen(dict(fila), self.borrador["id"])["estado_estimacion"], RECALCULAR)

    # --- Unidad de partidas -----------------------------------------------------------

    def test_partida_con_precios_no_cambia_unidad(self):
        with self.assertRaises(HTTPException) as error:
            servicio_banco.editar_partida(self.radier["id"], PartidaEditar(unidad="m3"))
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("da de baja", error.exception.detail)
        self.assertEqual(self.radier["unidad"], "m2")

    def test_partida_con_precios_si_cambia_nombre_y_categoria(self):
        # Misma unidad + nombre y categoría: se permite.
        editada = servicio_banco.editar_partida(
            self.radier["id"], PartidaEditar(nombre="Radier de hormigón", categoria_id=6, unidad="m2")
        )
        self.assertEqual((editada["nombre"], editada["categoria_id"], editada["unidad"], editada["codigo"]),
                         ("Radier de hormigón", 6, "m2", "04.01"))

    def test_partida_sin_ningun_precio_si_cambia_unidad(self):
        editada = servicio_banco.editar_partida(self.nueva["id"], PartidaEditar(unidad="ml"))
        self.assertEqual(editada["unidad"], "ml")

    def test_listado_marca_partidas_con_precios(self):
        # En la base es la vista partidas_con_precios; en el falso, las filas de precios.
        self.db["partidas_con_precios"] = [{"partida_id": p} for p in {f["partida_id"] for f in self.db["precios_partida"]}]
        with patch.object(servicio_banco, "get_user_scoped_client", return_value=self.cliente):
            usuario = UsuarioActual(id=uuid4(), email="a@x.cl", access_token="token")
            filas = servicio_banco.listar_banco(usuario, self.borrador["id"])
        self.assertEqual({f["codigo"]: f["tiene_precios"] for f in filas}, {"04.01": True, "04.10": False})

    # --- Respaldo en la base ------------------------------------------------------------

    def test_la_base_tambien_lo_impide(self):
        self.assertIn("fecha_publicacion timestamptz,", MIGRACION)
        self.assertIn("check (not vigente or fecha_publicacion is not null)", MIGRACION)
        self.assertIn("create trigger precios_partida_version_publicada_inmutable", MIGRACION)
        self.assertIn("where v.fecha_publicacion is not null", MIGRACION)
        self.assertIn("fecha_publicacion = coalesce(fecha_publicacion, now())", MIGRACION)
        self.assertIn("create trigger versiones_precios_conservar_publicacion", MIGRACION)
        self.assertIn("before update of unidad on public.partidas", MIGRACION)


if __name__ == "__main__":
    unittest.main()
