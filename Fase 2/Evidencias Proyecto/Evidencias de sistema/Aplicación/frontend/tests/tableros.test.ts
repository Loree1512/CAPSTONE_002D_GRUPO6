// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { coberturaBanco, esPrecioReferencial } from '../src/lib/banco.ts'
import {
  accionSugerida, distribucionEstados, montoCartera, montoPorTipo, ordenarPorPrioridad, requiereAtencion,
} from '../src/lib/cartera.ts'
import { montoCompacto } from '../src/lib/formato.ts'
import type { EstadoProyecto, Proyecto } from '../src/tipos/api.ts'

const proyecto = (id: string, estado: EstadoProyecto | null, costo: number | null, tipo = 'Vivienda', fecha = '2026-10-01'): Proyecto => ({
  id, nombre: id, comuna: 'Quilpué', tipo_obra: tipo, material: 'Albañilería', superficie_m2: 100, pisos: 1,
  estandar_terminaciones: 'medio', estado, costo_total: costo, actualizado_en: fecha,
})

const CARTERA = [
  proyecto('a', 'vigente', 100, 'Vivienda', '2026-10-01'),
  proyecto('b', 'recalcular', 50, 'Ampliación', '2026-09-01'),
  proyecto('c', null, null, 'Vivienda', '2026-10-05'),          // sin estado = sin estimar
  proyecto('d', 'vigente', 300, 'Edificio', '2026-10-03'),
  proyecto('e', 'ejecutada', 900, 'Vivienda', '2026-10-09'),
  proyecto('f', 'recalcular', 70, 'Vivienda', '2026-10-08'),
]

describe('cartera: reglas del tablero', () => {
  it('el monto de la cartera sigue sumando solo las estimaciones vigentes', () => {
    assert.equal(montoCartera(CARTERA), 400)
  })

  it('requieren atención las por recalcular y las sin estimar', () => {
    assert.deepEqual(CARTERA.filter(requiereAtencion).map((p) => p.id), ['b', 'c', 'f'])
  })

  it('distribución por estado en orden fijo, con porcentajes', () => {
    assert.deepEqual(distribucionEstados(CARTERA).map((t) => [t.estado, t.cantidad, Math.round(t.porcentaje)]), [
      ['vigente', 2, 33], ['recalcular', 2, 33], ['sin_estimar', 1, 17], ['ejecutada', 1, 17],
    ])
    assert.deepEqual(distribucionEstados([]).map((t) => t.porcentaje), [0, 0, 0, 0])
  })

  it('prioridad: recalcular, sin estimar, vigentes y ejecutadas; lo reciente primero dentro de cada una', () => {
    assert.deepEqual(ordenarPorPrioridad(CARTERA).map((p) => p.id), ['f', 'b', 'c', 'd', 'a', 'e'])
    // No modifica la lista original.
    assert.equal(CARTERA[0].id, 'a')
  })

  it('cada estado tiene su siguiente paso', () => {
    assert.deepEqual(['b', 'c', 'a', 'e'].map((id) => accionSugerida(CARTERA.find((p) => p.id === id)!)), [
      'Recalcular la estimación', 'Generar la estimación', 'Al día', 'Obra cerrada',
    ])
  })

  it('monto por tipo: solo vigentes, de mayor a menor, barra relativa al mayor', () => {
    assert.deepEqual(montoPorTipo(CARTERA), [
      { tipo: 'Edificio', monto: 300, cantidad: 1, porcentaje: 100 },
      { tipo: 'Vivienda', monto: 100, cantidad: 1, porcentaje: (100 / 300) * 100 },
    ])
    assert.deepEqual(montoPorTipo([]), [])
  })
})

describe('banco: cobertura de precios', () => {
  const fila = (vigente: boolean, precio: number | null, fuente: string | null = null) =>
    ({ vigente, precio_unitario: precio, fuente })

  it('distingue oficina, referencial y sin precio, solo entre partidas vigentes', () => {
    const cobertura = coberturaBanco([
      fila(true, 100, 'Editado por la oficina'),
      fila(true, 200, 'Referencial de mercado'),
      fila(true, 300, 'REFERENCIAL'),
      fila(true, null),
      fila(false, null),                       // dada de baja: no cuenta
    ])
    assert.deepEqual(cobertura, { total: 4, conPrecio: 3, oficina: 1, referencial: 2, sinPrecio: 1, porcentaje: 75 })
  })

  it('sin partidas la cobertura es cero, no NaN', () => {
    assert.equal(coberturaBanco([]).porcentaje, 0)
  })

  it('la regla de precio referencial es la misma que usaba el banco', () => {
    assert.equal(esPrecioReferencial({ fuente: 'Referencial de mercado · Valparaíso' }), true)
    assert.equal(esPrecioReferencial({ fuente: 'Editado por la oficina' }), false)
    assert.equal(esPrecioReferencial({ fuente: null }), false)
  })
})

describe('formato: montos compactos', () => {
  it('abrevia desde un millón y deja completos los menores', () => {
    assert.equal(montoCompacto(671_718_414), '$671,7 M')
    assert.equal(montoCompacto(16_800_000), '$16,8 M')
    assert.equal(montoCompacto(1_000_000), '$1 M')
    assert.match(montoCompacto(950_000), /^\$\s?950\.000$/)
    assert.equal(montoCompacto(null), '—')
  })
})
