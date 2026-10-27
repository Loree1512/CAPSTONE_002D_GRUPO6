const PESOS = new Intl.NumberFormat('es-CL', {
  style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
})
const NUMERO = new Intl.NumberFormat('es-CL')
// Precio unitario: CLP con separador de miles, sin perder decimales si los tiene.
const PRECIO = new Intl.NumberFormat('es-CL', {
  style: 'currency', currency: 'CLP', minimumFractionDigits: 0, maximumFractionDigits: 4,
})

export function pesos(valor: number | null | undefined): string {
  return valor == null ? '—' : PESOS.format(valor)
}

export function numero(valor: number | null | undefined): string {
  return valor == null ? '—' : NUMERO.format(valor)
}

export function superficie(m2: number | null | undefined): string {
  return m2 == null ? '—' : `${NUMERO.format(m2)} m²`
}

export function dias(valor: number | null | undefined): string {
  return valor == null ? '—' : `${NUMERO.format(valor)} días`
}

export function fecha(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: 'numeric' })
}

/** Factor de ajuste: × 1,05 o × 1,1025. */
export function factor(valor: number | null | undefined): string {
  if (valor == null) return '—'
  return `× ${valor.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
}

export function precioUnitario(valor: number | null | undefined): string {
  return valor == null ? '' : PRECIO.format(valor)
}

/** Lo que se escribe en una celda de precio ("$650.000", "650000", "1.350,5")
 *  como número en texto, igual que un input numérico: "650000", "1350.5". */
export function leerPrecioEscrito(texto: string): string {
  const limpio = texto.replace(/[^\d.,-]/g, '')
  if (!limpio) return ''
  // "3.5" o "3.25" sin coma: el punto es decimal. "650.000": el punto es de miles.
  if (!limpio.includes(',') && /^\d+\.\d{1,2}$/.test(limpio)) return limpio
  return limpio.replace(/\./g, '').replace(',', '.')
}
