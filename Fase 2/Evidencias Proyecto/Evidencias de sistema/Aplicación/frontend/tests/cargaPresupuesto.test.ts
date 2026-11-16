// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import {
  conCalculo, crearSecuencia, estadoTrasCalcular, filaEnProceso, hayFilasEnProceso, iniciarFila, puedeCalcular,
  terminarFila, textoBotonCalcular,
} from '../src/lib/calculoPresupuesto.ts'
import type { CondicionesCalculo } from '../src/lib/calculoPresupuesto.ts'
import { partidaDeCatalogoAgregada } from '../src/lib/duplicados.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

const LISTO: CondicionesCalculo = {
  guardando: false, hayFilasEnProceso: false, errorAjustes: '', errorTextoObservaciones: '',
  hayPartidas: true, hayPresupuesto: true, costoPendiente: true,
}

/** Una promesa que se resuelve o rechaza cuando el test lo decide. */
function pendiente<T>() {
  let resolver!: (v: T) => void
  let rechazar!: (e: unknown) => void
  const promesa = new Promise<T>((res, rej) => { resolver = res; rechazar = rej })
  return { promesa, resolver, rechazar }
}

describe('Recalcular: estado de carga', () => {
  it('al pulsar inicia la carga y el botón queda bloqueado con «Calculando…»', async () => {
    const estado = { guardando: false, errorCalculo: '' }
    const espera = pendiente<string>()
    const corrida = conCalculo(estado, () => espera.promesa, () => 'error')

    assert.equal(estado.guardando, true)
    assert.equal(puedeCalcular({ ...LISTO, guardando: estado.guardando }), false)
    assert.equal(textoBotonCalcular({ guardando: true, hayFilasEnProceso: false, hayPresupuesto: true, ajustesCambiaron: false }), 'Calculando…')

    espera.resolver('listo')
    assert.equal(await corrida, 'listo')
  })

  it('no se dispara dos veces mientras calcula', async () => {
    const estado = { guardando: false, errorCalculo: '' }
    const espera = pendiente<string>()
    let llamadas = 0
    const tarea = () => { llamadas++; return espera.promesa }

    const primera = conCalculo(estado, tarea, () => 'error')
    const segunda = await conCalculo(estado, tarea, () => 'error')

    assert.equal(segunda, undefined)
    assert.equal(llamadas, 1)
    espera.resolver('listo')
    await primera
    assert.equal(llamadas, 1)
  })

  it('al terminar bien detiene la carga y vuelve a «Recalcular»', async () => {
    const estado = { guardando: false, errorCalculo: 'error anterior' }
    await conCalculo(estado, async () => 'ok', () => 'error')
    assert.equal(estado.guardando, false)
    assert.equal(estado.errorCalculo, '')
    assert.equal(textoBotonCalcular({ guardando: false, hayFilasEnProceso: false, hayPresupuesto: true, ajustesCambiaron: false }), 'Recalcular')
  })

  it('un error restaura la interfaz y deja el mensaje', async () => {
    const estado = { guardando: false, errorCalculo: '' }
    const resultado = await conCalculo(estado, async () => { throw new Error('boom') }, (e) => `No se pudo: ${(e as Error).message}`)
    assert.equal(resultado, undefined)
    assert.equal(estado.guardando, false)
    assert.equal(estado.errorCalculo, 'No se pudo: boom')
    // Se puede reintentar.
    assert.equal(puedeCalcular({ ...LISTO, guardando: estado.guardando }), true)
  })

  it('tras un error se puede calcular otra vez', async () => {
    const estado = { guardando: false, errorCalculo: '' }
    await conCalculo(estado, async () => { throw new Error('x') }, () => 'falló')
    const segunda = await conCalculo(estado, async () => 'bien', () => 'falló')
    assert.equal(segunda, 'bien')
    assert.equal(estado.errorCalculo, '')
  })

  it('textos del botón según el estado', () => {
    const t = (c: Partial<Parameters<typeof textoBotonCalcular>[0]>) =>
      textoBotonCalcular({ guardando: false, hayFilasEnProceso: false, hayPresupuesto: true, ajustesCambiaron: false, ...c })
    assert.equal(t({ hayPresupuesto: false }), 'Generar estimación')
    assert.equal(t({ ajustesCambiaron: true }), 'Aplicar cambios')
    assert.equal(t({}), 'Recalcular')
    assert.equal(t({ hayFilasEnProceso: true }), 'Guardando cambios…')
    assert.equal(t({ guardando: true, hayFilasEnProceso: true }), 'Calculando…')
  })

  it('puedeCalcular exige algo que calcular y ningún error ni guardado en curso', () => {
    assert.equal(puedeCalcular(LISTO), true)
    assert.equal(puedeCalcular({ ...LISTO, hayPartidas: false }), false)
    assert.equal(puedeCalcular({ ...LISTO, errorAjustes: 'GG fuera de rango' }), false)
    assert.equal(puedeCalcular({ ...LISTO, errorTextoObservaciones: 'muy larga' }), false)
    assert.equal(puedeCalcular({ ...LISTO, costoPendiente: false }), false)
    // Sin estimación previa siempre se puede generar.
    assert.equal(puedeCalcular({ ...LISTO, hayPresupuesto: false, costoPendiente: false }), true)
    // No se calcula con una partida a medio guardar.
    assert.equal(puedeCalcular({ ...LISTO, hayFilasEnProceso: true }), false)
  })

  it('tras generar, el proyecto queda vigente salvo que ya esté ejecutado', () => {
    assert.equal(estadoTrasCalcular('recalcular'), 'vigente')
    assert.equal(estadoTrasCalcular('sin_estimar'), 'vigente')
    assert.equal(estadoTrasCalcular(null), 'vigente')
    assert.equal(estadoTrasCalcular(undefined), 'vigente')
    assert.equal(estadoTrasCalcular('ejecutada'), 'ejecutada')
  })
})

