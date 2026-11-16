// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import {
  cargarDetalleProyecto, mensajeCargaProyecto, MENSAJE_SIN_ID, puedeReintentar, vistaDetalle,
  type FuenteDetalle,
} from '../src/lib/detalleProyecto.ts'
import { bloqueoCronograma } from '../src/lib/plazo.ts'
import { puedeEditarObservaciones } from '../src/lib/observaciones.ts'
import type { PartidasProyecto, PlantillaResumen, Proyecto } from '../src/tipos/api.ts'
import type { Estimacion } from '../src/tipos/estimacion.ts'

/* Detalle de proyecto (estimacion.html): mientras carga no puede aparecer ningún
   estado vacío; un error de carga tampoco se disfraza de proyecto vacío. */

const AJUSTES_BASE = { gastosGeneralesPct: 15, utilidadPct: 10 }
const PROYECTO = { id: 'p-1', nombre: 'Casa Madera', mi_rol: 'propietario', estado: 'vigente' } as unknown as Proyecto
const PLANTILLA = { id: 't-1', tipo_obra: 'Vivienda unifamiliar', materialidad: 'Albañilería confinada' } as PlantillaResumen
const ESTIMACION = { id: 'e-1', total: 4_007_700, gastosGeneralesPct: 20, utilidadPct: 12 } as unknown as Estimacion

function partidas(cambios: Partial<PartidasProyecto> = {}): PartidasProyecto {
  return { plantilla_aplicada: null, plantilla_sugerida: null, version_precios: null, partidas: [], ...cambios }
}

function fuente(cambios: Partial<FuenteDetalle> = {}): FuenteDetalle {
  return {
    obtenerProyecto: async () => PROYECTO,
    listarVersiones: async () => [{ id: 'v-2', vigente: true }, { id: 'v-1', vigente: false }] as never,
    listarCategorias: async () => [],
    listarPartidasProyecto: async () => partidas(),
    ultimaEstimacion: async () => null,
    obtenerConfiguracion: async () => ({ gastosGeneralesPct: 18, utilidadPct: 9 }),
    ...cambios,
  }
}

/** Promesa que se resuelve a mano: deja la carga detenida "a mitad de camino". */
function pendiente<T>() {
  let resolver!: (v: T) => void
  const promesa = new Promise<T>((r) => { resolver = r })
  return { promesa, resolver }
}

describe('vista del detalle de proyecto', () => {
  it('mientras carga es «cargando», aunque ya haya proyecto o error previos', () => {
    assert.equal(vistaDetalle({ cargando: true, proyecto: null, error: '' }), 'cargando')
    assert.equal(vistaDetalle({ cargando: true, proyecto: PROYECTO, error: '' }), 'cargando')
    assert.equal(vistaDetalle({ cargando: true, proyecto: null, error: 'x' }), 'cargando')
  })

  it('terminada con proyecto es «listo»', () => {
    assert.equal(vistaDetalle({ cargando: false, proyecto: PROYECTO, error: '' }), 'listo')
  })

  it('terminada sin proyecto o con error es «error», nunca «listo»', () => {
    assert.equal(vistaDetalle({ cargando: false, proyecto: null, error: 'falló' }), 'error')
    assert.equal(vistaDetalle({ cargando: false, proyecto: null, error: '' }), 'error')
    assert.equal(vistaDetalle({ cargando: false, proyecto: PROYECTO, error: 'falló' }), 'error')
  })
})

