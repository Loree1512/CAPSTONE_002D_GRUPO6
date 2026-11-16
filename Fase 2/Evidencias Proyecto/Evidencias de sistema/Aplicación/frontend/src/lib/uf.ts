import type { PlazoEstimacion } from '../tipos/estimacion.ts'

/* Presentación de la UF. Son dos conceptos distintos y no se mezclan:
   - UF vigente: la del día, para el Panel (GET /configuracion/uf-vigente).
   - UF utilizada: la que quedó guardada con una estimación (ufValor y ufFecha del plazo),
     histórica; nunca se reemplaza por la vigente ni se reconstruye. */

/** Respuesta de GET /configuracion/uf-vigente. Sin valor ni fecha si no hay UF cargada. */
export interface UfVigente {
  valor: number | null
  fecha: string | null
  fuente: string
}

export interface PresentacionUf {
  disponible: boolean
  /** "$41.274,20", o "No disponible". */
  valor: string
  /** "05 nov 2026 · CMF", o vacío si no hay UF. */
  detalle: string
}

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

// Siempre dos decimales, como se publica la UF: 41.274,20.
const UF = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** "$41.274,20". La UF no es CLP, pero el signo $ es como la oficina la lee. */
export function valorUf(valor: number): string {
  return `$${UF.format(valor)}`
}

/** "2026-11-05" → "05 nov 2026". Se lee el texto, no un Date: una zona horaria no corre el día. */
export function fechaUf(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return null
  const mes = MESES[Number(m[2]) - 1]
  return mes ? `${m[3]} ${mes} ${m[1]}` : null
}

const NO_DISPONIBLE: PresentacionUf = { disponible: false, valor: 'No disponible', detalle: '' }

function presentar(valor: number | null | undefined, fecha: string | null | undefined, fuente: string): PresentacionUf {
  const dia = fechaUf(fecha)
  if (valor == null || !Number.isFinite(valor) || valor <= 0 || !dia) return NO_DISPONIBLE
  return { disponible: true, valor: valorUf(valor), detalle: `${dia} · ${fuente}` }
}

/** Panel: la UF de hoy. */
export function presentarUfVigente(uf: UfVigente | null | undefined): PresentacionUf {
  return presentar(uf?.valor, uf?.fecha, uf?.fuente || 'CMF')
}

/** Transparencia: la UF que usó esa estimación. Una estimación anterior al snapshot no la tiene. */
export function presentarUfUtilizada(plazo: Pick<PlazoEstimacion, 'ufValor' | 'ufFecha'> | null | undefined): PresentacionUf {
  return presentar(plazo?.ufValor, plazo?.ufFecha, 'CMF')
}