describe('Edición de una partida: solo su fila queda ocupada', () => {
  it('una fila en proceso no marca a las demás', () => {
    const filas = iniciarFila({}, 'a')
    assert.equal(filaEnProceso(filas, 'a'), true)
    assert.equal(filaEnProceso(filas, 'b'), false)
    assert.equal(hayFilasEnProceso(filas), true)
  })

  it('dos filas a la vez se liberan por separado', () => {
    let filas = iniciarFila(iniciarFila({}, 'a'), 'b')
    filas = terminarFila(filas, 'a')
    assert.equal(filaEnProceso(filas, 'a'), false)
    assert.equal(filaEnProceso(filas, 'b'), true)
    filas = terminarFila(filas, 'b')
    assert.equal(hayFilasEnProceso(filas), false)
  })

  it('dos ediciones seguidas de la misma fila no la liberan antes de tiempo', () => {
    let filas = iniciarFila(iniciarFila({}, 'a'), 'a')
    filas = terminarFila(filas, 'a')
    assert.equal(filaEnProceso(filas, 'a'), true)
    filas = terminarFila(filas, 'a')
    assert.equal(filaEnProceso(filas, 'a'), false)
  })

  it('no modifica el estado anterior y terminar una fila ajena no hace nada', () => {
    const antes = iniciarFila({}, 'a')
    iniciarFila(antes, 'b')
    assert.deepEqual(antes, { a: 1 })
    assert.deepEqual(terminarFila(antes, 'zzz'), { a: 1 })
  })

  it('el refresco del proyecto solo lo aplica el pedido más reciente', () => {
    const secuencia = crearSecuencia()
    const primero = secuencia.nueva()
    const segundo = secuencia.nueva()
    assert.equal(secuencia.vigente(primero), false)
    assert.equal(secuencia.vigente(segundo), true)
  })
})

