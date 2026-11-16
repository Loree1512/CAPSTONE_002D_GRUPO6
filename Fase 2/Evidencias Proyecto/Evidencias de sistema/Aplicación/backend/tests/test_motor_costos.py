"""Motor de costos por partidas del proyecto (motor 2.x): cantidad × precio unitario.

Ejecutar desde backend/:
    python -m pytest            (o python -m unittest discover -s tests -v)
"""

import json
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from app.schemas.configuracion import ConfiguracionEditar, ConfiguracionRespuesta
from app.schemas.estimacion import EstimacionCrear, EstimacionRespuesta
from app.schemas.partida_proyecto import PartidaProyectoCrear, PartidaProyectoEditar
from app.services.motor_costos import (
    CALCULADA,
    FUENTE_PRECIO_PROYECTO,
    SIN_CANTIDAD,
    SIN_PRECIO,
    VERSION_MOTOR,
    CategoriaEntrada,
    ConfiguracionIncompleta,
    PartidaProyectoEntrada,
    PrecioEntrada,
    ProyectoEntrada,
    calcular_estimacion,
    configuracion_desde_parametros,
    redondear_clp,
)
from app.services.resumen_proyecto import firma_partidas
from app.services.snapshot_estimacion import a_filas, armar_respuesta

RAIZ = Path(__file__).resolve().parents[2]
SEEDS = RAIZ / "supabase" / "seeds"

# Entradas de fábrica del frontend (catálogo, precios, configuración).
REFERENCIA = json.loads(
    (Path(__file__).parent / "datos" / "referencia_motor_ts.json").read_text(encoding="utf-8"),
    parse_float=Decimal,
)
ENTRADAS = REFERENCIA["entradas"]
_BASE = ENTRADAS["configuracion"]

PARAMETROS = {
    "valor_hora_hombre": _BASE["valorHoraHombre"],
    "gastos_generales_pct": _BASE["gastosGeneralesPct"],
    "utilidad_pct": _BASE["utilidadPct"],
    "factores_comuna": _BASE["factoresComuna"],
    "tramos_pisos": _BASE["tramosPisos"],
    "factores_estandar": _BASE["factoresEstandar"],
    "factores_materialidad": _BASE["factoresMaterial"],
    "capitulos_estandar": ["06", "07"],
    "capitulos_materialidad": ["03", "04"],
}
CONFIGURACION = configuracion_desde_parametros(PARAMETROS)

FUNDACIONES = CategoriaEntrada(3, "03", "Fundaciones", 3)
OBRA_GRUESA = CategoriaEntrada(4, "04", "Obra gruesa y estructura", 4)
PRELIMINARES = CategoriaEntrada(1, "01", "Obras preliminares", 1)

FUENTE_BANCO = "Referencial de mercado 2026-T3"

# Ids con forma de UUID: la respuesta de la API los valida.
PP_1 = "11111111-0000-0000-0000-000000000001"
PP_2 = "11111111-0000-0000-0000-000000000002"
RADIER = "22222222-0000-0000-0000-000000000001"


def proyecto(comuna="Viña del Mar", pisos=2, superficie="20", **extra) -> ProyectoEntrada:
    datos = dict(
        comuna=comuna,
        tipo_obra="Ampliación",
        materialidad="Estructura metálica",
        superficie_m2=Decimal(superficie),
        numero_pisos=pisos,
        estandar_terminaciones="alto",
    )
    datos.update(extra)
    return ProyectoEntrada(**datos)


def partida(id, nombre, cantidad, *, partida_id=None, override=None, categoria=OBRA_GRUESA,
            unidad="m3", orden=1, origen=None, codigo=None) -> PartidaProyectoEntrada:
    return PartidaProyectoEntrada(
        id=id,
        partida_id=partida_id,
        codigo=codigo,
        categoria=categoria,
        nombre=nombre,
        unidad=unidad,
        cantidad=None if cantidad is None else Decimal(str(cantidad)),
        precio_unitario_override=None if override is None else Decimal(str(override)),
        origen=origen or ("manual" if partida_id is None else "catalogo"),
        orden=orden,
    )


def precios(**por_partida) -> dict:
    return {k: PrecioEntrada(Decimal(str(v)), FUENTE_BANCO) for k, v in por_partida.items()}


