import { factorPisos } from './configuracion'
import type { Configuracion } from './configuracion'
import type { EstadoPartida, PartidaProyecto, Proyecto } from '../tipos/api'

/* Motor de costo de BuildCast: presupuesto por partidas del proyecto.

   subtotal = cantidad × precio unitario (el particular del proyecto si hay,
   si no el del banco). Los factores de comuna y pisos son opcionales.
   GG y utilidad se calculan, ambos, sobre el costo directo.

   Es el mismo cálculo que backend/app/services/motor_costos.py. Aquí lo usan
   el modo demostración y los subtotales en vivo de la tabla de partidas; con
   la API real, la estimación que vale es la que guarda el backend.

   Redondeo: los montos del presupuesto van en CLP entero, mitades hacia
   arriba, cada uno una sola vez (subtotal base, subtotal con factor, GG y
   utilidad por separado). El total suma montos ya redondeados. */

/** Peso entero, mitades hacia arriba (93.787,5 → 93.788). Los montos son ≥ 0.
 *  toPrecision(15) descarta el ruido binario del double (2,675 × 100 = 267,4999…). */
export function redondearClp(valor: number): number {
  return Math.round(Number(valor.toPrecision(15)))
}

/** El precio particular del proyecto manda sobre el del banco. */
export function precioResuelto(override: number | null, banco: number | null): number | null {
  return override ?? banco
}

/** La cantidad la define el profesional: si falta, no se inventa. */
export function estadoPartida(cantidad: number | null, precio: number | null): EstadoPartida {
  if (cantidad == null) return 'sin_cantidad'
  if (precio == null) return 'sin_precio'
  return 'calculada'
}

export function subtotalPartida(cantidad: number | null, precio: number | null): number | null {
  return cantidad != null && precio != null ? redondearClp(cantidad * precio) : null
}

/* --- Presupuesto --------------------------------------------------------- */

export type LineaEntrada = Pick<
  PartidaProyecto,
  | 'id' | 'partida_id' | 'codigo' | 'categoria_codigo' | 'categoria_nombre' | 'categoria_orden'
  | 'nombre' | 'unidad' | 'cantidad' | 'precio_unitario_override' | 'precio_banco' | 'origen' | 'orden' | 'observacion'
> & { fuente_banco?: string | null }

export interface LineaPresupuesto {
  entrada: LineaEntrada
  estado: EstadoPartida
  precioUnitario: number | null
  fuentePrecio: string | null
  factorAplicado: number
  subtotalBase: number
  subtotal: number
}

export interface CapituloPresupuesto {
  codigo: string
  nombre: string
  subtotal: number
  incidencia: number
  lineas: LineaPresupuesto[]
}

export interface FactoresAplicados {
  aplicar: boolean
  comuna: number
  pisos: number
  ajuste: number
}

export interface Presupuesto {
  lineas: LineaPresupuesto[]
  capitulos: CapituloPresupuesto[]
  costoDirectoBase: number
  costoDirecto: number
  gastosGeneralesPct: number
  gastosGenerales: number
  utilidadPct: number
  utilidad: number
  total: number
  costoM2: number
  factores: FactoresAplicados
  partidasSinPrecio: number
  partidasSinCantidad: number
  completa: boolean
}

export const FUENTE_PRECIO_PROYECTO = 'Precio particular del proyecto'

export interface OpcionesPresupuesto {
  gastosGeneralesPct?: number
  utilidadPct?: number
  aplicarFactores?: boolean
}

export function calcularPresupuesto(
  proyecto: Pick<Proyecto, 'superficie_m2' | 'pisos' | 'comuna'>,
  partidas: LineaEntrada[],
  config: Pick<Configuracion, 'gastosGeneralesPct' | 'utilidadPct' | 'factoresComuna' | 'tramosPisos'>,
  opciones: OpcionesPresupuesto = {},
): Presupuesto {
  const superficie = Number(proyecto.superficie_m2) || 0
  const gg = opciones.gastosGeneralesPct ?? config.gastosGeneralesPct
  const ut = opciones.utilidadPct ?? config.utilidadPct

  const aplicar = opciones.aplicarFactores ?? false
  const comuna = aplicar ? (config.factoresComuna[proyecto.comuna] ?? 1) : 1
  const pisos = aplicar ? factorPisos(config, Number(proyecto.pisos) || 1) : 1
  const factores: FactoresAplicados = { aplicar, comuna, pisos, ajuste: comuna * pisos }

  const ordenadas = [...partidas].sort((a, b) => a.categoria_orden - b.categoria_orden || a.orden - b.orden)

  const lineas: LineaPresupuesto[] = ordenadas.map((p) => {
    const precio = precioResuelto(p.precio_unitario_override, p.precio_banco)
    const estado = estadoPartida(p.cantidad, precio)
    const subtotalBase = estado === 'calculada' ? (subtotalPartida(p.cantidad, precio) as number) : 0
    return {
      entrada: p,
      estado,
      precioUnitario: precio,
      fuentePrecio: p.precio_unitario_override != null ? FUENTE_PRECIO_PROYECTO : (p.fuente_banco ?? null),
      factorAplicado: factores.ajuste,
      subtotalBase,
      subtotal: redondearClp(subtotalBase * factores.ajuste),
    }
  })

  const calculadas = lineas.filter((l) => l.estado === 'calculada')
  const costoDirectoBase = calculadas.reduce((suma, l) => suma + l.subtotalBase, 0)
  const costoDirecto = calculadas.reduce((suma, l) => suma + l.subtotal, 0)

  const capitulos: CapituloPresupuesto[] = []
  for (const l of calculadas) {
    let capitulo = capitulos.find((c) => c.codigo === l.entrada.categoria_codigo)
    if (!capitulo) {
      capitulo = { codigo: l.entrada.categoria_codigo, nombre: l.entrada.categoria_nombre, subtotal: 0, incidencia: 0, lineas: [] }
      capitulos.push(capitulo)
    }
    capitulo.lineas.push(l)
    capitulo.subtotal += l.subtotal
  }
  const conMonto = capitulos.filter((c) => c.subtotal > 0)
  conMonto.forEach((c) => { c.incidencia = costoDirecto ? (c.subtotal / costoDirecto) * 100 : 0 })

  // GG y utilidad, ambos sobre el costo directo (como RAM).
  const gastosGenerales = redondearClp(costoDirecto * gg / 100)
  const utilidad = redondearClp(costoDirecto * ut / 100)
  const total = costoDirecto + gastosGenerales + utilidad

  const partidasSinPrecio = lineas.filter((l) => l.estado === 'sin_precio').length
  const partidasSinCantidad = lineas.filter((l) => l.estado === 'sin_cantidad').length

  return {
    lineas,
    capitulos: conMonto,
    costoDirectoBase,
    costoDirecto,
    gastosGeneralesPct: gg,
    gastosGenerales,
    utilidadPct: ut,
    utilidad,
    total,
    costoM2: superficie ? total / superficie : 0,
    factores,
    partidasSinPrecio,
    partidasSinCantidad,
    completa: partidasSinPrecio === 0 && partidasSinCantidad === 0,
  }
}
