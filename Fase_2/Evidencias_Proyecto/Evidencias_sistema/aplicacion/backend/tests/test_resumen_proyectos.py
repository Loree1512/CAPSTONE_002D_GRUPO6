"""Resumen de la última estimación en GET /proyectos y GET /proyectos/{id}.

Ejecutar desde backend/:
    python -m unittest discover -s tests -v
"""

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

# Valores ficticios antes de importar app.database: las pruebas nunca tocan Supabase.
os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402
from supabase import create_client  # noqa: E402

from app.schemas.autenticacion import UsuarioActual  # noqa: E402
from app.schemas.proyecto import ProyectoActualizar, ProyectoRespuesta  # noqa: E402
from app.services import servicio_proyectos  # noqa: E402
from app.services.resumen_proyecto import (  # noqa: E402
    CAMPOS_SNAPSHOT,
    RECALCULAR,
    SIN_ESTIMAR,
    VIGENTE,
    con_resumen,
    firma_partidas,
)

V1 = "11111111-1111-1111-1111-111111111111"
V2 = "22222222-2222-2222-2222-222222222222"


def proyecto(fecha_actualizacion="2026-09-01T10:00:00+00:00", estimaciones=None, **extra):
    fila = {
        "id": str(uuid4()),
        "usuario_id": str(uuid4()),
        "nombre": "Casa Bravo",
        "comuna": "Villa Alemana",
        "tipo_obra": "Vivienda unifamiliar",
        "materialidad": "Albañilería confinada",
        "superficie_m2": 142,
        "numero_pisos": 2,
        "estandar_terminaciones": "medio",
        "estado": "borrador",
        "fecha_creacion": "2026-09-01T09:00:00+00:00",
        "fecha_actualizacion": fecha_actualizacion,
        **extra,
    }
    if estimaciones is not None:
        fila["estimaciones"] = estimaciones
    return fila


PARTIDAS = [
    {"id": "aaaaaaaa-0000-0000-0000-000000000001", "partida_id": "bbbbbbbb-0000-0000-0000-000000000001",
     "cantidad": 3, "precio_unitario_override": None},
    {"id": "aaaaaaaa-0000-0000-0000-000000000002", "partida_id": None,
     "cantidad": 1, "precio_unitario_override": 966670},
]


def estimacion(fecha="2026-09-01T11:00:00.123456+00:00", version=V1, total=89318414.24, m2=629002.92, de=None,
               partidas=()):
    """Estimación cuyo snapshot son los datos de `de` (por defecto, los de proyecto()) y esas partidas."""
    datos = de or proyecto()
    return {
        "id": str(uuid4()), "fecha_creacion": fecha, "version_precio_id": version,
        "costo_total": total, "costo_m2": m2, "firma_partidas": firma_partidas(partidas),
        **{campo: datos[campo] for campo in CAMPOS_SNAPSHOT},
    }