def ram_1():
    """Costo directo 1.416.670: la mano de obra es una partida más."""
    return [
        partida(PP_1, "Hormigón para radier", 3, partida_id=RADIER, codigo="04.01", orden=1),
        partida(PP_2, "Equipo de trabajo", 1, override=966670, unidad="gl", orden=2),
    ], precios(**{RADIER: 150000})


def ram_2():
    """Costo directo 1.875.750."""
    return [
        partida(PP_1, "Hormigón para radier", "2.5", partida_id=RADIER, orden=1),
        partida(PP_2, "Maestro y ayudante", 1, override=1500000, unidad="gl", orden=2),
    ], precios(**{RADIER: 150300})


class CantidadPorPrecio(unittest.TestCase):

    def test_7_cantidad_por_precio(self):
        r = calcular_estimacion(
            proyecto(),
            [partida("pp-1", "Hormigón radier", 3, partida_id="pt-1")],
            precios(**{"pt-1": 150000}),
            CONFIGURACION,
        )
        linea = r.lineas[0]
        self.assertEqual(linea.estado, CALCULADA)
        self.assertEqual(linea.subtotal_base, Decimal(450000))
        self.assertEqual(linea.subtotal, Decimal(450000))
        self.assertEqual(r.costo_directo, Decimal(450000))
        self.assertEqual(r.version_motor, VERSION_MOTOR)

    def test_5_partida_de_catalogo_usa_precio_del_banco(self):
        r = calcular_estimacion(proyecto(), [partida("pp-1", "Radier", 2, partida_id="pt-1")],
                                precios(**{"pt-1": 16500}), CONFIGURACION)
        linea = r.lineas[0]
        self.assertEqual(linea.precio_unitario_base, Decimal(16500))
        self.assertIsNone(linea.precio_unitario_override)
        self.assertEqual(linea.precio_unitario, Decimal(16500))
        self.assertEqual(linea.fuente_precio, FUENTE_BANCO)

    def test_6_precio_particular_tiene_prioridad(self):
        r = calcular_estimacion(proyecto(), [partida("pp-1", "Radier", 2, partida_id="pt-1", override=20000)],
                                precios(**{"pt-1": 16500}), CONFIGURACION)
        linea = r.lineas[0]
        self.assertEqual(linea.precio_unitario_base, Decimal(16500))  # se conserva para trazabilidad
        self.assertEqual(linea.precio_unitario, Decimal(20000))
        self.assertEqual(linea.subtotal, Decimal(40000))
        self.assertEqual(linea.fuente_precio, FUENTE_PRECIO_PROYECTO)

    def test_override_cero_es_un_precio_valido(self):
        r = calcular_estimacion(proyecto(), [partida("pp-1", "Incluido", 1, partida_id="pt-1", override=0)],
                                precios(**{"pt-1": 16500}), CONFIGURACION)
        self.assertEqual(r.lineas[0].estado, CALCULADA)
        self.assertEqual(r.costo_directo, 0)

    def test_8_sin_cantidad_no_suma_ni_se_inventa(self):
        partidas = [
            partida("pp-1", "Radier", None, partida_id="pt-1"),
            partida("pp-2", "Excavación", 4, partida_id="pt-2", orden=2),
        ]
        r = calcular_estimacion(proyecto(), partidas, precios(**{"pt-1": 16500, "pt-2": 7500}), CONFIGURACION)
        linea = next(l for l in r.lineas if l.proyecto_partida_id == "pp-1")
        self.assertEqual(linea.estado, SIN_CANTIDAD)
        self.assertIsNone(linea.cantidad)
        self.assertEqual((linea.subtotal_base, linea.subtotal), (0, 0))
        self.assertEqual(r.costo_directo, Decimal(30000))
        self.assertEqual(r.partidas_sin_cantidad, 1)
        self.assertFalse(r.completa)

    def test_9_sin_precio_no_suma(self):
        partidas = [
            partida("pp-1", "Radier", 2, partida_id="pt-sin-precio"),
            partida("pp-2", "Manual sin precio", 2),
        ]
        r = calcular_estimacion(proyecto(), partidas, {}, CONFIGURACION)
        self.assertEqual([l.estado for l in r.lineas], [SIN_PRECIO, SIN_PRECIO])
        self.assertEqual(r.costo_directo, 0)
        self.assertEqual(r.partidas_sin_precio, 2)
        self.assertFalse(r.completa)

    def test_cantidad_cero_suma_cero(self):
        r = calcular_estimacion(proyecto(), [partida("pp-1", "Escalera", 0, override=850000)], {}, CONFIGURACION)
        self.assertEqual(r.lineas[0].estado, CALCULADA)
        self.assertTrue(r.completa)
        self.assertEqual(r.capitulos, [])  # capítulo sin monto se omite

    def test_orden_por_categoria_y_orden_del_proyecto(self):
        partidas = [
            partida("b", "Estructura", 1, override=1, categoria=OBRA_GRUESA, orden=1),
            partida("c", "Cimientos 2", 1, override=1, categoria=FUNDACIONES, orden=3),
            partida("a", "Cimientos 1", 1, override=1, categoria=FUNDACIONES, orden=2),
            partida("d", "Faenas", 1, override=1, categoria=PRELIMINARES, orden=9),
        ]
        r = calcular_estimacion(proyecto(), partidas, {}, CONFIGURACION)
        self.assertEqual([l.proyecto_partida_id for l in r.lineas], ["d", "a", "c", "b"])
        self.assertEqual([c.codigo for c in r.capitulos], ["01", "03", "04"])
        self.assertEqual([l.orden for l in r.lineas], [1, 2, 3, 4])


