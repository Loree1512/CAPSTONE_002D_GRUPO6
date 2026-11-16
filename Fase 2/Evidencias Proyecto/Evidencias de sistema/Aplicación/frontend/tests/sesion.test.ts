// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { beforeEach, describe, it } from 'node:test'

// localStorage en memoria: sesion.ts solo lo usa al llamarse.
const datos = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (k: string) => datos.get(k) ?? null,
    setItem: (k: string, v: string) => { datos.set(k, String(v)) },
    removeItem: (k: string) => { datos.delete(k) },
  },
})

const { cerrar, guardar, haySesion, refresco, token } = await import('../src/lib/sesion.ts')

describe('sesión guardada', () => {
  beforeEach(() => datos.clear())

  it('guarda access y refresh token', () => {
    assert.equal(guardar({ access_token: 'a1', refresh_token: 'r1' }), true)
    assert.deepEqual([token(), refresco(), haySesion()], ['a1', 'r1', true])
  })

  it('sin refresh token no queda uno anterior', () => {
    guardar({ access_token: 'a1', refresh_token: 'r1' })
    guardar({ access_token: 'a2' })
    assert.deepEqual([token(), refresco()], ['a2', null])
  })

  it('sin access token no guarda nada', () => {
    assert.equal(guardar({ refresh_token: 'r1' }), false)
    assert.equal(datos.size, 0)
  })

  it('cerrar() elimina ambos tokens y el usuario', () => {
    guardar({ access_token: 'a1', refresh_token: 'r1' })
    datos.set('buildcast.usuario', '{}')
    datos.set('buildcast.config', 'otra cosa')
    cerrar()
    assert.deepEqual([token(), refresco(), haySesion()], [null, null, false])
    assert.deepEqual([...datos.keys()], ['buildcast.config'])
  })
})
