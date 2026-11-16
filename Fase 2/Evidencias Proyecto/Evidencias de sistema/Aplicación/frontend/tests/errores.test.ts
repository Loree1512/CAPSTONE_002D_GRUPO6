// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  ErrorApi,
  MENSAJE_GUARDAR_PLANTILLA,
  mensajeEliminarProyecto,
  mensajeGuardarPlantilla,
  resolverGuardado,
} from '../src/lib/errores.ts'

const rechazar = (e: unknown) => async () => { throw e }

describe('guardar una plantilla', () => {
  it('2xx muestra el mensaje de éxito', async () => {
    const r = await resolverGuardado(async () => ({ id: 'p1' }), 'Datos de la plantilla guardados.')
    assert.deepEqual(r, { ok: true, mensaje: 'Datos de la plantilla guardados.' })
  })

  it('403 informa que faltan permisos y no es éxito', async () => {
    const r = await resolverGuardado(rechazar(new ErrorApi(403, 'detalle del servidor')), 'Guardado.')
    assert.deepEqual(r, { ok: false, error: 'No tienes permisos para editar plantillas.' })
  })

  it('401, 404 y 422 tienen su propio mensaje', () => {
    assert.match(mensajeGuardarPlantilla(new ErrorApi(401, 'x')), /sesión/)
    assert.match(mensajeGuardarPlantilla(new ErrorApi(404, 'x')), /no fue encontrada/)
    assert.match(mensajeGuardarPlantilla(new ErrorApi(422, 'x')), /no son válidos/)
  })

  it('un conflicto 409 conserva la explicación de la API', () => {
    assert.equal(mensajeGuardarPlantilla(new ErrorApi(409, 'Ya existe una plantilla vigente.')), 'Ya existe una plantilla vigente.')
  })

  it('error inesperado o de red muestra el mensaje genérico', async () => {
    for (const e of [new ErrorApi(0, 'sin red'), new ErrorApi(500, 'boom'), new TypeError('x'), new SyntaxError('JSON'), 'texto', undefined]) {
      const r = await resolverGuardado(rechazar(e), 'Guardado.')
      assert.deepEqual(r, { ok: false, error: MENSAJE_GUARDAR_PLANTILLA })
    }
    assert.equal(MENSAJE_GUARDAR_PLANTILLA, 'No fue posible guardar la plantilla. Inténtalo nuevamente.')
  })

  it('un fallo nunca se interpreta como guardado exitoso', async () => {
    for (const estado of [400, 401, 403, 404, 409, 422, 500, 503]) {
      const r = await resolverGuardado(rechazar(new ErrorApi(estado, 'x')), 'Guardado.')
      assert.equal(r.ok, false, `estado ${estado}`)
      assert.ok(!('mensaje' in r))
    }
  })
})

describe('eliminar un proyecto', () => {
  it('traduce 403, 404 y el resto', () => {
    assert.match(mensajeEliminarProyecto(new ErrorApi(403, 'x')), /propietario/)
    assert.match(mensajeEliminarProyecto(new ErrorApi(404, 'x')), /ya no existe/)
    assert.match(mensajeEliminarProyecto(new Error('red')), /No fue posible eliminar/)
  })
})