class Factores(unittest.TestCase):

    def test_10_factores_desactivados_valen_1(self):
        # Viña del Mar 1.05 y 2 pisos 1.05, pero sin aplicar.
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION, aplicar_factores=False)
        self.assertFalse(r.factores.aplicar)
        self.assertEqual((r.factores.comuna, r.factores.pisos, r.factores.ajuste), (1, 1, 1))
        self.assertEqual(r.costo_directo, r.costo_directo_base)
        self.assertTrue(all(l.factor_aplicado == 1 for l in r.lineas))

    def test_por_defecto_no_se_aplican(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION)
        self.assertEqual(r.factores.ajuste, 1)

    def test_11_factores_de_comuna_y_pisos(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION, aplicar_factores=True)
        ajuste = Decimal("1.05") * Decimal("1.05")
        self.assertEqual((r.factores.comuna, r.factores.pisos, r.factores.ajuste),
                         (Decimal("1.05"), Decimal("1.05"), ajuste))
        self.assertEqual(r.costo_directo_base, Decimal(1416670))
        radier, equipo = r.lineas
        self.assertEqual((radier.subtotal_base, radier.subtotal), (Decimal(450000), Decimal(496125)))
        # 966.670 × 1,1025 = 1.065.753,675 → 1.065.754
        self.assertEqual((equipo.subtotal_base, equipo.subtotal), (Decimal(966670), Decimal(1065754)))
        # El costo directo suma subtotales ya redondeados.
        self.assertEqual(r.costo_directo, Decimal(1561879))

    def test_comuna_sin_factor_y_tramo_de_pisos(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(comuna="Santiago", pisos=4), partidas, banco, CONFIGURACION,
                                aplicar_factores=True)
        self.assertEqual((r.factores.comuna, r.factores.pisos), (1, Decimal("1.12")))

    def test_estandar_y_materialidad_no_afectan_el_costo(self):
        partidas, banco = ram_1()
        economico = calcular_estimacion(
            proyecto(estandar_terminaciones="economico", materialidad="Albañilería confinada"),
            partidas, banco, CONFIGURACION, aplicar_factores=True,
        )
        alto = calcular_estimacion(
            proyecto(estandar_terminaciones="alto", materialidad="Hormigón armado"),
            partidas, banco, CONFIGURACION, aplicar_factores=True,
        )
        self.assertEqual(economico.costo_total, alto.costo_total)