describe('cargarDetalleProyecto', () => {
  it('no entrega nada hasta tener partidas y estimación: no hay estado intermedio', async () => {
    const lentas = pendiente<PartidasProyecto>()
    let resuelto = false
    const carga = cargarDetalleProyecto(fuente({ listarPartidasProyecto: () => lentas.promesa }), 'p-1', AJUSTES_BASE)
      .then((d) => { resuelto = true; return d })

    // El proyecto ya llegó, pero las partidas no: la pantalla sigue cargando.
    await new Promise((r) => setTimeout(r, 0))
    assert.equal(resuelto, false)

    lentas.resolver(partidas({ plantilla_aplicada: PLANTILLA, partidas: [{ id: 'pp-1' }] as never }))
    const detalle = await carga
    assert.equal(detalle.proyecto, PROYECTO)
    assert.equal(detalle.plantillaAplicada, PLANTILLA)
    assert.equal(detalle.partidas.length, 1)
  })

  it('sin plantilla ni partidas lo informa como dato real, no como valor por defecto', async () => {
    const detalle = await cargarDetalleProyecto(fuente(), 'p-1', AJUSTES_BASE)
    assert.equal(detalle.plantillaAplicada, null)
    assert.deepEqual(detalle.partidas, [])
    assert.equal(detalle.estimacion, null)
    assert.equal(detalle.versionVigenteId, 'v-2')
    // Sin estimación, el formulario parte de la configuración de la oficina.
    assert.deepEqual(detalle.ajustes, { gastosGeneralesPct: 18, utilidadPct: 9 })
  })

  it('entrega la estimación guardada junto con el resto', async () => {
    const detalle = await cargarDetalleProyecto(fuente({ ultimaEstimacion: async () => ESTIMACION }), 'p-1', AJUSTES_BASE)
    assert.equal(detalle.estimacion, ESTIMACION)
  })

  it('sin configuración usa los ajustes base sin fallar la carga', async () => {
    const detalle = await cargarDetalleProyecto(
      fuente({ obtenerConfiguracion: async () => { throw new ErrorApi(500, 'caída') } }), 'p-1', AJUSTES_BASE)
    assert.deepEqual(detalle.ajustes, AJUSTES_BASE)
  })

  for (const peticion of ['obtenerProyecto', 'listarPartidasProyecto', 'ultimaEstimacion', 'listarCategorias'] as const) {
    it(`si falla ${peticion}, falla la carga completa (no se muestra vacío)`, async () => {
      const f = fuente({ [peticion]: async () => { throw new ErrorApi(500, 'Error del servidor') } })
      await assert.rejects(cargarDetalleProyecto(f, 'p-1', AJUSTES_BASE), ErrorApi)
    })
  }
})

describe('mensajes de error de carga', () => {
  it('explica los casos habituales', () => {
    assert.match(mensajeCargaProyecto(new ErrorApi(404, 'x')), /no existe/)
    assert.match(mensajeCargaProyecto(new ErrorApi(403, 'x')), /acceso/)
    assert.match(mensajeCargaProyecto(new ErrorApi(0, 'x')), /conexión/)
    assert.equal(mensajeCargaProyecto(new ErrorApi(500, 'Error del servidor')), 'Error del servidor')
    assert.ok(mensajeCargaProyecto(new TypeError('boom')).length > 0)
  })

  it('sin id de proyecto no ofrece reintentar', () => {
    assert.equal(puedeReintentar(MENSAJE_SIN_ID), false)
    assert.equal(puedeReintentar('No hubo respuesta del servidor.'), true)
  })
})

/* --- Estructura de estimacion.html ----------------------------------------- */

const HTML = readFileSync(new URL('../estimacion.html', import.meta.url), 'utf8')

interface Abierta { nombre: string; atributos: string }

/** Etiquetas abiertas en la posición `fin`, de la más externa a la más interna.
 *  Respeta comillas: las expresiones de Alpine pueden llevar ">" (=>). */
function ancestros(html: string, fin: number): Abierta[] {
  const VACIOS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr'])
  const pila: Abierta[] = []
  let i = 0
  while ((i = html.indexOf('<', i)) !== -1 && i < fin) {
    if (html.startsWith('<!--', i)) { i = html.indexOf('-->', i) + 3; continue }
    let j = i + 1
    let comilla = ''
    while (j < html.length && (comilla || html[j] !== '>')) {
      if (comilla) { if (html[j] === comilla) comilla = '' } else if (html[j] === '"' || html[j] === "'") comilla = html[j]
      j++
    }
    const crudo = html.slice(i + 1, j)
    const nombre = /^\/?([a-zA-Z][\w-]*)/.exec(crudo)?.[1]?.toLowerCase()
    if (nombre && j < fin) {
      if (crudo.startsWith('/')) {
        const k = pila.map((p) => p.nombre).lastIndexOf(nombre)
        if (k !== -1) pila.length = k
      } else if (!VACIOS.has(nombre)) {
        pila.push({ nombre, atributos: crudo })
      }
    }
    i = j + 1
  }
  return pila
}

const condicionDe = (a: Abierta) => /x-if="([^"]*)"/.exec(a.atributos)?.[1]
const dentroDeVista = (texto: string, vista: string) =>
  ancestros(HTML, HTML.indexOf(texto)).some((a) => a.nombre === 'template' && condicionDe(a) === `vista === '${vista}'`)

