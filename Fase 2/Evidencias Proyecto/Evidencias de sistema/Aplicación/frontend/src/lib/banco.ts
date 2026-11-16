import type { FilaBanco } from '../tipos/api.ts'

/* Reglas del banco de precios que comparten el panel y la pantalla del banco. */

/** Precio de mercado cargado como punto de partida; al corregirlo pasa a ser de la oficina. */
export function esPrecioReferencial(fila: Pick<FilaBanco, 'fuente'>): boolean {
  return (fila.fuente ?? '').toLowerCase().includes('referencial')
}

export interface Cobertura {
  /** Partidas vigentes del catálogo. */
  total: number
  conPrecio: number
  /** Con precio corregido por la oficina. */
  oficina: number
  /** Con precio, pero todavía el de mercado. */
  referencial: number
  sinPrecio: number
  /** Porcentaje de partidas con precio, entero. */
  porcentaje: number
}

export function coberturaBanco(filas: Pick<FilaBanco, 'vigente' | 'precio_unitario' | 'fuente'>[]): Cobertura {
  const vigentes = filas.filter((f) => f.vigente)
  const conPrecio = vigentes.filter((f) => f.precio_unitario != null)
  const referencial = conPrecio.filter(esPrecioReferencial).length
  const total = vigentes.length
  return {
    total,
    conPrecio: conPrecio.length,
    oficina: conPrecio.length - referencial,
    referencial,
    sinPrecio: total - conPrecio.length,
    porcentaje: total ? Math.round((conPrecio.length / total) * 100) : 0,
  }
}
