// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import { CABECERA_ACCESO, crearCliente, type AlmacenSesion } from '../src/lib/http.ts'
import {
  decidirAcceso, esFragmentoDeAuth, leerEnlaceInvitacion, MENSAJE_ENLACE_INVALIDO, MENSAJE_SIN_VERIFICAR,
} from '../src/lib/invitacion.ts'
import type { Usuario } from '../src/tipos/api.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

// Lo que /verify agrega a redirect_to (GoTrue, flujo implícito).
const HASH_INVITE = '#access_token=at1&expires_at=1&expires_in=3600&refresh_token=rt1&sb=&token_type=bearer&type=invite'
const HASH_RECOVERY = HASH_INVITE.replace('type=invite', 'type=recovery')

const pendiente: Usuario = { id: 'u1', correo: 'm@x.cl', rol: 'profesional', accesoConfigurado: false }
const activo: Usuario = { ...pendiente, accesoConfigurado: true }

function yoQueResponde(usuario: Usuario | Error) {
  const llamadas = { n: 0 }
  const yo = async () => {
    llamadas.n++
    if (usuario instanceof Error) throw usuario
    return usuario
  }
  return { yo, llamadas }
}

describe('acceso: enlace de Supabase', () => {
  it('reconoce la sesión de una invitación y de un enlace renovado (recuperación)', () => {
    assert.deepEqual(leerEnlaceInvitacion(HASH_INVITE), { tipo: 'invitacion', access_token: 'at1', refresh_token: 'rt1' })
    assert.deepEqual(leerEnlaceInvitacion(HASH_RECOVERY), { tipo: 'invitacion', access_token: 'at1', refresh_token: 'rt1' })
  })

  it('un enlace usado o vencido se explica', () => {
    assert.deepEqual(leerEnlaceInvitacion('#error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired&sb='),
      { tipo: 'error', mensaje: MENSAJE_ENLACE_INVALIDO })
  })

  it('la landing reenvía a acceso.html solo fragmentos de Auth', () => {
    assert.equal(esFragmentoDeAuth(HASH_INVITE), true)
    assert.equal(esFragmentoDeAuth('#error_code=otp_expired'), true)
    assert.equal(esFragmentoDeAuth(''), false)
    assert.equal(esFragmentoDeAuth('#como-funciona'), false)
    const landing = leer('src/paginas/landing.ts')
    assert.match(landing, /esFragmentoDeAuth\(window\.location\.hash\)/)
    assert.match(landing, /window\.location\.replace\('\/acceso\.html' \+ window\.location\.hash\)/)
    // Nada del fragmento va a la consola.
    assert.doesNotMatch(landing, /console\.\w+\([^)]*hash/)
  })
})

describe('acceso: qué mostrar', () => {
  it('enlace abierto + cuenta pendiente → «Crea tu contraseña»', async () => {
    const { yo } = yoQueResponde(pendiente)
    const destino = await decidirAcceso({ enlace: leerEnlaceInvitacion(HASH_INVITE), haySesion: true, guardado: null, yo })
    assert.deepEqual(destino, { a: 'crear_clave' })
  })

  it('recargar la página sin el fragmento mantiene el formulario (lo dice el backend)', async () => {
    const { yo } = yoQueResponde(pendiente)
    assert.deepEqual(await decidirAcceso({ enlace: null, haySesion: true, guardado: pendiente, yo }), { a: 'crear_clave' })
  })

  it('una cuenta activa con enlace no repite el flujo: va al panel', async () => {
    const { yo } = yoQueResponde(activo)
    assert.deepEqual(await decidirAcceso({ enlace: leerEnlaceInvitacion(HASH_RECOVERY), haySesion: true, guardado: null, yo }),
      { a: 'panel' })
  })

  it('sesión normal ya activa: directo al panel sin preguntar', async () => {
    const { yo, llamadas } = yoQueResponde(activo)
    assert.deepEqual(await decidirAcceso({ enlace: null, haySesion: true, guardado: activo, yo }), { a: 'panel' })
    assert.equal(llamadas.n, 0)
  })

  it('sin sesión: login normal', async () => {
    const { yo, llamadas } = yoQueResponde(activo)
    assert.deepEqual(await decidirAcceso({ enlace: null, haySesion: false, guardado: null, yo }), { a: 'login' })
    assert.equal(llamadas.n, 0)
  })

  it('enlace vencido: login con el motivo', async () => {
    const { yo } = yoQueResponde(activo)
    assert.deepEqual(await decidirAcceso({ enlace: leerEnlaceInvitacion('#error_code=otp_expired'), haySesion: false, guardado: null, yo }),
      { a: 'login', error: MENSAJE_ENLACE_INVALIDO })
  })

  it('si /yo no responde: con enlace, el formulario; sin enlace, aviso y login', async () => {
    const caido = yoQueResponde(new ErrorApi(0, 'sin conexión'))
    assert.deepEqual(await decidirAcceso({ enlace: leerEnlaceInvitacion(HASH_INVITE), haySesion: true, guardado: null, yo: caido.yo }),
      { a: 'crear_clave' })
    assert.deepEqual(await decidirAcceso({ enlace: null, haySesion: true, guardado: null, yo: caido.yo }),
      { a: 'login', error: MENSAJE_SIN_VERIFICAR })
    const vencida = yoQueResponde(new ErrorApi(401, 'expirada'))
    assert.deepEqual(await decidirAcceso({ enlace: null, haySesion: true, guardado: null, yo: vencida.yo }), { a: 'login' })
  })
})

