// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { bienvenida, horaChile, primerNombre, saludoSegunHora } from '../src/lib/bienvenida.ts'
import type { Usuario } from '../src/tipos/api.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

// Noviembre: Chile está en UTC−3.
const chile = (hora: number, minuto = 0) => new Date(Date.UTC(2026, 10, 5, hora + 3, minuto))

const usuario = (extra: Partial<Usuario> = {}): Usuario => ({ id: 'u1', correo: 'a@b.cl', ...extra })

describe('Bienvenida: nombre', () => {
  it('usa el primer nombre del nombre completo', () => {
    assert.equal(primerNombre('Ángel González Cortés'), 'Ángel')
    assert.equal(primerNombre('  Ángel   González '), 'Ángel')
    assert.equal(primerNombre('Ángel'), 'Ángel')
  })

  it('sin nombre no inventa uno', () => {
    assert.equal(primerNombre(undefined), null)
    assert.equal(primerNombre(null), null)
    assert.equal(primerNombre('   '), null)
  })

  it('usuario con nombre: saludo con primer nombre y mensaje', () => {
    const b = bienvenida(usuario({ nombre: 'Ángel González' }), chile(9))
    assert.equal(b.saludo, 'Buenos días, Ángel')
    assert.equal(b.mensaje, 'Revisa el estado de tus proyectos y estimaciones.')
  })

  it('usuario sin nombre: saludo sin coma ni nombre falso', () => {
    assert.equal(bienvenida(usuario(), chile(9)).saludo, 'Buenos días')
    assert.equal(bienvenida(null, chile(15)).saludo, 'Buenas tardes')
    assert.equal(bienvenida(usuario({ nombre: '  ' }), chile(22)).saludo, 'Buenas noches')
  })
})

describe('Bienvenida: hora de Chile', () => {
  it('días, tardes y noches', () => {
    assert.equal(saludoSegunHora(chile(6)), 'Buenos días')
    assert.equal(saludoSegunHora(chile(11, 59)), 'Buenos días')
    assert.equal(saludoSegunHora(chile(12)), 'Buenas tardes')
    assert.equal(saludoSegunHora(chile(19, 59)), 'Buenas tardes')
    assert.equal(saludoSegunHora(chile(20)), 'Buenas noches')
    assert.equal(saludoSegunHora(chile(0)), 'Buenas noches')
    assert.equal(saludoSegunHora(chile(5, 59)), 'Buenas noches')
  })

  it('usa la hora de Chile, no la del equipo', () => {
    // 01:00 UTC del 5 de noviembre son las 22:00 del 4 en Chile.
    assert.equal(horaChile(new Date(Date.UTC(2026, 10, 5, 1, 0))), 22)
    assert.equal(horaChile(new Date(Date.UTC(2026, 10, 5, 3, 0))), 0)
  })
})

describe('Bienvenida: rol', () => {
  it('el rol no forma parte de la bienvenida, sea cual sea el usuario', () => {
    for (const extra of [{ rol: 'administrador', esAdministradorPrincipal: true }, { rol: 'profesional' }]) {
      assert.deepEqual(Object.keys(bienvenida(usuario({ nombre: 'Ana', ...extra }), chile(9))), ['saludo', 'mensaje'])
    }
  })
})

describe('Bienvenida: diseño del Panel', () => {
  const html = leer('panel.html')
  const css = leer('src/estilos/base.css')

  it('va en el encabezado, antes de los KPI, con datos del usuario', () => {
    const cabecera = html.indexOf('bc-cabecera-tablero"')
    const kpis = html.indexOf('bc-kpis bc-kpis--tablero')
    for (const dato of ['bienvenida.saludo', 'bienvenida.mensaje']) {
      const posicion = html.indexOf(dato)
      assert.ok(posicion > cabecera && posicion < kpis, `${dato} debe estar en el encabezado`)
    }
  })

  it('sin avatar, tarjeta de perfil ni rol visible en el encabezado', () => {
    assert.doesNotMatch(html, /avatar|perfil|bienvenida.rol|administrador principal/i)
    assert.doesNotMatch(css, /bc-cabecera-tablero__rol/)
  })

  it('el Panel lee al usuario de la sesión y no escribe nombres', () => {
    const panel = leer('src/paginas/panel.ts')
    assert.match(panel, /bienvenida\(usuario\(\)\)/)
    assert.match(panel, /prepararNavegacion\(\)\.then/)
  })
})