class EstadoEstimacion(unittest.TestCase):

    def test_sin_estimaciones(self):
        r = con_resumen(proyecto(estimaciones=[]), V1)
        self.assertEqual(r["estado_estimacion"], SIN_ESTIMAR)
        for campo in ("ultima_estimacion_id", "costo_total", "costo_m2", "fecha_estimacion", "plazo_dias"):
            self.assertIsNone(r[campo], campo)

    def test_1_proyecto_sin_modificar_es_vigente(self):
        e = estimacion()
        r = con_resumen(proyecto(estimaciones=[e]), V1)
        self.assertEqual(r["estado_estimacion"], VIGENTE)
        self.assertEqual(r["ultima_estimacion_id"], e["id"])
        self.assertEqual((r["costo_total"], r["costo_m2"]), (89318414.24, 629002.92))
        self.assertEqual(r["fecha_estimacion"], e["fecha_creacion"])
        self.assertIsNone(r["plazo_dias"])

    def test_fecha_de_actualizacion_ya_no_decide(self):
        # Editado "después" según la fecha, pero con los mismos datos.
        r = con_resumen(proyecto("2026-12-31T23:59:59+00:00", [estimacion()]), V1)
        self.assertEqual(r["estado_estimacion"], VIGENTE)

    def test_numeros_se_comparan_por_valor(self):
        # numeric puede volver como 142.0 en un lado y 142 en el otro.
        e = {**estimacion(), "superficie_m2": 142.0}
        self.assertEqual(con_resumen(proyecto(estimaciones=[e]), V1)["estado_estimacion"], VIGENTE)

    def test_3_cambio_de_superficie(self):
        r = con_resumen(proyecto(estimaciones=[estimacion()], superficie_m2=150), V1)
        self.assertEqual(r["estado_estimacion"], RECALCULAR)

    def test_4_cambio_de_comuna(self):
        r = con_resumen(proyecto(estimaciones=[estimacion()], comuna="Quilpué"), V1)
        self.assertEqual(r["estado_estimacion"], RECALCULAR)

    def test_cambio_de_cualquier_dato_del_snapshot(self):
        cambios = {
            "tipo_obra": "Ampliación", "materialidad": "Hormigón armado",
            "numero_pisos": 3, "estandar_terminaciones": "alto",
        }
        for campo, valor in cambios.items():
            with self.subTest(campo=campo):
                r = con_resumen(proyecto(estimaciones=[estimacion()], **{campo: valor}), V1)
                self.assertEqual(r["estado_estimacion"], RECALCULAR)

    def test_5_nueva_version_vigente(self):
        r = con_resumen(proyecto(estimaciones=[estimacion(version=V1)]), V2)
        self.assertEqual(r["estado_estimacion"], RECALCULAR)
        # Sin versión vigente no hay con qué recalcular.
        r = con_resumen(proyecto(estimaciones=[estimacion(version=V1)]), None)
        self.assertEqual(r["estado_estimacion"], VIGENTE)

    def test_6_recalcular_despues_del_cambio_vuelve_a_vigente(self):
        editado = proyecto(superficie_m2=150)
        self.assertEqual(con_resumen({**editado, "estimaciones": [estimacion()]}, V1)["estado_estimacion"], RECALCULAR)
        # La nueva estimación guarda los datos actuales y pasa a ser la última.
        nueva = estimacion("2026-09-02T12:00:00+00:00", de=editado)
        self.assertEqual(con_resumen({**editado, "estimaciones": [nueva]}, V1)["estado_estimacion"], VIGENTE)

    def test_17_cambios_en_partidas_piden_recalcular(self):
        e = estimacion(partidas=PARTIDAS)
        con = lambda partidas: con_resumen(proyecto(estimaciones=[e], proyecto_partidas=partidas), V1)["estado_estimacion"]

        self.assertEqual(con([dict(p) for p in PARTIDAS]), VIGENTE)
        cambios = {
            "cantidad": [{**PARTIDAS[0], "cantidad": 4}, PARTIDAS[1]],
            "precio particular": [PARTIDAS[0], {**PARTIDAS[1], "precio_unitario_override": 1}],
            "precio particular quitado": [PARTIDAS[0], {**PARTIDAS[1], "precio_unitario_override": None}],
            "cantidad vaciada": [{**PARTIDAS[0], "cantidad": None}, PARTIDAS[1]],
            "partida quitada": [PARTIDAS[0]],
            "partida agregada": [*PARTIDAS, {"id": str(uuid4()), "partida_id": None, "cantidad": 1,
                                             "precio_unitario_override": 5}],
        }
        for motivo, partidas in cambios.items():
            with self.subTest(motivo=motivo):
                self.assertEqual(con(partidas), RECALCULAR)

    def test_cambios_sin_efecto_en_el_costo_no_piden_recalcular(self):
        e = estimacion(partidas=PARTIDAS)
        # Otro orden, 3.0 en vez de 3, y columnas que no cambian el costo.
        partidas = [
            {**PARTIDAS[1], "nombre": "Otro nombre", "orden": 1, "observacion": "nota"},
            {**PARTIDAS[0], "cantidad": 3.0, "orden": 2},
        ]
        r = con_resumen(proyecto(estimaciones=[e], proyecto_partidas=partidas), V1)
        self.assertEqual(r["estado_estimacion"], VIGENTE)
        self.assertNotIn("proyecto_partidas", r)

    def test_usa_la_mas_reciente(self):
        # PostgREST entrega la última (orden + límite por proyecto); se toma esa fila.
        reciente = estimacion("2026-09-02T12:00:00+00:00", total=90434894.42)
        r = con_resumen(proyecto(estimaciones=[reciente]), V1)
        self.assertEqual((r["ultima_estimacion_id"], r["costo_total"]), (reciente["id"], 90434894.42))

    def test_consulta_ordena_y_limita_por_proyecto(self):
        cliente = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"])
        consulta = servicio_proyectos._con_ultima_estimacion(
            cliente.postgrest.from_("proyectos").select(servicio_proyectos.SELECT_CON_RESUMEN)
        )
        params = consulta.request.params
        self.assertEqual(params["estimaciones.order"], "fecha_creacion.desc,id.desc")
        self.assertEqual(params["estimaciones.limit"], "1")
        # El snapshot y la firma de partidas vienen en la misma consulta embebida.
        embebida = params["select"].split("estimaciones(")[1].split(")")[0]
        for campo in (*CAMPOS_SNAPSHOT, "firma_partidas"):
            self.assertIn(campo, embebida)
        self.assertIn("proyecto_partidas(id,partida_id,cantidad,precio_unitario_override)", params["select"])

    def test_respuesta_de_proyecto_recien_creado(self):
        r = ProyectoRespuesta.model_validate(con_resumen(proyecto(), None)).model_dump(mode="json")
        self.assertEqual(r["estado_estimacion"], "sin_estimar")
        self.assertIsNone(r["ultima_estimacion_id"])
        self.assertIsNone(r["costo_total"])
        self.assertNotIn("estimaciones", r)