class GastosGeneralesYUtilidad(unittest.TestCase):
    """Fórmula de los presupuestos de RAM: GG y utilidad, ambos sobre el costo directo."""

    def test_12_a_15_caso_ram_10_y_10(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(superficie="20"), partidas, banco, CONFIGURACION,
                                gastos_generales_pct=Decimal(10), utilidad_pct=Decimal(10))
        self.assertEqual(r.costo_directo, Decimal("1416670"))
        self.assertEqual(r.gastos_generales, Decimal("141667"))
        self.assertEqual(r.utilidad, Decimal("141667"))
        self.assertEqual(r.costo_total, Decimal("1700004"))
        self.assertEqual(r.costo_m2, Decimal("1700004") / Decimal(20))
        self.assertEqual(r.costo_m2, Decimal("85000.2"))

    def test_caso_ram_5_y_7_redondea_gg_y_utilidad_por_separado(self):
        partidas, banco = ram_2()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION,
                                gastos_generales_pct=Decimal(5), utilidad_pct=Decimal(7))
        self.assertEqual(r.costo_directo, Decimal("1875750"))
        self.assertEqual(r.gastos_generales, Decimal("93788"))  # 93.787,5
        self.assertEqual(r.utilidad, Decimal("131303"))  # 131.302,5
        self.assertEqual(r.costo_total, Decimal("2100841"))  # suma de montos redondeados

    def test_montos_en_pesos_enteros(self):
        partidas = [
            partida(PP_1, "Hormigón", "2.35", override="150333"),  # 353.282,55
            partida(PP_2, "Moldaje", "0.5", override="3"),  # 1,5
        ]
        r = calcular_estimacion(proyecto(), partidas, {}, CONFIGURACION,
                                gastos_generales_pct=Decimal("12.5"), utilidad_pct=Decimal(10))
        self.assertEqual([l.subtotal_base for l in r.lineas], [Decimal(353283), Decimal(2)])
        self.assertEqual(r.costo_directo, Decimal(353285))
        self.assertEqual(r.gastos_generales, Decimal(44161))  # 44.160,625
        self.assertEqual(r.utilidad, Decimal(35329))  # 35.328,5
        self.assertEqual(r.costo_total, Decimal(353285 + 44161 + 35329))
        for monto in (r.costo_directo, r.gastos_generales, r.utilidad, r.costo_total):
            self.assertEqual(monto, monto.to_integral_value())
        # Precio y cantidad se guardan tal cual, sin redondear.
        self.assertEqual((r.lineas[0].cantidad, r.lineas[0].precio_unitario), (Decimal("2.35"), Decimal(150333)))

    def test_redondeo_mitad_hacia_arriba(self):
        self.assertEqual(redondear_clp(Decimal("0.5")), 1)
        self.assertEqual(redondear_clp(Decimal("2.5")), 3)  # no es redondeo bancario
        self.assertEqual(redondear_clp(Decimal("2.4999")), 2)

    def test_13_utilidad_no_se_calcula_sobre_cd_mas_gg(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION,
                                gastos_generales_pct=Decimal(10), utilidad_pct=Decimal(10))
        self.assertNotEqual(r.utilidad, (r.costo_directo + r.gastos_generales) * Decimal("0.1"))

    def test_sin_porcentajes_usa_la_configuracion(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION)
        self.assertEqual((r.gastos_generales_pct, r.utilidad_pct), (Decimal(12), Decimal(10)))
        self.assertEqual(r.gastos_generales, Decimal(170000))  # 170.000,4
        self.assertEqual(r.utilidad, Decimal(141667))

    def test_gg_y_utilidad_sobre_costo_directo_con_factores(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION, aplicar_factores=True,
                                gastos_generales_pct=Decimal(10), utilidad_pct=Decimal(10))
        # 1.561.879 × 10 % = 156.187,9
        self.assertEqual(r.gastos_generales, Decimal(156188))
        self.assertEqual(r.utilidad, Decimal(156188))


def guardar_y_leer(resultado, proyecto_entrada, filas_proyecto=()):
    """Resultado → filas de la RPC → JSON (como viaja a Supabase) → respuesta."""
    cabecera, lineas = a_filas(
        resultado,
        proyecto_id="00000000-0000-0000-0000-000000000001",
        proyecto=proyecto_entrada,
        version={"id": "00000000-0000-0000-0000-000000000002", "version": "2026-T3-REF", "fuente": "Referencial"},
        parametros=PARAMETROS,
        firma_partidas=firma_partidas(filas_proyecto),
    )
    cabecera = json.loads(json.dumps(cabecera, default=str))
    lineas = json.loads(json.dumps(lineas, default=str))
    cabecera.update(id="00000000-0000-0000-0000-000000000003", fecha_creacion=datetime.now(timezone.utc))
    return cabecera, lineas


