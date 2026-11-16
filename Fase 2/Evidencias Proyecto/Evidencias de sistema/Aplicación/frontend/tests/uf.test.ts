// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { fechaUf, presentarUfUtilizada, presentarUfVigente, valorUf } from '../src/lib/uf.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

describe('UF: formato chileno', () => {
  it('valor con separador de miles, coma decimal y dos decimales', () => {
    assert.equal(valorUf(41274.2), '$41.274,20')
    assert.equal(valorUf(41263.57), '$41.263,57')
    assert.equal(valorUf(41000), '$41.000,00')
  })

  it('fecha corta sin depender de la zona horaria', () => {
    assert.equal(fechaUf('2026-11-05'), '05 nov 2026')
    assert.equal(fechaUf('2026-01-01'), '01 ene 2026')
    assert.equal(fechaUf('2026-12-31'), '31 dic 2026')
    assert.equal(fechaUf('2026-11-05T00:00:00+00:00'), '05 nov 2026')
  })

  it('fecha ausente o inválida', () => {
    assert.equal(fechaUf(null), null)
    assert.equal(fechaUf(''), null)
    assert.equal(fechaUf('2026-13-05'), null)
    assert.equal(fechaUf('hoy'), null)
  })
})

describe('Panel: UF vigente', () => {
  it('muestra valor, fecha y fuente', () => {
    assert.deepEqual(presentarUfVigente({ valor: 41274.2, fecha: '2026-11-05', fuente: 'CMF' }), {
      disponible: true, valor: '$41.274,20', detalle: '05 nov 2026 · CMF',
    })
  })

  it('sin UF cargada queda como no disponible, sin inventar valor ni fecha', () => {
    const vacia = { disponible: false, valor: 'No disponible', detalle: '' }
    assert.deepEqual(presentarUfVigente({ valor: null, fecha: null, fuente: 'CMF' }), vacia)
    assert.deepEqual(presentarUfVigente(null), vacia)
    assert.deepEqual(presentarUfVigente(undefined), vacia)
  })

  it('un valor sin fecha, o no positivo, no se presenta', () => {
    assert.equal(presentarUfVigente({ valor: 41274.2, fecha: null, fuente: 'CMF' }).disponible, false)
    assert.equal(presentarUfVigente({ valor: 0, fecha: '2026-11-05', fuente: 'CMF' }).disponible, false)
  })
})

describe('Transparencia: UF utilizada', () => {
  it('muestra el snapshot guardado con la estimación', () => {
    assert.deepEqual(presentarUfUtilizada({ ufValor: 41263.57, ufFecha: '2026-11-03' }), {
      disponible: true, valor: '$41.263,57', detalle: '03 nov 2026 · CMF',
    })
  })

  it('una estimación histórica sin snapshot muestra un estado neutro', () => {
    const vacia = { disponible: false, valor: 'No disponible', detalle: '' }
    assert.deepEqual(presentarUfUtilizada({ ufValor: null, ufFecha: null }), vacia)
    assert.deepEqual(presentarUfUtilizada(null), vacia)
    assert.deepEqual(presentarUfUtilizada(undefined), vacia)
  })

  it('no depende de la UF vigente: solo recibe el plazo de la estimación', () => {
    const antigua = presentarUfUtilizada({ ufValor: 38000.1, ufFecha: '2026-01-02' })
    const vigente = presentarUfVigente({ valor: 41274.2, fecha: '2026-11-05', fuente: 'CMF' })
    assert.equal(antigua.valor, '$38.000,10')
    assert.notEqual(antigua.valor, vigente.valor)
  })
})

describe('Dónde aparece la UF', () => {
  it('el Panel muestra la UF vigente', () => {
    const html = leer('panel.html')
    assert.match(html, /UF vigente/)
    assert.match(html, /x-text="uf\.valor"/)
    assert.match(html, /x-text="uf\.detalle"/)
  })

  it('Transparencia muestra la UF utilizada de la estimación, no la vigente', () => {
    const html = leer('estimacion.html')
    assert.match(html, /UF utilizada/)
    assert.match(html, /x-text="ufUtilizada\.valor"/)
    assert.doesNotMatch(html, /UF vigente/)
  })

  it('no aparece en proyectos, banco de precios ni plantillas', () => {
    for (const archivo of ['proyectos.html', 'precios.html', 'plantillas.html']) {
      assert.doesNotMatch(leer(archivo), /UF vigente|UF utilizada|uf\.valor/, archivo)
    }
  })

  it('el Panel pide la UF a la API de BuildCast, no a la CMF', () => {
    const panel = leer('src/paginas/panel.ts')
    assert.match(panel, /api\.obtenerUfVigente\(\)/)
    assert.doesNotMatch(panel, /cmfchile|apikey/i)
    assert.match(leer('src/lib/apiReal.ts'), /'\/configuracion\/uf-vigente'/)
  })
})
