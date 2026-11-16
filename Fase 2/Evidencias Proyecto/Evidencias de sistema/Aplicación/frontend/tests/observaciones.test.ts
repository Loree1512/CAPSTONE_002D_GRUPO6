// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import {
  accionCotizacion, errorObservaciones, normalizarObservaciones, observacionesCambiaron, OBSERVACIONES_MAX,
  puedeEditarObservaciones,
} from '../src/lib/observaciones.ts'
import { errorClaveNueva, leerEnlaceInvitacion, MENSAJE_ENLACE_INVALIDO } from '../src/lib/invitacion.ts'
import { describirEvento } from '../src/lib/historial.ts'
import type { EventoHistorial } from '../src/tipos/api.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

describe('observaciones: texto y validación', () => {
  it('es opcional: vacía o en blanco queda en null', () => {
    assert.equal(normalizarObservaciones(''), null)
    assert.equal(normalizarObservaciones('  \r\n '), null)
    assert.equal(normalizarObservaciones(null), null)
    assert.equal(normalizarObservaciones(' Sujeto a terreno.\r\nRevisar especialidades. '),
      'Sujeto a terreno.\nRevisar especialidades.')
  })

  it('respeta el máximo', () => {
    assert.equal(errorObservaciones('x'.repeat(OBSERVACIONES_MAX)), '')
    assert.equal(errorObservaciones(`  ${'x'.repeat(OBSERVACIONES_MAX)}  `), '')
    assert.equal(errorObservaciones('x'.repeat(OBSERVACIONES_MAX + 1)), 'Las observaciones admiten hasta 1000 caracteres.')
  })

  it('detecta cambios sin contar espacios sobrantes', () => {
    assert.equal(observacionesCambiaron(' Nota ', 'Nota'), false)
    assert.equal(observacionesCambiaron('', null), false)
    assert.equal(observacionesCambiaron('Otra', 'Nota'), true)
    assert.equal(observacionesCambiaron('', 'Nota'), true)
  })
})

describe('observaciones: permisos', () => {
  it('propietario y editor la editan; lector solo visualiza', () => {
    assert.equal(puedeEditarObservaciones('propietario'), true)
    assert.equal(puedeEditarObservaciones('editor'), true)
    assert.equal(puedeEditarObservaciones('lector'), false)
    assert.equal(puedeEditarObservaciones(null), false)
  })

  it('el campo editable solo se muestra a quien puede editar', () => {
    const html = leer('estimacion.html')
    assert.match(html, /<div class="bc-campo"[^>]*x-show="puedeEditarObservaciones"[^>]*>\s*<label for="observaciones">/)
  })
})

describe('observaciones: acción del botón', () => {
  it('cambiar solo la observación no pide recalcular', () => {
    assert.equal(accionCotizacion({ hayEstimacion: true, costoPendiente: false, observacionCambio: true }), 'actualizar')
    assert.equal(accionCotizacion({ hayEstimacion: true, costoPendiente: false, observacionCambio: false }), null)
  })

  it('si el costo cambió, recalcula y lleva la observación', () => {
    assert.equal(accionCotizacion({ hayEstimacion: true, costoPendiente: true, observacionCambio: true }), 'recalcular')
    assert.equal(accionCotizacion({ hayEstimacion: true, costoPendiente: true, observacionCambio: false }), 'recalcular')
  })

  it('sin estimación, la observación va con la primera', () => {
    assert.equal(accionCotizacion({ hayEstimacion: false, costoPendiente: false, observacionCambio: true }), 'generar')
  })

  it('la página usa «Actualizar cotización» y no lo presenta como recálculo', () => {
    const html = leer('estimacion.html')
    assert.match(html, /x-show="accion === 'actualizar'"[^>]*\n?[^>]*@click="actualizarCotizacion\(\)"/)
    assert.match(html, /'Actualizar cotización'/)
    const ts = readFileSync(new URL('../src/paginas/estimacion.ts', import.meta.url), 'utf8')
    // El estado del proyecto no depende de la observación.
    const inicio = ts.indexOf('get costoPendiente() {')
    const costo = ts.slice(inicio, ts.indexOf('},', inicio))
    assert.match(costo, /ajustesCambiaron/)
    assert.doesNotMatch(costo, /observacion/i)
  })
})

describe('observaciones: se muestran como texto, nunca como HTML', () => {
  for (const archivo of ['estimacion.html', 'documento.html']) {
    it(archivo, () => {
      const html = leer(archivo)
      assert.doesNotMatch(html, /x-html/)
      assert.match(html, /x-text="presupuesto\.observaciones"/)
    })
  }

  it('el documento solo la incluye cuando tiene contenido', () => {
    assert.match(leer('documento.html'), /<template x-if="presupuesto\.observaciones">\s*<section>\s*<h2 class="bc-h2">Observaciones<\/h2>/)
  })
})

describe('observaciones: historial', () => {
  it('describe la actualización de la cotización', () => {
    const evento: EventoHistorial = {
      id: 'e-1', accion: 'cotizacion_actualizada', entidad: 'estimacion', entidad_id: 'est-2',
      usuario_id: 'u-1', usuario_email: 'loreto@x.cl', usuario_nombre: 'Loreto',
      valores_anteriores: { observaciones: null }, valores_nuevos: { observaciones: 'Sujeto a terreno.' },
      origen: 'api', fecha: '2026-11-03T10:00:00',
    }
    const entrada = describirEvento(evento)
    assert.equal(entrada.texto, 'Actualizó las observaciones de la cotización')
    assert.deepEqual(entrada.cambios, [{ campo: 'Observaciones', anterior: 'Sin observaciones', nuevo: 'Sujeto a terreno.' }])
  })
})

describe('invitación: enlace y contraseña', () => {
  it('lee la sesión del enlace de invitación', () => {
    assert.deepEqual(leerEnlaceInvitacion('#access_token=abc&refresh_token=def&expires_in=3600&type=invite'),
      { tipo: 'invitacion', access_token: 'abc', refresh_token: 'def' })
  })

  it('ignora otros fragmentos', () => {
    assert.equal(leerEnlaceInvitacion(''), null)
    assert.equal(leerEnlaceInvitacion('#demostracion'), null)
    assert.equal(leerEnlaceInvitacion('#access_token=abc&type=signup'), null)
    assert.equal(leerEnlaceInvitacion('#type=invite'), null)
  })

  it('un enlace vencido muestra un error entendible', () => {
    assert.deepEqual(leerEnlaceInvitacion('#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid'),
      { tipo: 'error', mensaje: MENSAJE_ENLACE_INVALIDO })
  })

  it('valida la contraseña nueva', () => {
    assert.equal(errorClaveNueva('corta', 'corta'), 'La contraseña debe tener al menos 8 caracteres.')
    assert.equal(errorClaveNueva('una-clave-larga', 'otra-clave-larga'), 'Las contraseñas no coinciden.')
    assert.equal(errorClaveNueva('una-clave-larga', 'una-clave-larga'), '')
  })
})
