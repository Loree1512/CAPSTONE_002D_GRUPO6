/* Datos y reglas puras de la landing: recorrido hacia el presupuesto y perfiles.
   Sin DOM, para poder probarlas desde node. */

/** Las seis etapas del recorrido, en el orden de sus láminas. */
export const ETAPAS = ['Proyecto', 'Documentos', 'Análisis', 'Cantidades', 'Costos', 'Presupuesto'] as const

/** Mismo reparto que las capas fijadas: la etapa i ocupa [i/total, (i+1)/total). */
export function indiceEtapa(avance: number, total: number = ETAPAS.length): number {
  return Math.min(total - 1, Math.max(0, Math.floor(avance * total)))
}

/** Texto del indicador de la cabecera para la etapa i (0-based). */
export function textoEtapa(i: number): string {
  return `0${i + 1} / 0${ETAPAS.length} · ${ETAPAS[i]}`
}

/* Cada perfil: qué mira primero (foco) y qué gana con BuildCast (frase).
   Solo capacidades que la plataforma tiene hoy. */
export const PERFILES = [
  { foco: 'Costo rápido y partidas principales',
    frase: 'Una referencia de costo temprana, sin armar la planilla desde cero.' },
  { foco: 'Desglose y trazabilidad de cada monto',
    frase: 'Cada monto se explica: cantidad, precio unitario y de dónde salió ese precio.' },
  { foco: 'Vista consolidada de la cartera',
    frase: 'Toda la cartera en un panel: qué está vigente y qué hay que recalcular.' },
  { foco: 'Comparación preliminar de alternativas',
    frase: 'Cambia la materialidad o el estándar y compara el costo por m² antes de decidir.' },
  { foco: 'Costo, plazo y estado del proyecto',
    frase: 'Costo, plazo referencial y estado de la estimación, en una sola vista.' },
] as const

/** Pestaña de destino según la tecla (flechas, Inicio, Fin), o null si la tecla no navega. */
export function destinoTecla(tecla: string, actual: number, total: number): number | null {
  if (tecla === 'ArrowDown' || tecla === 'ArrowRight') return (actual + 1) % total
  if (tecla === 'ArrowUp' || tecla === 'ArrowLeft') return (actual - 1 + total) % total
  if (tecla === 'Home') return 0
  if (tecla === 'End') return total - 1
  return null
}