describe('acceso: cliente HTTP', () => {
  function cliente(respuestas: Response[]) {
    const estado = { token: 'a1' as string | null, refresco: 'r1' as string | null, cierres: 0, pendientes: 0 }
    const sesion: AlmacenSesion = {
      token: () => estado.token,
      refresco: () => estado.refresco,
      guardar: (t) => { estado.token = t.access_token; estado.refresco = t.refresh_token ?? null; return true },
      cerrar: () => { estado.token = null; estado.cierres++ },
    }
    const fetch = async () => (respuestas.length > 1 ? respuestas.shift()! : respuestas[0]).clone()
    const { pedir } = crearCliente({
      base: 'https://api.test', sesion, fetch, alAccesoPendiente: () => { estado.pendientes++ },
    })
    return { pedir, estado }
  }

  it('403 por invitación pendiente → lleva a crear la contraseña sin cerrar la sesión', async () => {
    const { pedir, estado } = cliente([new Response(JSON.stringify({ detail: 'Completa tu invitación creando tu contraseña antes de continuar.' }),
      { status: 403, headers: { 'Content-Type': 'application/json', [CABECERA_ACCESO]: 'pendiente' } })])
    await assert.rejects(pedir('/proyectos'), (e) => e instanceof ErrorApi && e.tipo === 'acceso_pendiente' && e.estado === 403)
    assert.equal(estado.pendientes, 1)
    assert.equal(estado.cierres, 0)
    assert.equal(estado.token, 'a1')
  })

  it('un 403 de permisos normal no redirige', async () => {
    const { pedir, estado } = cliente([new Response(JSON.stringify({ detail: 'Sin permisos' }),
      { status: 403, headers: { 'Content-Type': 'application/json' } })])
    await assert.rejects(pedir('/banco/versiones'), (e) => e instanceof ErrorApi && e.tipo === 'permisos')
    assert.equal(estado.pendientes, 0)
  })

  it('el refresco de sesión sigue funcionando', async () => {
    const { pedir, estado } = cliente([
      new Response('{}', { status: 401 }),
      new Response(JSON.stringify({ access_token: 'a2', refresh_token: 'r2' }), { status: 200 }),
      new Response('[]', { status: 200 }),
    ])
    assert.deepEqual(await pedir('/proyectos'), [])
    assert.equal(estado.token, 'a2')
    assert.equal(estado.pendientes, 0)
  })
})

describe('acceso: página', () => {
  it('pregunta al backend antes de mostrar un formulario', () => {
    const html = leer('acceso.html')
    assert.match(html, /x-init="iniciar\(\)"/)
    assert.match(html, /x-show="!verificando && invitacion"/)
    assert.match(html, /x-show="!verificando && !invitacion"/)
    const pagina = leer('src/paginas/acceso.ts')
    assert.match(pagina, /decidirAcceso\(/)
    // La contraseña no se guarda en el navegador.
    assert.doesNotMatch(pagina, /localStorage|sessionStorage/)
  })

  it('las páginas internas mandan al invitado pendiente a acceso.html', () => {
    const navegacion = leer('src/lib/navegacion.ts')
    assert.match(navegacion, /accesoConfigurado === false/)
    assert.match(leer('src/lib/apiReal.ts'), /alAccesoPendiente: \(\) => window\.location\.replace\('\/acceso\.html'\)/)
  })
})
