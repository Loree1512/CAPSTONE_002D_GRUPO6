// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { presentarPlazo } from '../src/lib/plazo.ts'
import type { PlazoEstimacion } from '../src/tipos/estimacion.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')
const tarjeta = /bc-resultado--claro bc-plazo">[\s\S]*?bc-plazo__pie[\s\S]*?<\/div>/.exec(leer('estimacion.html'))?.[0] ?? ''

const FUERA_DE_RANGO: PlazoEstimacion = {
  dias: 21, minDias: 10, maxDias: 111, metodo: 'p2', estado: 'tipo_obra_no_representado', fueraDominio: true,
  provisional: true, motivo: null, versionModelo: 'v1.0-2026-11-01', tipoObraModelo: 'vivienda',
  ufValor: 41263.57, ufFecha: '2026-11-03',
}

describe('Tarjeta de plazo referencial: ficha técnica', () => {
  const p = presentarPlazo(FUERA_DE_RANGO)

  it('textos de cada nivel', () => {
    assert.equal(p.rotulo, 'Plazo referencial')
    assert.equal(p.principal, 'Fuera del rango histórico')
    assert.equal(p.avisos[0], 'Este proyecto no cuenta con suficientes obras similares en los datos históricos disponibles.')
    assert.equal(p.valorModelo, 'Valor calculado: 21 días')
    assert.equal(p.rangoTecnico, 'Rango referencial: 10–111 días')
    assert.equal(p.origen, 'Modelo de plazo v1.0 · Estimación provisional')
  })

  it('el orden es: rótulo, estado, explicación, métricas y pie', () => {
    const orden = ['presentacion.rotulo', 'bc-resultado__leyenda', 'bc-plazo__avisos', 'bc-plazo__datos', 'bc-plazo__pie']
      .map((clave) => tarjeta.indexOf(clave))
    assert.ok(orden.every((i) => i >= 0), 'falta algún bloque')
    assert.deepEqual([...orden].sort((a, b) => a - b), orden)
  })

  it('las métricas separan etiqueta y cifra de los textos existentes', () => {
    assert.match(tarjeta, /presentacion\.valorModelo\.split\(': '\)\[0\]/)
    assert.match(tarjeta, /presentacion\.rangoTecnico\.split\(': '\)\[0\]/)
    assert.deepEqual('Valor calculado: 21 días'.split(': '), ['Valor calculado', '21 días'])
    assert.deepEqual('Rango referencial: 10–111 días'.split(': '), ['Rango referencial', '10–111 días'])
  })

  it('el pie muestra el modelo y aclara que no es un compromiso', () => {
    assert.match(tarjeta, /<b x-text="presentacion\.origen"><\/b>/)
    assert.match(tarjeta, /Referencia calculada con los datos disponibles\. No constituye un compromiso de plazo\./)
  })

  it('las métricas van en dos columnas entre filetes finos, y el pie al fondo', () => {
    const css = leer('src/estilos/base.css')
    assert.match(css, /\.bc-plazo__datos \{[^}]*display: grid[^}]*border-top: 1px solid var\(--bc-linea\)/)
    assert.match(css, /\.bc-plazo__datos > div \+ div \{[^}]*border-left: 1px solid var\(--bc-linea\)/)
    assert.match(css, /\.bc-plazo__pie \{[^}]*margin-top: auto/)
  })

  it('sin insignia ni íconos: solo texto', () => {
    assert.doesNotMatch(tarjeta, /insignia|<svg|<img|<i /)
  })
})

describe('La palabra «extrapolación» no aparece en la interfaz', () => {
  const visibles = ['estimacion.html', 'documento.html', 'proyectos.html', 'panel.html']
  const quitarComentarios = (html: string) => html.replace(/<!--[\s\S]*?-->/g, '')

  it('ni en los textos que ve el usuario de las páginas', () => {
    for (const archivo of visibles) assert.doesNotMatch(quitarComentarios(leer(archivo)), /extrapolaci/i, archivo)
  })

  it('ni en los textos que arma la lib de plazo', () => {
    const textos = [FUERA_DE_RANGO, { ...FUERA_DE_RANGO, estado: 'costo_incompleto' as const }, { ...FUERA_DE_RANGO, estado: 'fuera_rango_costo' as const, motivo: 'costo_sobre_rango' }]
      .flatMap((plazo) => {
        const p = presentarPlazo(plazo)
        return [p.rotulo, p.principal, p.valorModelo, p.rangoTecnico, p.origen, p.estadoCorto, ...p.avisos]
      })
    for (const texto of textos) assert.doesNotMatch(texto, /extrapolaci/i, texto)
  })
})

describe('Tarjeta: plazo sugerido por BuildCast (interno)', () => {
  it('se rotula como sugerencia, con error medio y estado del modelo en el pie', () => {
    assert.match(tarjeta, /<span class="bc-rotulo">Plazo sugerido por BuildCast<\/span>/)
    const pie = /bc-plazo__pie[\s\S]*?<\/div>/.exec(tarjeta)?.[0] ?? ''
    assert.match(pie, /x-text="errorMedio"/)
    assert.match(pie, /x-text="estadoModelo"/)
  })

  it('el error medio nunca se presenta como intervalo «±»', () => {
    assert.doesNotMatch(leer('estimacion.html'), /±/)
  })
})

describe('Tarjeta: plazo para la cotización', () => {
  const html = leer('estimacion.html')
  const bloque = /id="plazo-cotizacion">[\s\S]*?<\/template>\s*<p class="bc-nota"[^>]*>[^<]*<\/p>/.exec(html)?.[0] ?? ''

  it('separada de la sugerencia, con el texto para el documento', () => {
    assert.ok(bloque, 'falta el bloque del plazo para la cotización')
    assert.match(bloque, /<span class="bc-rotulo">Plazo para la cotización<\/span>/)
    assert.match(bloque, /Este será el plazo mostrado en el documento de entrega\./)
    assert.ok(html.indexOf('bc-plazo__pie') < html.indexOf('id="plazo-cotizacion"'), 'va debajo de la sugerencia')
  })

  it('campo en días, «Usar sugerencia», «Guardar plazo» y «Mantener» si está por revisar', () => {
    assert.match(bloque, /id="plazo-profesional" type="number"/)
    assert.match(bloque, /x-model="plazoEscrito"/)
    assert.match(bloque, /@click="usarSugerencia\(\)" x-text="textoUsarSugerencia"/)
    assert.match(bloque, /@click="guardarPlazo\(\)"/)
    assert.match(bloque, /Guardar plazo/)
    assert.match(bloque, /x-show="profesional\.porRevisar"[\s\S]*?@click="mantenerPlazo\(\)" x-text="textoMantener"/)
    assert.match(bloque, /x-text="profesional\.avisoRevision"/)
  })

  it('el lector no ve controles de edición', () => {
    const edicion = /<template x-if="puedeEditarPlazo">[\s\S]*?<\/template>/.exec(bloque)?.[0] ?? ''
    for (const control of ['plazo-profesional', 'usarSugerencia()', 'guardarPlazo()', 'mantenerPlazo()']) {
      assert.ok(edicion.includes(control), `${control} debe ir dentro de x-if="puedeEditarPlazo"`)
    }
  })

  it('no muestra métricas del modelo en el bloque del profesional', () => {
    assert.doesNotMatch(bloque, /errorMedio|estadoModelo|presentacion\./)
  })
})
