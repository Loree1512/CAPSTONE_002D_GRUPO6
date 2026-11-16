// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import { crearMiembros, mensajeMiembros, type ApiMiembros } from '../src/lib/miembros.ts'
import type { CandidatoMiembro, MiembroProyecto, RolProyecto } from '../src/tipos/api.ts'

const miembro = (usuario_id: string, rol: RolProyecto, email: string, nombre: string | null = null): MiembroProyecto =>
  ({ usuario_id, rol, email, nombre, fecha_creacion: null })

const INICIALES = [
  miembro('u-lector', 'lector', 'lector@x.cl'),
  miembro('u-prop', 'propietario', 'loreto@x.cl', 'Loreto Bravo'),
  miembro('u-editor', 'editor', 'camila@x.cl', 'Camila'),
]

const NORA: CandidatoMiembro = { usuario_id: 'u-nuevo', nombre: 'Nora', email: 'nora@x.cl' }
const CANDIDATOS: CandidatoMiembro[] = [NORA, { usuario_id: 'u-otro', nombre: null, email: 'otro@x.cl' }]

function preparar(rol: RolProyecto | null = 'propietario', cambios: Partial<ApiMiembros> = {}) {
  const llamadas: { metodo: string; args: unknown[] }[] = []
  let avisos = 0
  const registrar = (metodo: string, args: unknown[]) => llamadas.push({ metodo, args })
  const api: ApiMiembros = {
    listar: async () => { registrar('listar', []); return structuredClone(INICIALES) },
    candidatos: async (buscar) => {
      registrar('candidatos', [buscar])
      return CANDIDATOS.filter((c) => !buscar || `${c.nombre} ${c.email}`.toLowerCase().includes(buscar.toLowerCase()))
    },
    agregar: async (email, r) => { registrar('agregar', [email, r]); return miembro('u-nuevo', r, email, 'Nora') },
    cambiarRol: async (id, r) => {
      registrar('cambiarRol', [id, r])
      return { ...INICIALES.find((m) => m.usuario_id === id)!, rol: r }
    },
    quitar: async (id) => { registrar('quitar', [id]) },
    ...cambios,
  }
  const gestion = crearMiembros(api, () => { avisos++ })
  gestion.miRol = rol
  return { gestion, llamadas, avisos: () => avisos, de: (m: string) => llamadas.filter((l) => l.metodo === m) }
}

async function cargado(rol: RolProyecto | null = 'propietario', cambios: Partial<ApiMiembros> = {}) {
  const preparado = preparar(rol, cambios)
  await preparado.gestion.cargar()
  return preparado
}

const buscar = (g: ReturnType<typeof preparar>['gestion'], id: string) => g.miembros.find((m) => m.usuario_id === id)!

// Promesa que se resuelve a mano, para simular una respuesta lenta.
function pendiente<T>() {
  let resolver!: (v: T) => void
  const promesa = new Promise<T>((r) => { resolver = r })
  return { promesa, resolver }
}

describe('miembros: permisos por rol', () => {
  it('el propietario ve los controles, salvo en su propia fila', async () => {
    const { gestion } = await cargado('propietario')
    assert.equal(gestion.puedeAdministrar, true)
    assert.equal(gestion.modificable(buscar(gestion, 'u-editor')), true)
    assert.equal(gestion.modificable(buscar(gestion, 'u-lector')), true)
    assert.equal(gestion.modificable(buscar(gestion, 'u-prop')), false)
  })

  for (const rol of ['editor', 'lector', null] as const) {
    it(`${rol ?? 'sin rol'}: solo consulta, sin controles ni llamadas de escritura`, async () => {
      const { gestion, llamadas } = await cargado(rol)
      assert.equal(gestion.puedeAdministrar, false)
      assert.equal(gestion.miembros.length, 3)
      assert.ok(gestion.miembros.every((m) => !gestion.modificable(m)))

      gestion.abrirAgregar()
      assert.equal(gestion.modalAgregar, false)
      await gestion.buscarCandidatos()
      gestion.seleccionado = NORA
      await gestion.agregar()
      assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-editor'), 'lector'), false)
      gestion.pedirQuitar(buscar(gestion, 'u-editor'))
      assert.equal(gestion.porQuitar, null)
      await gestion.quitar()
      assert.deepEqual(llamadas.map((l) => l.metodo), ['listar'])
    })
  }

  it('el propietario nunca se ofrece para cambiar ni quitar', async () => {
    const { gestion, llamadas } = await cargado()
    const propietario = buscar(gestion, 'u-prop')
    assert.equal(await gestion.cambiarRol(propietario, 'lector'), false)
    gestion.pedirQuitar(propietario)
    assert.equal(gestion.porQuitar, null)
    assert.deepEqual(llamadas.map((l) => l.metodo), ['listar'])
  })

  it('ordena como el backend: propietario, editores y lectores', async () => {
    const { gestion } = await cargado()
    assert.deepEqual(gestion.miembros.map((m) => m.rol), ['propietario', 'editor', 'lector'])
    assert.deepEqual(gestion.nombres, { 'u-prop': 'Loreto Bravo', 'u-editor': 'Camila', 'u-lector': 'lector@x.cl' })
  })
})

