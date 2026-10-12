"""Motor de costos de BuildCast.

Presupuesto por partidas del proyecto: cantidad × precio unitario, como los
presupuestos de RAM. Las cantidades las define el profesional en cada proyecto y
la mano de obra es una partida más. No consulta Supabase. Mismo cálculo que
frontend/src/lib/motorCosto.ts.

Redondeo (RAM trabaja en pesos enteros): los montos que forman el presupuesto
se llevan a CLP entero con ROUND_HALF_UP, cada uno una sola vez:
  subtotal_base = redondear(cantidad × precio)
  subtotal      = redondear(subtotal_base × factor)
  GG y utilidad = redondear(costo directo × % / 100), cada uno por separado
  total         = suma de montos ya redondeados
Cantidades, precios unitarios, factores y costo por m² no se redondean.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

# Subir cuando cambie una fórmula; se guarda en cada estimación.
VERSION_MOTOR = "2.0.0"

# Estados de una línea. Solo "calculada" suma al costo directo.
CALCULADA = "calculada"
SIN_PRECIO = "sin_precio"
SIN_CANTIDAD = "sin_cantidad"

ORIGENES = ("plantilla", "catalogo", "manual")

# Fuente que se informa cuando la línea usa un precio particular del proyecto.
FUENTE_PRECIO_PROYECTO = "Precio particular del proyecto"

CERO = Decimal(0)
UNO = Decimal(1)
CIEN = Decimal(100)

# Claves de parametros_calculo que usa el motor. Estándar, materialidad y hora
# hombre siguen en la configuración, pero hoy no afectan el costo.
CLAVES_MOTOR = (
    "gastos_generales_pct",
    "utilidad_pct",
    "factores_comuna",
    "tramos_pisos",
)


def redondear_clp(valor: Decimal) -> Decimal:
    """Peso entero, mitades hacia arriba: 93.787,5 → 93.788."""
    return valor.quantize(UNO, rounding=ROUND_HALF_UP)


def a_decimal(valor) -> Optional[Decimal]:
    # Pasar por str() evita arrastrar el error binario del float.
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


# --- Entradas -------------------------------------------------------------------

@dataclass(frozen=True)
class ProyectoEntrada:
    comuna: str
    tipo_obra: str
    materialidad: str
    superficie_m2: Decimal
    numero_pisos: int
    estandar_terminaciones: str


@dataclass(frozen=True)
class CategoriaEntrada:
    id: int
    codigo: str
    nombre: str
    orden: int


@dataclass(frozen=True)
class PartidaProyectoEntrada:
    """Una línea de proyecto_partidas, con su categoría resuelta."""
    id: str
    partida_id: Optional[str]  # None = partida manual
    codigo: Optional[str]  # código del catálogo, si viene de él
    categoria: CategoriaEntrada
    nombre: str
    unidad: str
    cantidad: Optional[Decimal]
    precio_unitario_override: Optional[Decimal]
    origen: str
    orden: int
    observacion: Optional[str] = None


@dataclass(frozen=True)
class PrecioEntrada:
    precio_unitario: Optional[Decimal]
    fuente: Optional[str] = None


@dataclass(frozen=True)
class TramoPisos:
    desde: int
    hasta: int
    factor: Decimal


@dataclass(frozen=True)
class ConfiguracionCalculo:
    gastos_generales_pct: Decimal
    utilidad_pct: Decimal
    factores_comuna: Mapping[str, Decimal]
    tramos_pisos: Tuple[TramoPisos, ...]


class ConfiguracionIncompleta(ValueError):
    pass


def configuracion_desde_parametros(parametros: Mapping[str, object]) -> ConfiguracionCalculo:
    """Arma la configuración desde las filas de parametros_calculo."""
    faltantes = [clave for clave in CLAVES_MOTOR if clave not in parametros]
    if faltantes:
        raise ConfiguracionIncompleta(
            "Falta configurar: " + ", ".join(faltantes) + "."
        )

    return ConfiguracionCalculo(
        gastos_generales_pct=a_decimal(parametros["gastos_generales_pct"]),
        utilidad_pct=a_decimal(parametros["utilidad_pct"]),
        factores_comuna={str(k): a_decimal(v) for k, v in dict(parametros["factores_comuna"]).items()},
        tramos_pisos=tuple(
            TramoPisos(int(t["desde"]), int(t["hasta"]), a_decimal(t["factor"]))
            for t in parametros["tramos_pisos"]
        ),
    )


# --- Resultado ------------------------------------------------------------------

@dataclass(frozen=True)
class FactoresAplicados:
    # Valores usados: todos 1 si no se aplican factores.
    aplicar: bool
    comuna: Decimal
    pisos: Decimal
    ajuste: Decimal


@dataclass(frozen=True)
class LineaCalculada:
    orden: int
    proyecto_partida_id: str
    partida_id: Optional[str]
    codigo: Optional[str]
    nombre: str
    unidad: str
    origen: str
    observacion: Optional[str]
    categoria_id: int
    categoria_codigo: str
    categoria_nombre: str
    categoria_orden: int
    estado: str

    cantidad: Optional[Decimal]
    precio_unitario_base: Optional[Decimal]  # del banco
    precio_unitario_override: Optional[Decimal]
    precio_unitario: Optional[Decimal]  # el finalmente usado, sin factor
    fuente_precio: Optional[str]

    factor_aplicado: Decimal  # comuna × pisos, o 1

    subtotal_base: Decimal  # cantidad × precio, CLP entero
    subtotal: Decimal  # subtotal_base × factor, CLP entero


@dataclass(frozen=True)
class CapituloCalculado:
    codigo: str
    nombre: str
    subtotal: Decimal
    incidencia: Decimal
    lineas: List[LineaCalculada]


@dataclass(frozen=True)
class ResultadoEstimacion:
    version_motor: str
    lineas: List[LineaCalculada]  # todas, también las que no suman
    capitulos: List[CapituloCalculado]  # solo lo que suma
    factores: FactoresAplicados
    costo_directo_base: Decimal
    costo_directo: Decimal
    gastos_generales_pct: Decimal
    gastos_generales: Decimal
    utilidad_pct: Decimal
    utilidad: Decimal
    costo_total: Decimal
    costo_m2: Decimal
    partidas_calculadas: int
    partidas_sin_precio: int
    partidas_sin_cantidad: int
    completa: bool


# --- Reglas por línea (también las usa el listado de partidas del proyecto) ----------

def resolver_precio(override: Optional[Decimal], precio_banco: Optional[Decimal]) -> Optional[Decimal]:
    """El precio particular del proyecto manda sobre el del banco."""
    return override if override is not None else precio_banco


def subtotal_linea(cantidad: Optional[Decimal], precio: Optional[Decimal]) -> Optional[Decimal]:
    """cantidad × precio en CLP entero; None si falta alguno."""
    if cantidad is None or precio is None:
        return None
    return redondear_clp(cantidad * precio)


def estado_linea(cantidad: Optional[Decimal], precio: Optional[Decimal]) -> str:
    # La cantidad la define el profesional: si falta, no se inventa.
    if cantidad is None:
        return SIN_CANTIDAD
    if precio is None:
        return SIN_PRECIO
    return CALCULADA


def factor_pisos(tramos: Sequence[TramoPisos], pisos: int) -> Decimal:
    # Usa el primer tramo que calza; si ninguno calza, 1.
    for tramo in tramos:
        if tramo.desde <= pisos <= tramo.hasta:
            return tramo.factor
    return UNO


def factores_de(proyecto: ProyectoEntrada, configuracion: ConfiguracionCalculo, aplicar: bool) -> FactoresAplicados:
    if not aplicar:
        return FactoresAplicados(aplicar=False, comuna=UNO, pisos=UNO, ajuste=UNO)

    comuna = configuracion.factores_comuna.get(proyecto.comuna, UNO)
    pisos = factor_pisos(configuracion.tramos_pisos, proyecto.numero_pisos or 1)
    return FactoresAplicados(aplicar=True, comuna=comuna, pisos=pisos, ajuste=comuna * pisos)


# --- Cálculo --------------------------------------------------------------------

def calcular_estimacion(
    proyecto: ProyectoEntrada,
    partidas: Sequence[PartidaProyectoEntrada],
    precios: Mapping[str, PrecioEntrada],
    configuracion: ConfiguracionCalculo,
    gastos_generales_pct: Optional[Decimal] = None,
    utilidad_pct: Optional[Decimal] = None,
    aplicar_factores: bool = False,
) -> ResultadoEstimacion:
    """Calcula el presupuesto de un proyecto a partir de sus partidas.

    precios va por partida_id del catálogo y trae el precio de la versión elegida.
    """
    superficie = proyecto.superficie_m2 or CERO
    gg_pct = configuracion.gastos_generales_pct if gastos_generales_pct is None else gastos_generales_pct
    ut_pct = configuracion.utilidad_pct if utilidad_pct is None else utilidad_pct
    factores = factores_de(proyecto, configuracion, aplicar_factores)

    # Capítulo por orden de categoría y, dentro, el orden del proyecto.
    ordenadas = sorted(partidas, key=lambda p: (p.categoria.orden, p.orden))

    lineas: List[LineaCalculada] = []
    for p in ordenadas:
        precio_banco = precios.get(p.partida_id) if p.partida_id else None
        base = precio_banco.precio_unitario if precio_banco else None
        precio = resolver_precio(p.precio_unitario_override, base)
        estado = estado_linea(p.cantidad, precio)

        if p.precio_unitario_override is not None:
            fuente = FUENTE_PRECIO_PROYECTO
        else:
            fuente = precio_banco.fuente if precio_banco else None

        subtotal_base = subtotal_linea(p.cantidad, precio) if estado == CALCULADA else CERO

        lineas.append(LineaCalculada(
            orden=len(lineas) + 1,
            proyecto_partida_id=p.id,
            partida_id=p.partida_id,
            codigo=p.codigo,
            nombre=p.nombre,
            unidad=p.unidad,
            origen=p.origen,
            observacion=p.observacion,
            categoria_id=p.categoria.id,
            categoria_codigo=p.categoria.codigo,
            categoria_nombre=p.categoria.nombre,
            categoria_orden=p.categoria.orden,
            estado=estado,
            cantidad=p.cantidad,
            precio_unitario_base=base,
            precio_unitario_override=p.precio_unitario_override,
            precio_unitario=precio,
            fuente_precio=fuente,
            factor_aplicado=factores.ajuste,
            subtotal_base=subtotal_base,
            subtotal=redondear_clp(subtotal_base * factores.ajuste),
        ))

    calculadas = [l for l in lineas if l.estado == CALCULADA]
    costo_directo_base = sum((l.subtotal_base for l in calculadas), CERO)
    costo_directo = sum((l.subtotal for l in calculadas), CERO)

    capitulos: List[CapituloCalculado] = []
    por_codigo: Dict[str, List[LineaCalculada]] = {}
    for linea in calculadas:
        por_codigo.setdefault(linea.categoria_codigo, []).append(linea)
    for codigo, lineas_capitulo in por_codigo.items():
        subtotal = sum((l.subtotal for l in lineas_capitulo), CERO)
        # Se omiten capítulos sin monto.
        if subtotal > 0:
            capitulos.append(CapituloCalculado(
                codigo=codigo,
                nombre=lineas_capitulo[0].categoria_nombre,
                subtotal=subtotal,
                incidencia=(subtotal / costo_directo) * CIEN if costo_directo else CERO,
                lineas=lineas_capitulo,
            ))

    # GG y utilidad, ambos sobre el costo directo (como RAM).
    # Cada uno se redondea por separado y el total suma lo ya redondeado.
    gastos_generales = redondear_clp(costo_directo * gg_pct / CIEN)
    utilidad = redondear_clp(costo_directo * ut_pct / CIEN)
    costo_total = costo_directo + gastos_generales + utilidad

    sin_precio = sum(1 for l in lineas if l.estado == SIN_PRECIO)
    sin_cantidad = sum(1 for l in lineas if l.estado == SIN_CANTIDAD)

    return ResultadoEstimacion(
        version_motor=VERSION_MOTOR,
        lineas=lineas,
        capitulos=capitulos,
        factores=factores,
        costo_directo_base=costo_directo_base,
        costo_directo=costo_directo,
        gastos_generales_pct=gg_pct,
        gastos_generales=gastos_generales,
        utilidad_pct=ut_pct,
        utilidad=utilidad,
        costo_total=costo_total,
        costo_m2=costo_total / superficie if superficie else CERO,
        partidas_calculadas=len(calculadas),
        partidas_sin_precio=sin_precio,
        partidas_sin_cantidad=sin_cantidad,
        completa=sin_precio == 0 and sin_cantidad == 0,
    )
