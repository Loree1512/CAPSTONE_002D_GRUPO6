// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import { crearCliente, MENSAJES, type AlmacenSesion, type Tokens } from '../src/lib/http.ts'

const json = (estado: number, cuerpo: unknown) =>
  new Response(JSON.stringify(cuerpo), { status: estado, headers: { 'Content-Type': 'application/json' } })
const texto = (estado: number, cuerpo: string) => new Response(cuerpo, { status: estado })

type Respuesta = Response | Error | (() => Response | Promise<Response>)

interface Llamada { url: string; metodo: string; auth: string | null; cuerpo: unknown }

/** Responde según la ruta; cada ruta consume su lista en orden y repite la última. */
function preparar(rutas: Record<string, Respuesta[]>, tokens: Partial<Tokens> = { access_token: 'a1', refresh_token: 'r1' }) {
  const llamadas: Llamada[] = []
  const estado = { token: tokens.access_token ?? null, refresco: tokens.refresh_token ?? null, cierres: 0, salidas: 0 }

  const sesion: AlmacenSesion = {
    token: () => estado.token,
    refresco: () => estado.refresco,
    guardar: (t) => { estado.token = t.access_token; estado.refresco = t.refresh_token ?? null; return true },
    cerrar: () => { estado.token = null; estado.refresco = null; estado.cierres++ },
  }

  const fetch = async (url: string, init: RequestInit) => {
    const ruta = url.replace('https://api.test', '')
    const cabeceras = init.headers as Record<string, string>
    llamadas.push({
      url: ruta, metodo: init.method ?? 'GET', auth: cabeceras.Authorization ?? null,
      cuerpo: init.body ? JSON.parse(init.body as string) : undefined,
    })
    const cola = rutas[ruta]
    if (!cola) throw new Error(`ruta no preparada: ${ruta}`)
    const siguiente = cola.length > 1 ? cola.shift()! : cola[0]
    if (siguiente instanceof Error) throw siguiente
    const respuesta = typeof siguiente === 'function' ? await siguiente() : siguiente
    return respuesta.clone()
  }

  const { pedir } = crearCliente({ base: 'https://api.test', sesion, fetch, alCerrarSesion: () => { estado.salidas++ } })
  const de = (ruta: string) => llamadas.filter((l) => l.url === ruta)
  return { pedir, llamadas, estado, de }
}

async function falla(promesa: Promise<unknown>): Promise<ErrorApi> {
  try {
    await promesa
  } catch (e) {
    assert.ok(e instanceof ErrorApi, `se esperaba ErrorApi, llegó ${e}`)
    return e
  }
  assert.fail('se esperaba un error')
}

const REFRESCO_OK = json(200, { access_token: 'a2', refresh_token: 'r2', token_type: 'bearer' })

describe('pedir: clasificación de errores', () => {
  it('fallo de fetch → conexión, sin mencionar CORS ni cerrar sesión', async () => {
    const { pedir, estado } = preparar({ '/proyectos': [new TypeError('Failed to fetch')] })
    const error = await falla(pedir('/proyectos'))
    assert.deepEqual([error.estado, error.tipo, error.message], [0, 'conexion', MENSAJES.conexion])
    assert.doesNotMatch(error.message, /CORS/)
    assert.equal(estado.cierres, 0)
  })

  for (const [codigo, tipo, porDefecto] of [
    [403, 'permisos', MENSAJES.permisos],
    [404, 'no_encontrado', MENSAJES.noEncontrado],
    [409, 'conflicto', 'La solicitud falló (409).'],
    [422, 'validacion', MENSAJES.validacion],
  ] as const) {
    it(`${codigo} → ${tipo}, usa el detalle de la API y no cierra sesión`, async () => {
      const { pedir, estado, de } = preparar({ '/x': [json(codigo, { detail: 'Detalle de la API.' })] })
      const error = await falla(pedir('/x'))
      assert.deepEqual([error.estado, error.tipo, error.message], [codigo, tipo, 'Detalle de la API.'])

      const sinDetalle = preparar({ '/x': [json(codigo, {})] })
      assert.equal((await falla(sinDetalle.pedir('/x'))).message, porDefecto)
      assert.deepEqual([estado.cierres, estado.salidas, de('/autenticacion/refrescar').length], [0, 0, 0])
    })
  }

  it('422 de Pydantic muestra el primer mensaje', async () => {
    const { pedir } = preparar({ '/x': [json(422, { detail: [{ msg: 'La unidad admite hasta 20 caracteres.' }] })] })
    assert.equal((await falla(pedir('/x'))).message, 'La unidad admite hasta 20 caracteres.')
  })

  for (const codigo of [500, 502, 503, 504]) {
    it(`${codigo} → servidor, con o sin JSON, sin cerrar sesión`, async () => {
      for (const respuesta of [json(codigo, { detail: 'Error interno del servidor.' }), texto(codigo, '<html>Gateway</html>')]) {
        const { pedir, estado } = preparar({ '/x': [respuesta] })
        const error = await falla(pedir('/x'))
        assert.deepEqual([error.estado, error.tipo, error.message], [codigo, 'servidor', MENSAJES.servidor])
        assert.equal(estado.cierres, 0)
      }
    })
  }

  it('2xx con cuerpo que no es JSON → respuesta inválida', async () => {
    const { pedir } = preparar({ '/x': [texto(200, '<!doctype html><p>Vercel</p>')] })
    const error = await falla(pedir('/x'))
    assert.deepEqual([error.estado, error.tipo, error.message], [200, 'respuesta_invalida', MENSAJES.invalida])
  })

  it('2xx vacío (204) devuelve null y JSON válido se entrega tal cual', async () => {
    const { pedir } = preparar({ '/vacio': [new Response(null, { status: 204 })], '/datos': [json(200, [{ id: 1 }])] })
    assert.equal(await pedir('/vacio'), null)
    assert.deepEqual(await pedir('/datos'), [{ id: 1 }])
  })

  it('envía el token, el método y el cuerpo', async () => {
    const { pedir, llamadas } = preparar({ '/x': [json(201, {})] })
    await pedir('/x', { metodo: 'POST', cuerpo: { nombre: 'A' } })
    assert.deepEqual(llamadas, [{ url: '/x', metodo: 'POST', auth: 'Bearer a1', cuerpo: { nombre: 'A' } }])
  })
})