const tick = () => new Promise((r) => setImmediate(r))

// Abre el modal y espera la primera carga de candidatos.
async function abierto(gestion: ReturnType<typeof preparar>['gestion']) {
  gestion.abrirAgregar()
  await tick()
}

describe('miembros: candidatos', () => {
  it('se cargan al abrir el modal', async () => {
    const { gestion, de } = await cargado()
    gestion.abrirAgregar()
    assert.equal(gestion.cargandoCandidatos, true)
    await tick()
    assert.deepEqual(de('candidatos').map((l) => l.args), [['']])
    assert.deepEqual(gestion.candidatos.map((c) => c.email), ['nora@x.cl', 'otro@x.cl'])
    assert.deepEqual([gestion.cargandoCandidatos, gestion.candidatosCargados], [false, true])
  })

  it('filtra con lo escrito', async () => {
    const { gestion, de } = await cargado()
    await abierto(gestion)
    gestion.busqueda = '  NORA '
    await gestion.buscarCandidatos()
    assert.deepEqual(de('candidatos').at(-1)!.args, ['NORA'])
    assert.deepEqual(gestion.candidatos.map((c) => c.usuario_id), ['u-nuevo'])
  })

  it('una respuesta lenta de una búsqueda anterior no pisa la última', async () => {
    const lenta = pendiente<CandidatoMiembro[]>()
    const { gestion } = await cargado('propietario', {
      candidatos: (buscar) => (buscar === 'n' ? lenta.promesa : Promise.resolve([NORA])),
    })
    gestion.busqueda = 'n'
    const primera = gestion.buscarCandidatos()
    gestion.busqueda = 'nora'
    await gestion.buscarCandidatos()
    lenta.resolver(CANDIDATOS)
    await primera
    assert.deepEqual(gestion.candidatos, [NORA])
    assert.equal(gestion.cargandoCandidatos, false)
  })

  it('sin candidatos queda la lista vacía y cargada', async () => {
    const { gestion } = await cargado('propietario', { candidatos: async () => [] })
    await abierto(gestion)
    assert.deepEqual([gestion.candidatosCargados, gestion.candidatos, gestion.errorCandidatos], [true, [], ''])
  })

  it('un error de carga se muestra', async () => {
    for (const [error, texto] of [
      [new ErrorApi(403, 'x'), /Solo el propietario/],
      [new ErrorApi(0, 'x'), /No se pudo conectar/],
      [new TypeError('red'), /usuarios disponibles/],
    ] as const) {
      const { gestion } = await cargado('propietario', { candidatos: async () => { throw error } })
      await abierto(gestion)
      assert.match(gestion.errorCandidatos, texto)
      assert.deepEqual([gestion.cargandoCandidatos, gestion.candidatosCargados], [false, false])
    }
  })

  it('editor y lector no consultan candidatos', async () => {
    for (const rol of ['editor', 'lector'] as const) {
      const { gestion, de } = await cargado(rol)
      gestion.abrirAgregar()
      await gestion.buscarCandidatos()
      assert.equal(de('candidatos').length, 0)
    }
  })
})

