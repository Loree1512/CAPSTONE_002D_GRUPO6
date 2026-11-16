// Ejecutar desde frontend/:  npm test
// Documento de entrega: el cliente ve solo el plazo definido por el profesional, nunca
// detalles del modelo de plazo (MAE, rango, versión, estado provisional ni dominio).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { plazoDocumento, profesionalSinDefinir } from '../src/lib/plazo.ts'
import type { PlazoProfesional } from '../src/tipos/estimacion.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')
const sinComentariosHtml = (html: string) => html.replace(/<!--[\s\S]*?-->/g, '')

const HTML = leer('documento.html')
const VISIBLE = sinComentariosHtml(HTML)
const TS = leer('src/paginas/documento.ts')

const DEFINIDO: PlazoProfesional = { dias: 135, estado: 'definido', origen: 'manual', fecha: '2026-11-05T14:00:00Z',
  usuarioId: 'u-1', usuarioNombre: 'Elena Editora' }

describe('documento: plazo para la cotización', () => {
  it('definido: «Plazo estimado de ejecución — 135 días»', () => {
    assert.deepEqual(plazoDocumento(DEFINIDO), { pendiente: false, texto: '135 días' })
    assert.match(VISIBLE, /<span class="bc-rotulo bc-rotulo--gris">Plazo estimado de ejecución<\/span>/)
    assert.match(VISIBLE, /x-text="plazoCliente\.texto"/)
  })

  it('sin definir: pendiente de definición, sin inventar ni usar el modelo', () => {
    assert.deepEqual(plazoDocumento(profesionalSinDefinir()), { pendiente: true, texto: 'Plazo pendiente de definición' })
    assert.deepEqual(plazoDocumento(undefined), { pendiente: true, texto: 'Plazo pendiente de definición' })
  })

  it('por revisar: también pendiente (el presupuesto cambió desde la decisión)', () => {
    assert.deepEqual(plazoDocumento({ ...DEFINIDO, estado: 'por_revisar' }),
      { pendiente: true, texto: 'Plazo pendiente de definición' })
  })

  it('el plazo sale del plazo profesional de la estimación, no de la sugerencia', () => {
    assert.match(TS, /plazoDocumento\(this\.presupuesto\?\.plazoProfesional\)/)
    assert.doesNotMatch(TS, /presupuesto\?*\.plazo\b(?!Profesional)/)
    assert.doesNotMatch(TS, /presentarPlazo|etiquetaModelo|avisoPlazo|textoRango|textoPlazo|hayPlazo\b/)
  })

  it('la generación no se bloquea: el documento se arma con o sin plazo', () => {
    assert.match(VISIBLE, /<template x-if="proyecto && presupuesto">/)
    assert.doesNotMatch(TS, /plazoProfesional[^\n]*(error|throw)/i)
  })
})

describe('documento: sin detalles del modelo de plazo', () => {
  it('no contiene MAE, error medio, rango, versión del modelo, «provisional» ni «fuera»', () => {
    for (const prohibido of [/MAE/, /error medio/i, /rango/i, /versión del modelo|modelo de plazo/i, /provisional/i,
      /fuera/i, /dominio/i, /±/, /respaldo/i, /calibrad/i]) {
      assert.doesNotMatch(VISIBLE, prohibido, String(prohibido))
    }
  })

  it('no usa la presentación de la sugerencia ni sus avisos', () => {
    assert.doesNotMatch(VISIBLE, /presentacion\.|aviso in|errorMedio|estadoModelo|versionModelo/)
  })

  it('reemplaza el párrafo sobre el modelo por una frase neutra', () => {
    assert.match(VISIBLE, /El plazo indicado fue definido por el profesional a cargo y es referencial\./)
    assert.doesNotMatch(VISIBLE, /presupuestos históricos|plazos ofertados/)
  })
})
