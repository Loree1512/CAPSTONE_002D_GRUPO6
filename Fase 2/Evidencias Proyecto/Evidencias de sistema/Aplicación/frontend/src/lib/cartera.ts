import { ESTADOS } from './catalogos.ts'
import type { EstadoProyecto, Proyecto } from '../tipos/api.ts'

/* Reglas comunes del panel y del listado de proyectos. */

export function estadoDe(p: Proyecto): EstadoProyecto {
  return p.estado ?? 'sin_estimar'
}

export function etiquetaEstado(p: Proyecto): string {
  return ESTADOS[estadoDe(p)].etiqueta
}

export function claseEstado(p: Proyecto): string {
  return ESTADOS[estadoDe(p)].clase
}

export function contarEstado(proyectos: Proyecto[], estado: EstadoProyecto): number {
  return proyectos.filter((p) => estadoDe(p) === estado).length
}

/** Solo suman las estimaciones vigentes: una por recalcular ya no es confiable. */
export function montoCartera(proyectos: Proyecto[]): number {
  return proyectos
    .filter((p) => estadoDe(p) === 'vigente')
    .reduce((suma, p) => suma + (p.costo_total ?? 0), 0)
}

/** Sin estimación o con una estimación que quedó desactualizada. */
export function requiereAtencion(p: Proyecto): boolean {
  const estado = estadoDe(p)
  return estado === 'recalcular' || estado === 'sin_estimar'
}

// Orden de lectura: lo resuelto primero, luego lo que pide acción y al final lo cerrado.
export const ORDEN_ESTADOS: EstadoProyecto[] = ['vigente', 'recalcular', 'sin_estimar', 'ejecutada']

export interface TramoEstado {
  estado: EstadoProyecto
  etiqueta: string
  cantidad: number
  porcentaje: number
}

/** Cuántos proyectos hay en cada estado, para la barra de la cartera. */
export function distribucionEstados(proyectos: Proyecto[]): TramoEstado[] {
  const total = proyectos.length
  return ORDEN_ESTADOS.map((estado) => {
    const cantidad = contarEstado(proyectos, estado)
    return { estado, etiqueta: ESTADOS[estado].etiqueta, cantidad, porcentaje: total ? (cantidad / total) * 100 : 0 }
  })
}

const PRIORIDAD: Record<EstadoProyecto, number> = { recalcular: 0, sin_estimar: 1, vigente: 2, ejecutada: 3 }

const ACCIONES: Record<EstadoProyecto, string> = {
  recalcular: 'Recalcular la estimación',
  sin_estimar: 'Generar la estimación',
  vigente: 'Al día',
  ejecutada: 'Obra cerrada',
}

export function accionSugerida(p: Proyecto): string {
  return ACCIONES[estadoDe(p)]
}

function fecha(p: Proyecto): number {
  const valor = Date.parse(p.actualizado_en ?? p.creado_en ?? '')
  return Number.isNaN(valor) ? 0 : valor
}

/** Lo que pide acción primero; dentro de cada estado, lo más reciente arriba. */
export function ordenarPorPrioridad(proyectos: Proyecto[]): Proyecto[] {
  return [...proyectos].sort((a, b) =>
    PRIORIDAD[estadoDe(a)] - PRIORIDAD[estadoDe(b)] || fecha(b) - fecha(a))
}

export interface MontoTipo {
  tipo: string
  monto: number
  cantidad: number
  /** Respecto del tipo con más monto: es el largo de la barra. */
  porcentaje: number
}

/** Monto vigente por tipo de obra, de mayor a menor. */
export function montoPorTipo(proyectos: Proyecto[]): MontoTipo[] {
  const tipos = new Map<string, { monto: number; cantidad: number }>()
  for (const p of proyectos) {
    if (estadoDe(p) !== 'vigente' || !p.costo_total) continue
    const actual = tipos.get(p.tipo_obra) ?? { monto: 0, cantidad: 0 }
    tipos.set(p.tipo_obra, { monto: actual.monto + p.costo_total, cantidad: actual.cantidad + 1 })
  }
  const filas = [...tipos].map(([tipo, v]) => ({ tipo, ...v })).sort((a, b) => b.monto - a.monto)
  const mayor = filas[0]?.monto ?? 0
  return filas.map((f) => ({ ...f, porcentaje: mayor ? (f.monto / mayor) * 100 : 0 }))
}
