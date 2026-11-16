// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { crearEliminacion } from '../src/lib/eliminacionProyecto.ts'
import { ErrorApi } from '../src/lib/errores.ts'

function preparar(resultado: () => Promise<unknown>) {
  const llamadas = { eliminar: 0, exito: 0 }
  const eliminacion = crearEliminacion({
    eliminar: () => { llamadas.eliminar++; return resultado() },
    alExito: () => { llamadas.exito++ },
  })
  return { eliminacion, llamadas }
}

describe('diálogo de eliminar proyecto', () => {
  it('abrir solo muestra el diálogo, no elimina', () => {
    const { eliminacion, llamadas } = preparar(async () => undefined)
    eliminacion.abrir()
    assert.equal(eliminacion.abierto, true)
    assert.equal(llamadas.eliminar, 0)
  })

  it('cancelar cierra sin llamar al DELETE', () => {
    const { eliminacion, llamadas } = preparar(async () => undefined)
    eliminacion.abrir()
    eliminacion.cancelar()
    assert.equal(eliminacion.abierto, false)
    assert.deepEqual(llamadas, { eliminar: 0, exito: 0 })
  })

  it('confirmar llama al DELETE una vez y, con 204, cierra y redirige', async () => {
    const { eliminacion, llamadas } = preparar(async () => undefined)
    eliminacion.abrir()
    await eliminacion.confirmar()
    assert.deepEqual(llamadas, { eliminar: 1, exito: 1 })
    assert.equal(eliminacion.abierto, false)
    assert.equal(eliminacion.error, '')
  })

  it('un doble clic no envía dos DELETE', async () => {
    let terminar!: () => void
    const { eliminacion, llamadas } = preparar(() => new Promise<void>((r) => { terminar = r }))
    eliminacion.abrir()
    const primero = eliminacion.confirmar()
    await eliminacion.confirmar()
    assert.equal(eliminacion.eliminando, true)
    eliminacion.cancelar()
    assert.equal(eliminacion.abierto, true)
    terminar()
    await primero
    assert.equal(llamadas.eliminar, 1)
  })

  it('un error no redirige, mantiene el diálogo y muestra el mensaje', async () => {
    for (const [estado, texto] of [[403, /propietario/], [404, /ya no existe/], [500, /No fue posible eliminar/]] as const) {
      const { eliminacion, llamadas } = preparar(async () => { throw new ErrorApi(estado, 'x') })
      eliminacion.abrir()
      await eliminacion.confirmar()
      assert.equal(llamadas.exito, 0)
      assert.equal(eliminacion.abierto, true)
      assert.equal(eliminacion.eliminando, false)
      assert.match(eliminacion.error, texto)
    }
  })

  it('un error de red tampoco cuenta como éxito y permite reintentar', async () => {
    let falla = true
    const { eliminacion, llamadas } = preparar(async () => { if (falla) throw new TypeError('red') })
    eliminacion.abrir()
    await eliminacion.confirmar()
    assert.equal(llamadas.exito, 0)
    falla = false
    await eliminacion.confirmar()
    assert.deepEqual(llamadas, { eliminar: 2, exito: 1 })
  })
})