describe('pedir: 204 No Content', () => {
  const sinContenido = () => new Response(null, { status: 204 })

  for (const ruta of ['/proyectos/p1', '/proyectos/p1/miembros/u1']) {
    it(`DELETE ${ruta} con 204 es éxito y devuelve null`, async () => {
      const { pedir, estado, llamadas } = preparar({ [ruta]: [sinContenido()] })
      assert.equal(await pedir(ruta, { metodo: 'DELETE' }), null)
      assert.deepEqual(llamadas.map((l) => [l.metodo, l.auth]), [['DELETE', 'Bearer a1']])
      assert.equal(estado.cierres, 0)
    })
  }

  it('no intenta parsear JSON: un 204 nunca da respuesta inválida', async () => {
    const parse = JSON.parse
    let llamadas = 0
    JSON.parse = (...args: Parameters<typeof JSON.parse>) => { llamadas++; return parse(...args) }
    try {
      const { pedir } = preparar({ '/proyectos/p1': [sinContenido()] })
      await pedir('/proyectos/p1', { metodo: 'DELETE' })
    } finally {
      JSON.parse = parse
    }
    assert.equal(llamadas, 0)
  })

  it('204 después de renovar la sesión también es éxito', async () => {
    const { pedir, de } = preparar({
      '/proyectos/p1/miembros/u1': [json(401, {}), sinContenido()],
      '/autenticacion/refrescar': [REFRESCO_OK],
    })
    assert.equal(await pedir('/proyectos/p1/miembros/u1', { metodo: 'DELETE' }), null)
    assert.equal(de('/proyectos/p1/miembros/u1').length, 2)
  })
})

