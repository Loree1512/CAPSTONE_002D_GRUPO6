// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { afterEach, describe, it } from 'node:test'

/* DOM mínimo: lo justo para ejercitar confirmar() sin navegador. */
class Nodo {
  tag: string; className = ''; id = ''; type = ''; textContent = ''
  style: Record<string, string> = {}; hijos: Nodo[] = []; atributos: Record<string, string> = {}
  oyentes: Record<string, Array<(e: unknown) => void>> = {}
  quitado = false
  constructor(tag: string) { this.tag = tag }
  append(...n: Nodo[]) { this.hijos.push(...n) }
  setAttribute(k: string, v: string) { this.atributos[k] = v }
  addEventListener(t: string, f: (e: unknown) => void) { (this.oyentes[t] ??= []).push(f) }
  remove() { this.quitado = true }
  focus() { documento.activeElement = this }
  emitir(t: string, e: unknown = {}) { (this.oyentes[t] ?? []).forEach((f) => f({ target: this, ...(e as object) })) }
  buscar(pred: (n: Nodo) => boolean): Nodo | undefined {
    if (pred(this)) return this
    for (const h of this.hijos) { const r = h.buscar(pred); if (r) return r }
    return undefined
  }
}
const teclas: Array<(e: unknown) => void> = []
const documento = {
  activeElement: null as unknown,
  body: new Nodo('body'),
  createElement: (t: string) => new Nodo(t),
  addEventListener: (t: string, f: (e: unknown) => void) => { if (t === 'keydown') teclas.push(f) },
  removeEventListener: (t: string, f: (e: unknown) => void) => { if (t === 'keydown') teclas.splice(teclas.indexOf(f), 1) },
}
// confirmar() comprueba `instanceof HTMLElement` para devolver el foco.
;(globalThis as unknown as Record<string, unknown>).HTMLElement = Nodo
;(globalThis as unknown as Record<string, unknown>).document = documento

const { confirmar } = await import('../src/lib/confirmar.ts')

const abrir = (extra = {}) => {
  const promesa = confirmar({ rotulo: 'Presupuesto', titulo: 'Quitar partida', mensaje: '¿Quitar «Mano de obra»?', confirmar: 'Quitar', ...extra })
  const capa = documento.body.hijos.at(-1) as Nodo
  const boton = (texto: string) => capa.buscar((n) => n.tag === 'button' && n.textContent === texto) as Nodo
  return { promesa, capa, boton }
}

afterEach(() => { documento.body.hijos.length = 0; teclas.length = 0; documento.activeElement = null })

describe('confirmar: diálogo propio', () => {
  it('usa el estilo de modal de BuildCast, con título, mensaje y accesibilidad', () => {
    const { capa } = abrir()
    assert.equal(capa.className, 'bc-capa')
    const modal = capa.hijos[0]
    assert.equal(modal.className, 'bc-modal')
    assert.equal(modal.atributos.role, 'alertdialog')
    assert.equal(modal.atributos['aria-modal'], 'true')
    assert.ok(modal.buscar((n) => n.textContent === 'Quitar partida'))
    assert.ok(modal.buscar((n) => n.textContent === '¿Quitar «Mano de obra»?'))
  })

  it('el foco empieza en Cancelar, no en la acción', () => {
    const { boton } = abrir()
    assert.equal(documento.activeElement, boton('Cancelar'))
  })

  it('el botón de acción confirma y cierra el diálogo', async () => {
    const { promesa, capa, boton } = abrir()
    boton('Quitar').emitir('click')
    assert.equal(await promesa, true)
    assert.equal(capa.quitado, true)
  })

  it('Cancelar no confirma', async () => {
    const { promesa, boton } = abrir()
    boton('Cancelar').emitir('click')
    assert.equal(await promesa, false)
  })

  it('Escape cancela y deja de escuchar el teclado', async () => {
    const { promesa } = abrir()
    teclas[0]({ key: 'Escape', preventDefault() {}, stopPropagation() {} })
    assert.equal(await promesa, false)
    assert.equal(teclas.length, 0)
  })

  it('un clic fuera del cuadro cancela; uno dentro no', async () => {
    const { promesa, capa } = abrir()
    capa.emitir('click', { target: capa.hijos[0] })
    capa.emitir('click', { target: capa })
    assert.equal(await promesa, false)
  })

  it('textos de botones personalizados', () => {
    const { boton } = abrir({ confirmar: 'Salir sin guardar', cancelar: 'Seguir editando' })
    assert.ok(boton('Salir sin guardar'))
    assert.ok(boton('Seguir editando'))
  })
})

describe('confirmar: las páginas ya no usan el cuadro nativo', () => {
  it('no queda ningún window.confirm en src/', () => {
    for (const archivo of readdirSync(new URL('../src/paginas/', import.meta.url))) {
      assert.doesNotMatch(readFileSync(new URL(`../src/paginas/${archivo}`, import.meta.url), 'utf8'), /(window\.)?\bconfirm\(/, archivo)
    }
  })
})