describe('miembros: agregar', () => {
  it('Agregar queda deshabilitado hasta elegir un usuario', async () => {
    const { gestion, de } = await cargado()
    await abierto(gestion)
    assert.equal(gestion.puedeAgregar, false)
    await gestion.agregar()
    assert.equal(de('agregar').length, 0)
    gestion.seleccionar(NORA)
    assert.equal(gestion.puedeAgregar, true)
  })

  it('envía el correo elegido y el rol, actualiza miembros y candidatos', async () => {
    const { gestion, de, avisos } = await cargado()
    await abierto(gestion)
    assert.equal(gestion.rolNuevo, 'editor')
    gestion.seleccionar(gestion.candidatos[0])
    gestion.rolNuevo = 'lector'
    await gestion.agregar()

    assert.deepEqual(de('agregar')[0].args, ['nora@x.cl', 'lector'])
    assert.equal(gestion.modalAgregar, false)
    assert.equal(buscar(gestion, 'u-nuevo').rol, 'lector')
    assert.deepEqual(gestion.miembros.map((m) => m.usuario_id), ['u-prop', 'u-editor', 'u-lector', 'u-nuevo'])
    assert.deepEqual(gestion.candidatos.map((c) => c.usuario_id), ['u-otro'])
    assert.equal(gestion.seleccionado, null)
    assert.match(gestion.aviso, /Nora/)
    assert.equal(avisos(), 1)
    // Sin recargar la lista de miembros.
    assert.equal(de('listar').length, 1)

    // Al volver a abrir, los candidatos se piden de nuevo y sin selección.
    await abierto(gestion)
    assert.equal(de('candidatos').length, 2)
    assert.equal(gestion.seleccionado, null)
  })

  it('un doble envío solo agrega una vez', async () => {
    const respuesta = pendiente<MiembroProyecto>()
    let veces = 0
    const { gestion } = await cargado('propietario', { agregar: () => { veces++; return respuesta.promesa } })
    await abierto(gestion)
    gestion.seleccionar(NORA)
    const primero = gestion.agregar()
    await gestion.agregar()
    assert.equal(gestion.agregando, true)
    assert.equal(gestion.puedeAgregar, false)
    gestion.cancelarAgregar()
    assert.equal(gestion.modalAgregar, true, 'no se cierra mientras envía')
    gestion.seleccionar(CANDIDATOS[1])
    assert.equal(gestion.seleccionado, NORA, 'no cambia la selección mientras envía')
    respuesta.resolver(miembro('u-nuevo', 'editor', 'nora@x.cl'))
    await primero
    assert.equal(veces, 1)
    assert.equal(gestion.agregando, false)
  })

  it('muestra el error de la API y deja reintentar', async () => {
    const casos: [ErrorApi | Error, RegExp][] = [
      [new ErrorApi(422, 'value is not a valid email address'), /Revisa el usuario/],
      [new ErrorApi(403, 'x'), /Solo el propietario/],
      [new ErrorApi(401, 'La sesión expiró.'), /sesión expiró/],
      [new ErrorApi(0, 'x'), /No se pudo conectar/],
      [new TypeError('Failed to fetch'), /No fue posible agregar/],
    ]
    for (const [error, texto] of casos) {
      const { gestion } = await cargado('propietario', { agregar: async () => { throw error } })
      await abierto(gestion)
      gestion.seleccionar(NORA)
      await gestion.agregar()
      assert.match(gestion.errorAgregar, texto)
      assert.deepEqual([gestion.modalAgregar, gestion.agregando, gestion.seleccionado], [true, false, NORA])
      assert.equal(gestion.miembros.length, 3)
    }
  })

  it('si ya no es candidato (404/409), avisa y refresca los candidatos', async () => {
    for (const [error, texto] of [
      [new ErrorApi(409, 'El usuario ya es miembro del proyecto.'), /ya es miembro/],
      [new ErrorApi(404, 'No hay un usuario registrado con ese correo.'), /No hay un usuario registrado/],
    ] as const) {
      const { gestion, de } = await cargado('propietario', { agregar: async () => { throw error } })
      await abierto(gestion)
      gestion.seleccionar(NORA)
      await gestion.agregar()
      await tick()
      assert.match(gestion.errorAgregar, texto)
      assert.equal(gestion.seleccionado, null)
      assert.equal(de('candidatos').length, 2)
    }
  })
})