/** El bloque que contiene un marcador, desde su etiqueta de apertura hasta su cierre. */
function bloqueEsqueleto(): string {
  const inicio = HTML.indexOf('<div class="bc-sk"')
  const fin = HTML.indexOf('<!-- Error', inicio)
  assert.ok(inicio !== -1 && fin !== -1, 'falta el esqueleto')
  return HTML.slice(inicio, fin)
}

describe('estimacion.html: carga sin estados falsos', () => {
  it('«Sin plantilla aplicada» solo existe dentro de la vista lista', () => {
    assert.ok(HTML.includes('Sin plantilla aplicada'))
    assert.ok(dentroDeVista('Sin plantilla aplicada', 'listo'))
  })

  it('«Este proyecto todavía no tiene partidas» solo existe dentro de la vista lista y con partidas vacías', () => {
    const texto = 'Este proyecto todavía no tiene partidas'
    assert.ok(dentroDeVista(texto, 'listo'))
    const condiciones = ancestros(HTML, HTML.indexOf(texto)).map(condicionDe).filter(Boolean)
    assert.ok(condiciones.includes('partidas.length === 0'), condiciones.join(' | '))
  })

  it('el esqueleto no muestra estados vacíos, cifras ni valores por defecto', () => {
    const sk = bloqueEsqueleto()
    for (const prohibido of ['Sin plantilla', 'Sin partidas', 'todavía no tiene', 'Sin observaciones', '$', 'x-text']) {
      assert.ok(!sk.includes(prohibido), `el esqueleto contiene «${prohibido}»`)
    }
  })

  it('el esqueleto se rige solo por vista === cargando y tiene texto accesible', () => {
    const sk = bloqueEsqueleto()
    assert.match(sk, /x-show="vista === 'cargando'"/)
    assert.match(sk, /role="status"/)
    assert.match(sk, /Cargando proyecto…/)
    // Las siluetas son decoración: ocultas a lectores de pantalla.
    for (const silueta of sk.match(/<(i|div) class="bc-sk__(titulo|meta|boton|tarjetas|pestanas|presupuesto)"[^>]*>/g) ?? []) {
      assert.match(silueta, /aria-hidden="true"/, silueta)
    }
  })

  it('el error tiene su propia vista, con título, reintentar y sin estado vacío', () => {
    const inicio = HTML.indexOf(`<template x-if="vista === 'error'">`)
    assert.ok(inicio !== -1)
    const bloque = HTML.slice(inicio, HTML.indexOf('</template>', inicio))
    assert.match(bloque, /No pudimos cargar este proyecto\./)
    assert.match(bloque, /role="alert"/)
    assert.match(bloque, /@click="reintentar\(\)"[^>]*>Reintentar</)
    assert.ok(!/Sin partidas|Sin plantilla|todavía no tiene/.test(bloque))
  })

  it('el contenido real (costo, plazo, pestañas, presupuesto) cuelga de vista === listo', () => {
    for (const marca of ['id="resultado-estimacion"', 'Plantilla aplicada', 'Presupuesto por partidas', 'Ajustes comerciales',
      'Cronograma preliminar', 'Miembros del proyecto', 'Actividad del proyecto']) {
      assert.ok(dentroDeVista(marca, 'listo'), marca)
    }
  })

  it('main no se oculta con x-cloak: el esqueleto se ve desde el primer pintado', () => {
    assert.match(HTML, /<main class="bc-pagina" :aria-busy="vista === 'cargando'">/)
    assert.ok(!HTML.includes('class="bc-esqueleto"'))
  })

  it('ningún x-show lleva display en el estilo en línea (x-show lo borra al mostrar)', () => {
    for (const archivo of ['estimacion.html', 'panel.html', 'proyectos.html', 'plantillas.html', 'precios.html']) {
      const html = readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')
      const malas = [...html.matchAll(/<[a-z]+\b[^>]*\bx-show="[^"]*"[^>]*>/g)]
        .map((m) => m[0]).filter((t) => /style="[^"]*\bdisplay\s*:/.test(t))
      assert.deepEqual(malas, [], archivo)
    }
  })
})

describe('sin regresiones en reglas del detalle', () => {
  it('cronograma: bloqueado con estimación incompleta o sin plazo', () => {
    assert.equal(bloqueoCronograma(false, { dias: 30 } as never), 'incompleta')
    assert.equal(bloqueoCronograma(true, null), 'sin_plazo')
  })

  it('permisos: un lector no edita observaciones; un editor sí', () => {
    assert.equal(puedeEditarObservaciones('lector'), false)
    assert.equal(puedeEditarObservaciones('editor'), true)
  })
})