# --- Cliente falso que imita a PostgREST con RLS ----------------------------------

class _Respuesta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    def __init__(self, cliente, tabla):
        self.cliente, self.tabla, self.filtros, self.una, self.cambios = cliente, tabla, {}, False, None

    def update(self, cambios):
        self.cambios = cambios
        return self

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def eq(self, columna, valor):
        self.filtros[columna] = valor
        return self

    def maybe_single(self):
        self.una = True
        return self

    def execute(self):
        self.cliente.consultas.append(self.tabla)
        filas = [f for f in self.cliente.datos.get(self.tabla, [])
                 if all(str(f.get(c)) == str(v) for c, v in self.filtros.items())]
        if self.cambios is not None:
            for fila in filas:
                fila.update(self.cambios)
                # Igual que el trigger: toda actualización mueve la fecha.
                fila["fecha_actualizacion"] = "2026-12-31T23:59:59+00:00"
        if self.una:
            return _Respuesta(filas[0]) if filas else None
        return _Respuesta(filas)


class _ClienteRLS:
    """Devuelve solo lo que RLS dejaría ver al dueño del token."""

    def __init__(self, token, proyectos, versiones):
        dueño = token.removeprefix("token-")
        self.consultas = []
        self.datos = {
            "proyectos": [p for p in proyectos if p["usuario_id"] == dueño],
            "versiones_precios": versiones,
        }

    def table(self, nombre):
        return _Consulta(self, nombre)


class SeguridadYConsultas(unittest.TestCase):

    def setUp(self):
        self.a = UsuarioActual(id=uuid4(), email="a@x.cl", access_token="")
        self.b = UsuarioActual(id=uuid4(), email="b@x.cl", access_token="")
        self.a.access_token = f"token-{self.a.id}"
        self.b.access_token = f"token-{self.b.id}"

        self.proyecto_a = proyecto(estimaciones=[estimacion()], usuario_id=str(self.a.id))
        self.proyecto_b = proyecto(estimaciones=[], usuario_id=str(self.b.id))
        self.clientes = []

        def cliente_de(token):
            cliente = _ClienteRLS(token, [self.proyecto_a, self.proyecto_b], [{"id": V1, "vigente": True}])
            self.clientes.append((token, cliente))
            return cliente

        parche = patch.object(servicio_proyectos, "get_user_scoped_client", side_effect=cliente_de)
        parche.start()
        self.addCleanup(parche.stop)

    def test_6_usuario_no_ve_datos_ajenos(self):
        lista_b = servicio_proyectos.obtener_proyectos(self.b)
        self.assertEqual([p["id"] for p in lista_b], [self.proyecto_b["id"]])
        self.assertEqual(lista_b[0]["estado_estimacion"], SIN_ESTIMAR)
        self.assertIsNone(lista_b[0]["costo_total"])

        # El proyecto de A, pedido por B, responde 404 como cualquier inexistente.
        with self.assertRaises(HTTPException) as error:
            servicio_proyectos.obtener_proyecto_por_id(self.b, self.proyecto_a["id"])
        self.assertEqual(error.exception.status_code, 404)

        # Todas las consultas usan el token del usuario, nunca el service role.
        self.assertTrue(all(token == self.b.access_token for token, _ in self.clientes))
        self.assertFalse(hasattr(servicio_proyectos, "supabase_admin"))

    def _put(self, **cambios):
        datos = {campo: self.proyecto_a[campo] for campo in (*CAMPOS_SNAPSHOT, "nombre")}
        datos.update(cambios)
        return servicio_proyectos.actualizar_proyecto(
            self.a, self.proyecto_a["id"], ProyectoActualizar.model_validate(datos)
        )

    def test_2_put_con_los_mismos_valores_sigue_vigente(self):
        antes = self.proyecto_a["fecha_actualizacion"]
        r = self._put()
        self.assertNotEqual(self.proyecto_a["fecha_actualizacion"], antes)  # el "trigger" movió la fecha
        self.assertEqual(r["estado_estimacion"], VIGENTE)

    def test_put_con_cambio_real_pide_recalcular(self):
        self.assertEqual(self._put(superficie_m2=150)["estado_estimacion"], RECALCULAR)

    def test_listado_hace_dos_consultas(self):
        lista_a = servicio_proyectos.obtener_proyectos(self.a)
        self.assertEqual(lista_a[0]["estado_estimacion"], VIGENTE)
        consultas = [c for _, cliente in self.clientes for c in cliente.consultas]
        # Proyectos (con su última estimación embebida) + versión vigente, sin importar cuántos proyectos haya.
        self.assertEqual(consultas, ["proyectos", "versiones_precios"])


if __name__ == "__main__":
    unittest.main()