describe('miembros: cambiar rol', () => {
  it('cambia de editor a lector y actualiza la fila', async () => {
    const { gestion, de, avisos } = await cargado()
    assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-editor'), 'lector'), true)
    assert.deepEqual(de('cambiarRol')[0].args, ['u-editor', 'lector'])
    assert.equal(buscar(gestion, 'u-editor').rol, 'lector')
    assert.equal(avisos(), 1)
  })

  it('elegir el mismo rol o uno no asignable no llama a la API', async () => {
    const { gestion, de } = await cargado()
    assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-editor'), 'editor'), true)
    assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-editor'), 'propietario'), false)
    assert.equal(de('cambiarRol').length, 0)
  })

  it('un cambio a la vez', async () => {
    const respuesta = pendiente<MiembroProyecto>()
    let veces = 0
    const { gestion } = await cargado('propietario', { cambiarRol: () => { veces++; return respuesta.promesa } })
    const primero = gestion.cambiarRol(buscar(gestion, 'u-editor'), 'lector')
    assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-lector'), 'editor'), false)
    respuesta.resolver(miembro('u-editor', 'lector', 'camila@x.cl', 'Camila'))
    assert.equal(await primero, true)
    assert.equal(veces, 1)
  })

  it('si falla, informa y la fila conserva su rol', async () => {
    const { gestion, de } = await cargado('propietario', {
      cambiarRol: async () => { throw new ErrorApi(404, 'El usuario no es miembro del proyecto.') },
    })
    assert.equal(await gestion.cambiarRol(buscar(gestion, 'u-editor'), 'lector'), false)
    assert.match(gestion.error, /no es miembro/)
    // La lista estaba desactualizada: se vuelve a pedir.
    assert.equal(de('listar').length, 2)
    assert.equal(gestion.cambiando, '')
  })
})

describe('miembros: quitar', () => {
  it('pide confirmación propia y quita al confirmar', async () => {
    const { gestion, de, avisos } = await cargado()
    gestion.pedirQuitar(buscar(gestion, 'u-lector'))
    assert.equal(gestion.porQuitar?.usuario_id, 'u-lector')
    assert.equal(de('quitar').length, 0)

    await gestion.quitar()
    assert.deepEqual(de('quitar')[0].args, ['u-lector'])
    assert.equal(gestion.porQuitar, null)
    assert.deepEqual(gestion.miembros.map((m) => m.usuario_id), ['u-prop', 'u-editor'])
    assert.equal(avisos(), 1)
  })

  it('cancelar no quita a nadie', async () => {
    const { gestion, de } = await cargado()
    gestion.pedirQuitar(buscar(gestion, 'u-lector'))
    gestion.cancelarQuitar()
    assert.equal(gestion.porQuitar, null)
    assert.equal(de('quitar').length, 0)
  })

  it('un doble clic no envía dos DELETE', async () => {
    const respuesta = pendiente<void>()
    let veces = 0
    const { gestion } = await cargado('propietario', { quitar: () => { veces++; return respuesta.promesa } })
    gestion.pedirQuitar(buscar(gestion, 'u-lector'))
    const primero = gestion.quitar()
    await gestion.quitar()
    gestion.cancelarQuitar()
    assert.notEqual(gestion.porQuitar, null, 'no se cierra mientras quita')
    respuesta.resolver()
    await primero
    assert.equal(veces, 1)
  })

  it('un error mantiene el diálogo con el mensaje', async () => {
    for (const [error, texto] of [
      [new ErrorApi(409, 'El propietario del proyecto no se puede quitar.'), /no se puede quitar/],
      [new ErrorApi(403, 'x'), /Solo el propietario/],
      [new TypeError('red'), /No fue posible quitar/],
    ] as const) {
      const { gestion } = await cargado('propietario', { quitar: async () => { throw error } })
      gestion.pedirQuitar(buscar(gestion, 'u-lector'))
      await gestion.quitar()
      assert.match(gestion.errorQuitar, texto)
      assert.equal(gestion.porQuitar?.usuario_id, 'u-lector')
      assert.equal(gestion.miembros.length, 3)
    }
  })
})

describe('miembros: carga', () => {
  it('un error de carga se muestra y no deja la lista como cargada', async () => {
    const { gestion } = await cargado('lector', { listar: async () => { throw new ErrorApi(0, 'x') } })
    assert.equal(gestion.cargado, false)
    assert.match(gestion.error, /No se pudo conectar/)
  })

  it('mensajes por estado', () => {
    assert.match(mensajeMiembros(new ErrorApi(401, 'x'), 'cargar'), /sesión expiró/)
    assert.match(mensajeMiembros(new ErrorApi(404, 'Proyecto no encontrado'), 'cargar'), /Proyecto no encontrado/)
    assert.match(mensajeMiembros(new ErrorApi(500, 'x'), 'cargar'), /No se pudieron cargar/)
  })
})
