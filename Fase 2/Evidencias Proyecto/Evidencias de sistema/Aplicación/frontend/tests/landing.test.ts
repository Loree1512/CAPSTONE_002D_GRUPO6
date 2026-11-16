// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { destinoTecla, ETAPAS, indiceEtapa, PERFILES, textoEtapa } from '../src/lib/recorrido.ts'

const HTML = readFileSync(new URL('../index.html', import.meta.url), 'utf8')

/** Bloque HTML de la sección del recorrido. */
const recorrido = (() => {
  const i = HTML.indexOf('data-seq="journey"')
  return HTML.slice(i, HTML.indexOf('</section>', i))
})()

/** Una lámina (capa) del recorrido por índice. */
function lamina(i: number): string {
  const ini = recorrido.indexOf(`data-seq-item="${i}"`)
  const fin = i < 5 ? recorrido.indexOf(`data-seq-item="${i + 1}"`) : recorrido.length
  return recorrido.slice(ini, fin)
}

describe('indicador de etapa', () => {
  it('corresponde a las seis etapas en orden', () => {
    assert.deepEqual([...ETAPAS], ['Proyecto', 'Documentos', 'Análisis', 'Cantidades', 'Costos', 'Presupuesto'])
    assert.equal(textoEtapa(0), '01 / 06 · Proyecto')
    assert.equal(textoEtapa(5), '06 / 06 · Presupuesto')
  })

  it('usa el mismo reparto que las capas: un sexto del recorrido por etapa', () => {
    assert.equal(indiceEtapa(0), 0)
    assert.equal(indiceEtapa(0.16), 0)
    assert.equal(indiceEtapa(1 / 6 + 0.001), 1)
    assert.equal(indiceEtapa(0.5), 3)
    assert.equal(indiceEtapa(0.999), 5)
    // Fuera de rango no inventa etapas.
    assert.equal(indiceEtapa(1), 5)
    assert.equal(indiceEtapa(-0.2), 0)
  })

  it('arranca oculto y sin depender del scroll de toda la página', () => {
    assert.match(HTML, /<span data-chapter="1" class="bc-capitulo" aria-hidden="true">01 \/ 06 · Proyecto<\/span>/)
    const ts = readFileSync(new URL('../src/paginas/landing.ts', import.meta.url), 'utf8')
    assert.doesNotMatch(ts, /scrollHeight - alto/)
  })
})

describe('recorrido: seis láminas de un mismo proyecto', () => {
  it('hay seis láminas animables, cada una con su dibujo accesible', () => {
    for (let i = 0; i < 6; i++) {
      const l = lamina(i)
      assert.match(l, /data-anima/, `lámina ${i}`)
      assert.match(l, new RegExp(`<svg class="bc-lamina__svg"[^>]*role="img" aria-labelledby="etapa-${i}-desc"`), `lámina ${i}`)
      assert.match(l, new RegExp(`<title id="etapa-${i}-desc">[^<]{40,}</title>`), `lámina ${i}`)
      assert.match(l, new RegExp(`>0${i + 1}</div><h3[^>]*>${ETAPAS[i]}</h3>`), `lámina ${i}`)
    }
  })

  it('el mismo folio recorre las seis láminas (continuidad)', () => {
    for (let i = 0; i < 6; i++) assert.match(lamina(i), /BC-2026-0142/, `lámina ${i}`)
  })

  it('el punto naranja del riel avanza una posición por etapa', () => {
    for (let i = 0; i < 6; i++) {
      const punto = /<circle class="bc-a bc-punto"[^>]*cx="(\d+)"/.exec(lamina(i))
      assert.equal(Number(punto?.[1]), 60 + i * 96, `lámina ${i}`)
    }
  })

  it('las cifras encadenan las etapas: cantidad → costo → presupuesto', () => {
    assert.match(lamina(3), /18,4/)
    assert.match(lamina(4), /18,4 m³/)
    assert.match(lamina(4), /\$ 98\.500 \/ m³/)
    assert.match(lamina(4), /\$ 1\.812\.400/)         // 18,4 × 98.500
    assert.match(lamina(4), /\$ 61\.240\.500/)
    assert.match(lamina(5), /\$ 76\.550\.625/)        // 61.240.500 × 1,25 (GG 15 % + utilidad 10 %)
    assert.equal(Math.round(18.4 * 98500), 1812400)
    assert.equal(61240500 * 1.25, 76550625)
  })

  it('no describe capacidades que el producto ya no tiene', () => {
    assert.doesNotMatch(recorrido, /rendimiento de mano de obra/)
  })

  it('ningún elemento lleva dos atributos class (el segundo se ignoraría)', () => {
    assert.equal((HTML.match(/<[a-z]+\b[^>]*\bclass="[^"]*"[^>]*\sclass="/g) ?? []).length, 0)
  })
})