describe('pedir: renovación de sesión ante 401', () => {
  it('401 → refresca, guarda ambos tokens y repite la petición una sola vez', async () => {
    const { pedir, estado, llamadas } = preparar({
      '/proyectos': [json(401, { detail: 'Token inválido o expirado' }), json(201, { id: 'p1' })],
      '/autenticacion/refrescar': [REFRESCO_OK],
    })
    assert.deepEqual(await pedir('/proyectos', { metodo: 'POST', cuerpo: { nombre: 'Casa' } }), { id: 'p1' })

    assert.deepEqual(llamadas.map((l) => [l.url, l.auth]), [
      ['/proyectos', 'Bearer a1'],
      // El refresco no lleva el access token vencido.
      ['/autenticacion/refrescar', null],
      ['/proyectos', 'Bearer a2'],
    ])
    assert.deepEqual(llamadas[1].cuerpo, { refresh_token: 'r1' })
    // La repetición lleva el mismo cuerpo: el formulario no se pierde.
    assert.deepEqual(llamadas[2].cuerpo, { nombre: 'Casa' })
    assert.deepEqual([estado.token, estado.refresco, estado.cierres, estado.salidas], ['a2', 'r2', 0, 0])
  })

  it('si la repetición vuelve a dar 401 no hay ciclo ni cierre de sesión', async () => {
    const { pedir, estado, de } = preparar({
      '/x': [json(401, {})],
      '/autenticacion/refrescar': [REFRESCO_OK],
    })
    const error = await falla(pedir('/x'))
    assert.deepEqual([error.estado, error.message], [401, MENSAJES.sesionRechazada])
    assert.deepEqual([de('/x').length, de('/autenticacion/refrescar').length], [2, 1])
    assert.equal(estado.cierres, 0)
  })

  it('refresh rechazado por Supabase (401) → cierra sesión y lleva al acceso', async () => {
    const { pedir, estado, de } = preparar({
      '/x': [json(401, {})],
      '/autenticacion/refrescar': [json(401, { detail: 'La sesión expiró. Vuelve a iniciar sesión.' })],
    })
    const error = await falla(pedir('/x'))
    assert.deepEqual([error.estado, error.tipo, error.message], [401, 'autenticacion', MENSAJES.sesionVencida])
    assert.deepEqual([estado.token, estado.refresco, estado.cierres, estado.salidas], [null, null, 1, 1])
    assert.equal(de('/x').length, 1)
  })

  it('sin refresh token guardado (sesión antigua) → cierra sesión', async () => {
    const { pedir, estado, de } = preparar({ '/x': [json(401, {})] }, { access_token: 'a1' })
    await falla(pedir('/x'))
    assert.deepEqual([estado.cierres, estado.salidas, de('/autenticacion/refrescar').length], [1, 1, 0])
  })

  for (const [nombre, respuesta, estadoEsperado] of [
    ['503', json(503, { detail: 'No se pudo validar la sesión en este momento.' }), 503],
    ['500', json(500, { detail: 'Error interno del servidor.' }), 503],
    ['sin red', new TypeError('Failed to fetch'), 0],
    ['respuesta no JSON', texto(200, '<html>'), 503],
    ['JSON sin tokens', json(200, { ok: true }), 503],
  ] as const) {
    it(`refresh con ${nombre} → conserva la sesión y da un error recuperable`, async () => {
      const { pedir, estado, de } = preparar({ '/x': [json(401, {})], '/autenticacion/refrescar': [respuesta] })
      const error = await falla(pedir('/x', { metodo: 'POST', cuerpo: { a: 1 } }))
      assert.deepEqual([error.estado, error.message], [estadoEsperado, MENSAJES.renovacion])
      assert.deepEqual([estado.token, estado.refresco, estado.cierres, estado.salidas], ['a1', 'r1', 0, 0])
      // No repite la petición original sin sesión nueva.
      assert.equal(de('/x').length, 1)
    })
  }

  it('varios 401 simultáneos comparten un único refresco', async () => {
    let soltar!: () => void
    const espera = new Promise<void>((r) => { soltar = r })
    const { pedir, estado, de } = preparar({
      '/a': [json(401, {}), json(200, 'a')],
      '/b': [json(401, {}), json(200, 'b')],
      '/c': [json(401, {}), json(200, 'c')],
      '/autenticacion/refrescar': [async () => { await espera; return REFRESCO_OK }],
    })
    const pendientes = Promise.all([pedir('/a'), pedir('/b'), pedir('/c')])
    await new Promise((r) => setImmediate(r))
    soltar()
    assert.deepEqual(await pendientes, ['a', 'b', 'c'])
    assert.equal(de('/autenticacion/refrescar').length, 1)
    // Cada una salió con el token viejo y se repitió una vez con el nuevo.
    for (const ruta of ['/a', '/b', '/c']) assert.deepEqual(de(ruta).map((l) => l.auth), ['Bearer a1', 'Bearer a2'])
    assert.equal(estado.cierres, 0)
  })

  it('un 401 que llega después de otro refresco solo repite, no refresca de nuevo', async () => {
    let soltarB!: () => void
    const esperaB = new Promise<void>((r) => { soltarB = r })
    const { pedir, de } = preparar({
      '/a': [json(401, {}), json(200, 'a')],
      // /b salió con el token viejo y su 401 llega cuando el refresco ya terminó.
      '/b': [async () => { await esperaB; return json(401, {}) }, json(200, 'b')],
      '/autenticacion/refrescar': [REFRESCO_OK],
    })
    const b = pedir('/b')
    assert.equal(await pedir('/a'), 'a')
    soltarB()
    assert.equal(await b, 'b')
    assert.equal(de('/autenticacion/refrescar').length, 1)
  })

  it('un 401 sin autenticación (login fallido) no intenta refrescar ni cierra sesión', async () => {
    const { pedir, estado, de } = preparar({ '/autenticacion/iniciar-sesion': [json(401, { detail: 'Credenciales inválidas' })] })
    const error = await falla(pedir('/autenticacion/iniciar-sesion', { metodo: 'POST', cuerpo: {}, autenticado: false }))
    assert.equal(error.message, 'Credenciales inválidas')
    assert.deepEqual([de('/autenticacion/refrescar').length, estado.cierres], [0, 0])
  })

  it('403, 404, 422 y 500 nunca cierran sesión ni refrescan', async () => {
    for (const codigo of [403, 404, 422, 500]) {
      const { pedir, estado, de } = preparar({ '/x': [json(codigo, {})] })
      await falla(pedir('/x'))
      assert.deepEqual([estado.cierres, estado.salidas, de('/autenticacion/refrescar').length], [0, 0, 0], String(codigo))
    }
  })
})
