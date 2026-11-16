// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

/* Cargas dentro de una pantalla ya abierta (modales, pestañas, abrir una plantilla):
   todas dan respuesta inmediata y ninguna muestra un vacío falso mientras espera. */

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')
const ESTIMACION = leer('estimacion.html')
const PLANTILLAS = leer('plantillas.html')
const PLANTILLAS_TS = leer('src/paginas/plantillas.ts')
const ESTIMACION_TS = leer('src/paginas/estimacion.ts')

describe('modal «Agregar partida»: catálogo', () => {
  it('muestra un aviso de carga mientras llega el catálogo', () => {
    assert.match(ESTIMACION, /x-show="cargandoCatalogo" role="status"[^>]*>\s*<p class="bc-cargando__aviso">[\s\S]*?Cargando el catálogo…/)
  })

  it('la lista (y su «ninguna partida coincide») se oculta mientras carga', () => {
    assert.match(ESTIMACION, /<div class="bc-lista" x-show="!cargandoCatalogo">/)
  })

  it('el indicador se apaga también si falla', () => {
    assert.match(ESTIMACION_TS, /this\.cargandoCatalogo = true[\s\S]*?finally \{\s*this\.cargandoCatalogo = false/)
  })
})

describe('modal «Aplicar plantilla»', () => {
  it('no deja aplicar ni elegir mientras carga las plantillas', () => {
    assert.match(ESTIMACION, /id="pl-elegida"[^>]*:disabled="cargandoPlantillas"/)
    assert.match(ESTIMACION, /:disabled="cargandoPlantillas \|\| !plantillaElegida/)
    assert.match(ESTIMACION_TS, /finally \{\s*this\.cargandoPlantillas = false/)
  })
})

describe('miembros e historial', () => {
  it('usan el indicador de carga común con texto accesible', () => {
    for (const texto of ['Cargando los miembros…', 'Cargando el historial…']) {
      const i = ESTIMACION.indexOf(texto)
      assert.ok(i !== -1, texto)
      const bloque = ESTIMACION.slice(ESTIMACION.lastIndexOf('<div class="bc-cargando"', i), i)
      assert.match(bloque, /role="status"/, texto)
    }
  })
})

describe('plantillas: abrir una plantilla', () => {
  it('el botón responde al instante y bloquea un segundo clic', () => {
    assert.match(PLANTILLAS, /:disabled="abriendo !== ''"/)
    assert.match(PLANTILLAS, /abriendo === p\.id \? 'Abriendo…' : 'Editar'/)
    assert.match(PLANTILLAS, /class="bc-progreso" x-show="cargando \|\| abriendo"/)
  })

  it('el estado se limpia aunque la apertura falle', () => {
    assert.match(PLANTILLAS_TS, /if \(this\.abriendo\) return/)
    assert.match(PLANTILLAS_TS, /finally \{\s*this\.abriendo = ''/)
  })
})

describe('monogramas', () => {
  it('son decorativos: el nombre sigue siendo el texto de la celda', () => {
    for (const html of [ESTIMACION, leer('administracion.html')]) {
      const monogramas = html.match(/<span class="bc-monograma"[^>]*>/g) ?? []
      assert.ok(monogramas.length > 0)
      for (const m of monogramas) assert.match(m, /aria-hidden="true"/)
    }
  })
})