describe('¿Para quién construimos?', () => {
  const pestanas = HTML.match(/<button type="button" class="bc-perfil-tab"[^>]*>/g) ?? []

  it('cinco perfiles como pestañas accesibles, una sola seleccionada', () => {
    assert.equal(pestanas.length, 5)
    pestanas.forEach((p, i) => {
      assert.match(p, /role="tab"/)
      assert.match(p, new RegExp(`id="perfil-tab-${i}"`))
      assert.match(p, /aria-controls="perfil-panel"/)
    })
    assert.equal(pestanas.filter((p) => p.includes('aria-selected="true"')).length, 1)
    assert.match(HTML, /role="tablist"/)
    assert.match(HTML, /id="perfil-panel" role="tabpanel" aria-labelledby="perfil-tab-0"/)
  })

  it('cada perfil tiene su propio visual en el mismo marco', () => {
    const vistas = HTML.match(/<figure class="bc-perfil-vista"[^>]*>/g) ?? []
    assert.equal(vistas.length, 5)
    assert.equal(vistas.filter((v) => v.includes('data-actual')).length, 1)
    vistas.slice(1).forEach((v) => assert.match(v, /aria-hidden="true"/))
    assert.equal((HTML.match(/class="bc-perfil-vista"[\s\S]*?<svg viewBox="0 0 520 280" role="img" aria-label="[^"]{20,}"/g) ?? []).length, 5)
  })

  it('las frases hablan de beneficios concretos y distintos', () => {
    assert.equal(PERFILES.length, 5)
    assert.equal(new Set(PERFILES.map((p) => p.frase)).size, 5)
    for (const p of PERFILES) assert.doesNotMatch(p.frase, /gran escala|nueva forma de trabajar/i)
    // La frase inicial del HTML es la del primer perfil: sin JS se lee igual.
    assert.ok(HTML.includes(PERFILES[0].frase))
    assert.ok(HTML.includes(PERFILES[0].foco))
  })

  it('teclado: flechas recorren en ciclo, Inicio y Fin van a los extremos', () => {
    assert.equal(destinoTecla('ArrowDown', 0, 5), 1)
    assert.equal(destinoTecla('ArrowRight', 4, 5), 0)
    assert.equal(destinoTecla('ArrowUp', 0, 5), 4)
    assert.equal(destinoTecla('ArrowLeft', 2, 5), 1)
    assert.equal(destinoTecla('Home', 3, 5), 0)
    assert.equal(destinoTecla('End', 1, 5), 4)
    assert.equal(destinoTecla('Enter', 1, 5), null)
    assert.equal(destinoTecla('a', 1, 5), null)
  })
})

describe('movimiento', () => {
  const css = readFileSync(new URL('../src/estilos/base.css', import.meta.url), 'utf8')

  it('los dibujos solo se ocultan para animarlos cuando hay .bc-movimiento', () => {
    for (const regla of css.match(/[^}]*\.bc-a\s*\{\s*opacity:\s*0/g) ?? []) {
      assert.match(regla, /\.bc-movimiento/, regla.trim())
    }
    const ts = readFileSync(new URL('../src/paginas/landing.ts', import.meta.url), 'utf8')
    assert.match(ts, /if \(!menosMovimiento\) document\.body\.classList\.add\('bc-movimiento'\)/)
  })
})
