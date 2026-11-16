// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

/* x-show solo oculta: Alpine evalúa igual las expresiones de los hijos. Un acceso a
   `presupuesto.` sin estimación lanza "Cannot read properties of null", así que debe
   quedar dentro de un <template x-if="presupuesto…"> o protegido en la misma expresión. */

const VACIOS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr'])
const ACCESO = /\bpresupuesto!?\.(?!\?)/
// "presupuesto && …" o "presupuesto ? … : …" en la misma expresión.
const PROTEGE = /^\s*\(?\s*presupuesto\s*(&&|\?(?!\.))/
// Condición de un x-if: "presupuesto" solo o seguido de "&&".
const PROTEGE_BLOQUE = /^\s*presupuesto\s*($|&&)/

interface Etiqueta { nombre: string; atributos: Record<string, string>; cierre: boolean; linea: number }

// Recorre las etiquetas respetando comillas: las expresiones pueden llevar ">" (=>).
function etiquetas(html: string): Etiqueta[] {
  const lista: Etiqueta[] = []
  let i = 0
  while ((i = html.indexOf('<', i)) !== -1) {
    if (html.startsWith('<!--', i)) { i = html.indexOf('-->', i) + 3; continue }
    let j = i + 1
    let comilla = ''
    while (j < html.length && (comilla || html[j] !== '>')) {
      if (comilla) { if (html[j] === comilla) comilla = '' } else if (html[j] === '"' || html[j] === "'") comilla = html[j]
      j++
    }
    const crudo = html.slice(i + 1, j)
    const nombre = /^\/?([a-zA-Z][\w-]*)/.exec(crudo)?.[1]?.toLowerCase()
    if (nombre) {
      const atributos: Record<string, string> = {}
      for (const m of crudo.matchAll(/([^\s=/]+)\s*=\s*("([^"]*)"|'([^']*)')/g)) atributos[m[1]] = m[3] ?? m[4]
      lista.push({ nombre, atributos, cierre: crudo.startsWith('/'), linea: html.slice(0, i).split('\n').length })
    }
    i = j + 1
  }
  return lista
}

/** Expresiones que leen `presupuesto.` sin protección, con su línea. */
function accesosSinProteger(html: string): string[] {
  const pila: { nombre: string; protege: boolean }[] = []
  const errores: string[] = []
  for (const e of etiquetas(html)) {
    if (e.cierre) {
      const k = pila.map((p) => p.nombre).lastIndexOf(e.nombre)
      if (k !== -1) pila.length = k
      continue
    }
    const protegido = pila.some((p) => p.protege)
    for (const [nombre, valor] of Object.entries(e.atributos)) {
      if (!/^(x-|:|@)/.test(nombre) || !ACCESO.test(valor)) continue
      if (!protegido && !PROTEGE.test(valor)) errores.push(`línea ${e.linea}: ${nombre}="${valor.trim().slice(0, 70)}"`)
    }
    if (!VACIOS.has(e.nombre)) {
      const condicion = e.nombre === 'template' ? e.atributos['x-if'] : undefined
      pila.push({ nombre: e.nombre, protege: condicion !== undefined && PROTEGE_BLOQUE.test(condicion) })
    }
  }
  return errores
}

describe('estimacion.html sin estimación', () => {
  it('ninguna expresión lee presupuesto sin protegerse', () => {
    const html = readFileSync(new URL('../estimacion.html', import.meta.url), 'utf8')
    assert.deepEqual(accesosSinProteger(html), [])
  })

  it('detecta el caso que fallaba: x-show no protege a los hijos', () => {
    const antes = `<p x-show="presupuesto && !presupuesto.completa">
      <span x-text="presupuesto.sinCantidad.map((l) => l.nombre)"></span></p>`
    assert.equal(accesosSinProteger(antes).length, 1)

    const ahora = `<template x-if="presupuesto && !presupuesto.completa"><p>
      <span x-text="presupuesto.sinCantidad.map((l) => l.nombre)"></span></p></template>`
    assert.deepEqual(accesosSinProteger(ahora), [])
  })

  it('una condición negada o comparada no cuenta como protección', () => {
    for (const condicion of ['!presupuesto', 'presupuesto === null', 'cargando']) {
      const html = `<template x-if="${condicion}"><b x-text="presupuesto.total"></b></template>`
      assert.equal(accesosSinProteger(html).length, 1, condicion)
    }
    assert.deepEqual(accesosSinProteger('<b x-text="presupuesto?.total ?? 0"></b>'), [])
  })
})