def como_api(cabecera, lineas) -> dict:
    return EstimacionRespuesta.model_validate(armar_respuesta(cabecera, lineas)).model_dump(mode="json", by_alias=True)


class Snapshot(unittest.TestCase):

    def test_filas_guardan_la_trazabilidad_por_linea(self):
        partidas = [
            partida("11111111-0000-0000-0000-000000000001", "Radier", 3, partida_id="22222222-0000-0000-0000-000000000001",
                    override=160000, codigo="04.01", origen="plantilla"),
            partida("11111111-0000-0000-0000-000000000002", "Equipo de trabajo", 1, override=500000, unidad="gl"),
        ]
        banco = precios(**{"22222222-0000-0000-0000-000000000001": 150000})
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION, aplicar_factores=True)
        cabecera, lineas = guardar_y_leer(r, proyecto())

        self.assertEqual(cabecera["aplicar_factores"], True)
        self.assertEqual(Decimal(cabecera["factor_ajuste"]), Decimal("1.1025"))
        self.assertEqual(Decimal(cabecera["costo_directo_base"]), Decimal(980000))
        self.assertEqual(cabecera["parametros_snapshot"], json.loads(json.dumps(PARAMETROS, default=str)))

        radier, equipo = lineas
        self.assertEqual(radier["partida_id"], "22222222-0000-0000-0000-000000000001")
        self.assertEqual(radier["origen"], "plantilla")
        self.assertEqual(radier["codigo_partida"], "04.01")
        self.assertEqual((radier["precio_unitario_banco"], radier["precio_unitario_override"], radier["precio_unitario_usado"]),
                         ("150000", "160000", "160000"))
        self.assertEqual(radier["fuente_precio"], FUENTE_PRECIO_PROYECTO)
        self.assertEqual(Decimal(radier["subtotal_base"]), Decimal(480000))
        self.assertEqual(Decimal(radier["subtotal"]), Decimal(480000) * Decimal("1.1025"))
        self.assertIsNone(equipo["partida_id"])
        self.assertEqual(equipo["origen"], "manual")
        self.assertIsNone(equipo["precio_unitario_banco"])

    def test_16_la_respuesta_sale_de_lo_guardado(self):
        partidas, banco = ram_1()
        r = calcular_estimacion(proyecto(), partidas, banco, CONFIGURACION,
                                gastos_generales_pct=Decimal(10), utilidad_pct=Decimal(10))
        cabecera, lineas = guardar_y_leer(r, proyecto())
        antes = como_api(cabecera, lineas)

        # Cambian las partidas del proyecto y el banco: lo guardado no se mueve.
        partidas[0] = partida(PP_1, "Otro nombre", 99, partida_id=RADIER)
        banco[RADIER] = PrecioEntrada(Decimal(1), "otra")
        despues = como_api(cabecera, lineas)

        self.assertEqual(antes, despues)
        self.assertEqual(despues["total"], 1700004)
        self.assertEqual(despues["gastosGenerales"], 141667)
        self.assertEqual(despues["utilidad"], 141667)
        self.assertEqual(despues["costoDirectoBase"], 1416670)
        linea = despues["capitulos"][0]["lineas"][0]
        self.assertEqual((linea["nombre"], linea["cantidad"], linea["precioUnitario"], linea["subtotal"]),
                         ("Hormigón para radier", 3, 150000, 450000))

    def test_respuesta_lista_partidas_pendientes(self):
        partidas = [
            partida("11111111-0000-0000-0000-000000000001", "Radier", None, partida_id="22222222-0000-0000-0000-000000000001"),
            partida("11111111-0000-0000-0000-000000000002", "Sin precio", 2),
            partida("11111111-0000-0000-0000-000000000003", "Ok", 1, override=10),
        ]
        r = calcular_estimacion(proyecto(), partidas, precios(**{"22222222-0000-0000-0000-000000000001": 1}), CONFIGURACION)
        respuesta = como_api(*guardar_y_leer(r, proyecto()))
        self.assertFalse(respuesta["completa"])
        self.assertEqual([l["nombre"] for l in respuesta["sinCantidad"]], ["Radier"])
        self.assertEqual([l["nombre"] for l in respuesta["sinPrecio"]], ["Sin precio"])
        self.assertEqual((respuesta["partidasSinCantidad"], respuesta["partidasSinPrecio"]), (1, 1))


