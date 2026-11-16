import type { RolProyecto } from '../tipos/api.ts'

/* Observaciones de la cotización: texto plano que se guarda con cada estimación.
   Cambiarlas no altera el costo, así que no pide recalcular. */

/** Mismo tope que el backend y el CHECK de la migración 006. */
export const OBSERVACIONES_MAX = 1000

/** Como el backend: sin espacios sobrantes; vacía es null. */
export function normalizarObservaciones(texto: string | null | undefined): string | null {
  const limpio = (texto ?? '').replace(/\r\n/g, '\n').trim()
  return limpio || null
}

export function observacionesCambiaron(formulario: string | null | undefined, guardadas: string | null | undefined): boolean {
  return normalizarObservaciones(formulario) !== normalizarObservaciones(guardadas)
}

export function errorObservaciones(texto: string | null | undefined): string {
  const limpio = normalizarObservaciones(texto)
  return limpio && limpio.length > OBSERVACIONES_MAX
    ? `Las observaciones admiten hasta ${OBSERVACIONES_MAX} caracteres.`
    : ''
}

/** Lector: solo visualiza. */
export function puedeEditarObservaciones(rol: RolProyecto | null | undefined): boolean {
  return rol === 'propietario' || rol === 'editor'
}

/** Plazo para la cotización: misma regla que las observaciones (y que RolProyecto.editor en
 *  el backend). Propietario o editor lo definen; el lector solo lo ve. */
export function puedeEditarPlazo(rol: RolProyecto | null | undefined): boolean {
  return puedeEditarObservaciones(rol)
}

/** generar: no hay estimación; recalcular: cambió algo que afecta el costo (lleva la
 *  observación consigo); actualizar: solo cambió la observación; null: nada que hacer. */
export type AccionCotizacion = 'generar' | 'recalcular' | 'actualizar' | null

export function accionCotizacion(estado: {
  hayEstimacion: boolean
  costoPendiente: boolean
  observacionCambio: boolean
}): AccionCotizacion {
  if (!estado.hayEstimacion) return 'generar'
  if (estado.costoPendiente) return 'recalcular'
  return estado.observacionCambio ? 'actualizar' : null
}