describe('Feedback visual: HTML y CSS', () => {
  const html = leer('estimacion.html')
  const css = leer('src/estilos/base.css')

  it('el botón se bloquea, anuncia la espera y muestra la barra mientras calcula', () => {
    assert.match(html, /:class="guardando && 'bc-boton--calculando'"/)
    assert.match(html, /:aria-busy="guardando"/)
    assert.match(html, /:disabled="!puedeAplicar" @click="aplicar\(\)" x-text="textoAplicar"/)
  })

  it('la barra es indeterminada: se desplaza y no muestra ningún porcentaje', () => {
    const bloque = /\.bc-boton--calculando::after \{[^}]*\}/.exec(css)?.[0] ?? ''
    assert.match(bloque, /animation: bc-barra-carga[^;]*infinite/)
    assert.match(bloque, /var\(--bc-acento\)/)
    assert.doesNotMatch(html + bloque, /\d+\s?%\s*(completado|listo|calculado)/i)
  })

  it('cada fila avisa por su cuenta, con id propio y sin ocupar espacio extra', () => {
    assert.match(html, /:id="'partida-' \+ p\.id" :aria-busy="filaEnProceso\(p\.id\)"/)
    assert.match(html, /'bc-fila-guardando': filaEnProceso\(p\.id\)/)
    assert.match(html, /x-text="origenPartida\(p\) \+ \(filaEnProceso\(p\.id\) \? ' · Guardando…' : ''\)"/)
    assert.match(css, /\.bc-fila-barra \{[^}]*position: absolute/)
    assert.doesNotMatch(html, /editando ===/)
  })

  it('prefers-reduced-motion quita el movimiento pero conserva la señal', () => {
    const reducido = /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.bc-boton--calculando::after, \.bc-fila-barra::before \{([^}]*)\}/.exec(css)
    assert.ok(reducido, 'falta la regla para movimiento reducido')
    assert.match(reducido[1], /animation: none/)
    // Sigue habiendo una línea visible (no desaparece) además del texto «Calculando…» / «Guardando…».
    assert.match(reducido[1], /background: var\(--bc-acento\)/)
    assert.doesNotMatch(reducido[1], /display: none|opacity: 0[;\s]/)
  })

  it('la página no espera la relectura del proyecto para liberar el botón ni las filas', () => {
    const pagina = leer('src/paginas/estimacion.ts')
    assert.doesNotMatch(pagina, /await this\.refrescarEstado\(\)/)
    assert.match(pagina, /conCalculo\(this,/)
  })
})

describe('Partidas repetidas: solo la misma partida de catálogo', () => {
  const fila = (id: string, partida_id: string | null, nombre = 'Mano de obra') => ({ id, partida_id, nombre })
  const PROYECTO = [
    fila('1', 'cat-1', 'Instalación de faenas'),   // de plantilla o agregada: ambas llevan partida_id
    fila('2', null, 'Mano de obra'),               // manual
  ]

  it('la misma partida de catálogo ya agregada se detecta y devuelve la fila existente', () => {
    assert.equal(partidaDeCatalogoAgregada(PROYECTO, 'cat-1')?.id, '1')
  })

  it('una partida de catálogo distinta no cuenta, aunque se llame igual', () => {
    assert.equal(partidaDeCatalogoAgregada(PROYECTO, 'cat-2'), undefined)
    assert.equal(partidaDeCatalogoAgregada([fila('1', 'cat-1', 'Excavación')], 'cat-9'), undefined)
  })

  it('una manual nunca cuenta como repetida, ni con el mismo nombre que otra', () => {
    const dosManuales = [fila('1', null, 'Equipo'), fila('2', null, 'Equipo')]
    assert.equal(partidaDeCatalogoAgregada(dosManuales, null), undefined)
    assert.equal(partidaDeCatalogoAgregada(dosManuales, undefined), undefined)
    assert.equal(partidaDeCatalogoAgregada(PROYECTO, ''), undefined)
  })

  it('proyecto vacío: nada que avisar', () => {
    assert.equal(partidaDeCatalogoAgregada([], 'cat-1'), undefined)
  })

  it('el aviso es inline, con «Ver partida» y «Cancelar», sin otro modal', () => {
    const html = leer('estimacion.html')
    assert.match(html, /Partida ya agregada/)
    assert.match(html, /Esta partida ya forma parte del presupuesto\./)
    assert.match(html, /@click="verPartidaExistente\(\)">Ver partida</)
    assert.match(html, /@click="duplicada = null">Cancelar</)
  })

  it('solo se valida el catálogo: las manuales no pasan por la regla', () => {
    const pagina = leer('src/paginas/estimacion.ts')
    const manual = /async agregarManual\(\) \{[\s\S]*?\n  \},/.exec(pagina)?.[0] ?? ''
    assert.ok(manual.length > 0)
    assert.doesNotMatch(manual, /partidaDeCatalogoAgregada|duplicada/)
    assert.match(pagina, /partidaDeCatalogoAgregada\(this\.partidas, f\.id\)/)
  })

  it('un clic repetido mientras se agrega no duplica', () => {
    const pagina = leer('src/paginas/estimacion.ts')
    assert.match(pagina, /if \(!this\.proyecto \|\| this\.agregandoCatalogo\) return/)
  })
})