class ContratoConfiguracion(unittest.TestCase):

    def test_el_motor_solo_exige_sus_claves(self):
        minimas = {clave: PARAMETROS[clave] for clave in
                   ("gastos_generales_pct", "utilidad_pct", "factores_comuna", "tramos_pisos")}
        configuracion_desde_parametros(minimas)
        del minimas["tramos_pisos"]
        with self.assertRaises(ConfiguracionIncompleta):
            configuracion_desde_parametros(minimas)

    def test_acepta_la_configuracion_del_frontend(self):
        cuerpo = json.loads(json.dumps(ENTRADAS["configuracion"], default=float))
        datos = ConfiguracionEditar.model_validate(cuerpo)
        self.assertIsNone(datos.capitulos_estandar)
        respuesta = ConfiguracionRespuesta.model_validate(
            {**datos.model_dump(), "capitulos_estandar": ["06", "07"], "capitulos_materialidad": ["03", "04"]}
        ).model_dump(by_alias=True)
        self.assertEqual(set(respuesta) - set(cuerpo), {"capitulosEstandar", "capitulosMaterialidad"})

    def test_limites_de_gastos_generales_y_utilidad(self):
        base = json.loads(json.dumps(ENTRADAS["configuracion"], default=float))
        validos = [("gastosGeneralesPct", 0), ("gastosGeneralesPct", 25), ("utilidadPct", 0), ("utilidadPct", 30)]
        invalidos = [("gastosGeneralesPct", -0.5), ("gastosGeneralesPct", 25.5), ("utilidadPct", -1), ("utilidadPct", 30.5)]
        for campo, valor in validos:
            with self.subTest(campo=campo, valor=valor):
                ConfiguracionEditar.model_validate({**base, campo: valor})
        for campo, valor in invalidos:
            with self.subTest(campo=campo, valor=valor):
                with self.assertRaises(ValidationError):
                    ConfiguracionEditar.model_validate({**base, campo: valor})


class ContratoSolicitudes(unittest.TestCase):

    def test_estimacion_cuerpo_vacio(self):
        datos = EstimacionCrear.model_validate({})
        self.assertIsNone(datos.gastos_generales_pct)
        self.assertIsNone(datos.utilidad_pct)
        self.assertFalse(datos.aplicar_factores)

    def test_estimacion_limites(self):
        for campo, valor in [("gastos_generales_pct", 25.5), ("utilidad_pct", 30.5), ("utilidad_pct", -1)]:
            with self.subTest(campo=campo):
                with self.assertRaises(ValidationError):
                    EstimacionCrear.model_validate({campo: valor})
        EstimacionCrear.model_validate({"gastos_generales_pct": 25, "utilidad_pct": 30})

    def test_partida_manual_pide_categoria_nombre_unidad_cantidad_y_precio(self):
        completa = {"origen": "manual", "categoria_id": 4, "nombre": " Muro ", "unidad": "m2",
                    "cantidad": 3, "precio_unitario_override": 1000}
        datos = PartidaProyectoCrear.model_validate(completa)
        self.assertEqual(datos.nombre, "Muro")
        for faltante in ("categoria_id", "nombre", "unidad", "cantidad", "precio_unitario_override"):
            with self.subTest(faltante=faltante):
                with self.assertRaises(ValidationError):
                    PartidaProyectoCrear.model_validate({k: v for k, v in completa.items() if k != faltante})

    def test_partida_de_catalogo_pide_partida(self):
        with self.assertRaises(ValidationError):
            PartidaProyectoCrear.model_validate({"origen": "catalogo"})
        datos = PartidaProyectoCrear.model_validate({"origen": "catalogo", "partida_id": "22222222-0000-0000-0000-000000000001"})
        self.assertIsNone(datos.cantidad)

    def test_valores_negativos_se_rechazan(self):
        with self.assertRaises(ValidationError):
            PartidaProyectoEditar.model_validate({"cantidad": -1})
        with self.assertRaises(ValidationError):
            PartidaProyectoEditar.model_validate({"precio_unitario_override": -5})
        with self.assertRaises(ValidationError):
            PartidaProyectoEditar.model_validate({"nombre": "  "})
        # null vacía la cantidad: el motor la marca sin cantidad.
        self.assertIn("cantidad", PartidaProyectoEditar.model_validate({"cantidad": None}).model_fields_set)

    def test_cantidades_decimales_exactas(self):
        datos = PartidaProyectoEditar.model_validate({"cantidad": 0.1})
        self.assertEqual(datos.model_dump(mode="json")["cantidad"], "0.1")


