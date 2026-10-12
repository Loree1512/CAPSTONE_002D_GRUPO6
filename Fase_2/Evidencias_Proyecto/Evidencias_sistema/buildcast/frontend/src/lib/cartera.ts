import { ESTADOS } from './catalogos'
import type { EstadoProyecto, Proyecto } from '../tipos/api'

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