class SeedsIgualesAlTypeScript(unittest.TestCase):

    def leer(self, nombre):
        return (SEEDS / nombre).read_text(encoding="utf-8")

    def test_catalogo_base(self):
        filas = re.findall(r"\('(\d\d)', '(\d\d\.\d\d)', '([^']*)', '(\w+)'\)", self.leer("001_catalogo_base.sql"))
        categoria = {c["id"]: c["codigo"] for c in ENTRADAS["categorias"]}
        esperado = [(categoria[p["categoria_id"]], p["codigo"], p["nombre"], p["unidad"]) for p in ENTRADAS["partidas"]]
        self.assertEqual(filas, esperado)

    def test_precios_referenciales(self):
        filas = re.findall(r"\('(\d\d\.\d\d)', ([\d.]+), ([\d.]+|null)\)", self.leer("002_precios_referenciales.sql"))
        obtenido = {c: (Decimal(p), None if r == "null" else Decimal(r)) for c, p, r in filas}
        esperado = {c: (p, r or None) for c, (p, r) in ENTRADAS["precios"].items()}
        self.assertEqual(obtenido, esperado)

    def test_configuracion(self):
        filas = re.findall(r"\('(\w+)', '(.*?)',\s*\n\s*'", self.leer("003_configuracion_base.sql"), re.DOTALL)
        obtenido = {clave: json.loads(valor, parse_float=Decimal) for clave, valor in filas}
        self.assertEqual(obtenido, PARAMETROS)


class SinMotorAnterior(unittest.TestCase):
    """Una instalación nueva no conoce el concepto de cuantía paramétrica."""

    def test_esquema_seeds_y_codigo_sin_cuantias(self):
        rutas = [
            *(RAIZ / "supabase" / "migrations").glob("*.sql"),
            *SEEDS.glob("*.sql"),
            *(RAIZ / "backend" / "app").rglob("*.py"),
            *(RAIZ / "frontend" / "src").rglob("*.ts"),
            *(RAIZ / "frontend").glob("*.html"),
        ]
        self.assertTrue(rutas)
        con_cuantias = [str(r) for r in rutas if re.search(r"cuant[ií]a", r.read_text(encoding="utf-8"), re.I)]
        self.assertEqual(con_cuantias, [])

    def test_una_sola_migracion_base(self):
        # 001 es la base; las siguientes solo agregan sobre ella.
        migraciones = sorted(p.name for p in (RAIZ / "supabase" / "migrations").glob("*.sql"))
        self.assertEqual(migraciones, [
            "001_schema_buildcast.sql", "002_roles_permisos_auditoria.sql", "003_rls_permisos_proyecto.sql",
            "004_eliminar_proyectos.sql", "005_administracion_usuarios.sql", "006_observaciones_estimacion.sql",
            "007_renovar_invitacion.sql", "008_acceso_configurado.sql", "009_plazo_estimaciones.sql",
            "010_plazo_profesional.sql",
        ])

    def test_seeds_finales(self):
        self.assertEqual(sorted(p.name for p in SEEDS.glob("*.sql")), [
            "001_catalogo_base.sql", "002_precios_referenciales.sql",
            "003_configuracion_base.sql", "004_plantillas_base.sql", "005_valores_uf_cmf.sql",
        ])
        plantillas = (SEEDS / "004_plantillas_base.sql").read_text(encoding="utf-8")
        self.assertNotIn("plantilla_partidas", plantillas)  # nacen vacías


if __name__ == "__main__":
    unittest.main()
