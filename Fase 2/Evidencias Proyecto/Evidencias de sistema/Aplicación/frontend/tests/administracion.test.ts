// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import {
  crearPanelAdministracion, etiquetaEstado, etiquetaRolGlobal, mensajeAdministracion, progreso,
  type ApiAdministracion,
} from '../src/lib/administracion.ts'
import { esAdministrador, mostrarSoloAdmin } from '../src/lib/rolGlobal.ts'
import type { SolicitudAdministrador, UsuarioAdministrado } from '../src/tipos/administracion.ts'

const PRINCIPALES = [
  { administrador_id: 'p-1', nombre: 'Ángel', email: 'angel@x.cl' },
  { administrador_id: 'p-2', nombre: 'Loreto', email: 'loreto@x.cl' },
  { administrador_id: 'p-3', nombre: 'Camila', email: 'camila@x.cl' },
]

function solicitud(votos: number, cambios: Partial<SolicitudAdministrador> = {}): SolicitudAdministrador {
  return {
    id: 's-1', usuario_id: 'u-juan', usuario_nombre: 'Juan', usuario_email: 'juan@x.cl', solicitado_por: 'p-1',
    estado: votos >= 3 ? 'aprobada' : 'pendiente', fecha_creacion: '2026-11-01T10:00:00Z',
    fecha_resolucion: votos >= 3 ? '2026-11-02T10:00:00Z' : null,
    aprobaciones_recibidas: votos, aprobaciones_requeridas: 3,
    aprobaciones: PRINCIPALES.map((p, i) => ({ ...p, aprobada: i < votos, fecha: i < votos ? '2026-11-01' : null })),
    puedo_aprobar: votos < 3,
    ...cambios,
  }
}

const usuario = (id: string, nombre: string, rol: 'administrador' | 'profesional', principal = false,
  pendiente: SolicitudAdministrador | null = null): UsuarioAdministrado => ({
  id, nombre, email: `${nombre.toLowerCase()}@x.cl`, rol_global: rol, es_administrador_principal: principal,
  fecha_creacion: '2026-10-01T10:00:00Z', estado: 'activo', solicitud_pendiente: pendiente,
  puede_solicitar_administrador: rol === 'profesional' && !pendiente,
})

const INICIALES = () => [
  usuario('p-1', 'Ángel', 'administrador', true),
  usuario('p-2', 'Loreto', 'administrador', true),
  usuario('p-3', 'Camila', 'administrador', true),
  usuario('u-juan', 'Juan', 'profesional'),
]

function preparar(cambios: Partial<ApiAdministracion> = {}, copiar?: (t: string) => Promise<void>) {
  const llamadas: { metodo: string; args: unknown[] }[] = []
  const api: ApiAdministracion = {
    listar: async () => { llamadas.push({ metodo: 'listar', args: [] }); return INICIALES() },
    crear: async (datos) => {
      llamadas.push({ metodo: 'crear', args: [datos] })
      return {
        usuario: { ...usuario('u-nueva', datos.nombre, 'profesional'), email: datos.email, estado: 'pendiente' },
        modo: 'enlace', enlace: 'https://ejemplo.supabase.co/auth/v1/verify?token=SECRETO',
      }
    },
    solicitar: async (id) => { llamadas.push({ metodo: 'solicitar', args: [id] }); return solicitud(0) },
    aprobar: async (id) => { llamadas.push({ metodo: 'aprobar', args: [id] }); return solicitud(1, { puedo_aprobar: false }) },
    renovar: async (id) => {
      llamadas.push({ metodo: 'renovar', args: [id] })
      const n = llamadas.filter((l) => l.metodo === 'renovar').length
      return {
        usuario: { ...usuario(id, 'Marta', 'profesional'), estado: 'pendiente' },
        modo: 'enlace', enlace: `https://ejemplo.supabase.co/auth/v1/verify?token=RENOVADO-${n}`,
      }
    },
    ...cambios,
  }
  const panel = crearPanelAdministracion(api, copiar ?? (async () => {}))
  return { panel, llamadas, de: (m: string) => llamadas.filter((l) => l.metodo === m) }
}

describe('administración: navegación', () => {
  it('Administración solo se muestra a administradores', () => {
    assert.equal(esAdministrador({ id: 'a', correo: 'a@x.cl', rol: 'administrador' }), true)
    assert.equal(esAdministrador({ id: 'b', correo: 'b@x.cl', rol: 'profesional' }), false)
    assert.equal(esAdministrador({ id: 'c', correo: 'c@x.cl' }), false)
    assert.equal(esAdministrador(null), false)

    const enlaces = [{ hidden: true }, { hidden: true }]
    const raiz = { querySelectorAll: (s: string) => { assert.equal(s, '[data-solo-admin]'); return enlaces } }
    mostrarSoloAdmin(raiz, { id: 'a', correo: 'a@x.cl', rol: 'administrador' })
    assert.deepEqual(enlaces.map((e) => e.hidden), [false, false])
    mostrarSoloAdmin(raiz, { id: 'b', correo: 'b@x.cl', rol: 'profesional' })
    assert.deepEqual(enlaces.map((e) => e.hidden), [true, true])
    mostrarSoloAdmin(raiz, null)
    assert.deepEqual(enlaces.map((e) => e.hidden), [true, true])
  })

  it('todas las páginas tienen el enlace oculto por defecto', () => {
    for (const pagina of ['panel', 'proyectos', 'proyecto', 'precios', 'plantillas', 'configuracion', 'estimacion', 'administracion']) {
      const html = readFileSync(new URL(`../${pagina}.html`, import.meta.url), 'utf8')
      assert.match(html, /<a href="\/administracion\.html"[^>]*\bdata-solo-admin\b[^>]*\bhidden\b[^>]*>Administración<\/a>/, pagina)
    }
  })

  it('el panel no interpreta HTML de los datos', () => {
    const html = readFileSync(new URL('../administracion.html', import.meta.url), 'utf8')
    assert.doesNotMatch(html, /x-html/)
  })
})

describe('administración: listado y errores', () => {
  it('carga los usuarios', async () => {
    const { panel } = preparar()
    await panel.cargar()
    assert.equal(panel.cargado, true)
    assert.deepEqual(panel.usuarios.map((u) => etiquetaRolGlobal(u)),
      ['Admin. principal', 'Admin. principal', 'Admin. principal', 'Profesional'])
    assert.equal(etiquetaRolGlobal({ rol_global: 'administrador', es_administrador_principal: false }), 'Administrador')
    assert.equal(etiquetaEstado('pendiente'), 'Invitación pendiente')
    assert.equal(etiquetaEstado(null), '—')
  })

  it('un profesional ve que la sección no es para él', async () => {
    const { panel } = preparar({ listar: async () => { throw new ErrorApi(403, 'Solo un administrador puede gestionar usuarios.') } })
    await panel.cargar()
    assert.equal(panel.sinPermiso, true)
    assert.equal(panel.error, 'Esta sección es solo para administradores.')
    assert.deepEqual(panel.usuarios, [])
  })

  it('traduce los errores por acción', () => {
    assert.equal(mensajeAdministracion(new ErrorApi(0, 'x'), 'cargar'),
      'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo nuevamente.')
    assert.equal(mensajeAdministracion(new ErrorApi(401, 'x'), 'crear'), 'Tu sesión expiró. Vuelve a iniciar sesión.')
    assert.equal(mensajeAdministracion(new ErrorApi(403, 'x'), 'aprobar'), 'Solo los administradores principales aprueban promociones.')
    assert.equal(mensajeAdministracion(new ErrorApi(409, 'Ya existe un usuario con ese correo.'), 'crear'),
      'Ya existe un usuario con ese correo.')
    assert.equal(mensajeAdministracion(new ErrorApi(500, 'detalle técnico'), 'solicitar'),
      'No fue posible crear la solicitud. Inténtalo nuevamente.')
    assert.equal(mensajeAdministracion(new Error('x'), 'cargar'), 'No se pudieron cargar los usuarios. Inténtalo nuevamente.')
  })
})

describe('administración: crear usuario', () => {
  it('crea un profesional y muestra el enlace una sola vez', async () => {
    const copias: string[] = []
    const { panel, de } = preparar({}, async (t) => { copias.push(t) })
    await panel.cargar()
    panel.abrirNuevo()
    panel.nuevo = { nombre: '  Marta Díaz ', email: ' marta@x.cl ' }
    assert.equal(panel.puedeCrear, true)
    await panel.crear()

    assert.deepEqual(de('crear')[0].args, [{ nombre: 'Marta Díaz', email: 'marta@x.cl' }])
    assert.equal(panel.creado?.enlace, 'https://ejemplo.supabase.co/auth/v1/verify?token=SECRETO')
    assert.equal(panel.usuarios.at(-1)?.rol_global, 'profesional')
    assert.equal(panel.aviso, 'Usuario creado: Marta Díaz.')

    await panel.copiarEnlace()
    assert.deepEqual(copias, ['https://ejemplo.supabase.co/auth/v1/verify?token=SECRETO'])
    assert.equal(panel.copiado, true)

    // Al cerrar, el enlace desaparece y no vuelve a mostrarse.
    panel.cerrarNuevo()
    assert.equal(panel.creado, null)
    assert.doesNotMatch(JSON.stringify(panel.usuarios), /SECRETO/)
    panel.abrirNuevo()
    assert.equal(panel.creado, null)
  })

  it('valida antes de llamar a la API', async () => {
    const { panel, de } = preparar()
    panel.abrirNuevo()
    panel.nuevo = { nombre: ' ', email: 'marta@x.cl' }
    assert.equal(panel.puedeCrear, false)
    await panel.crear()
    assert.equal(panel.errorNuevo, 'Escribe el nombre del usuario.')
    panel.nuevo = { nombre: 'Marta', email: 'no-es-correo' }
    await panel.crear()
    assert.equal(panel.errorNuevo, 'Escribe un correo válido.')
    assert.equal(de('crear').length, 0)
  })

  it('muestra el error de la API y no agrega a nadie', async () => {
    const { panel } = preparar({ crear: async () => { throw new ErrorApi(409, 'Ya existe un usuario con ese correo.') } })
    await panel.cargar()
    panel.abrirNuevo()
    panel.nuevo = { nombre: 'Juan', email: 'juan@x.cl' }
    await panel.crear()
    assert.equal(panel.errorNuevo, 'Ya existe un usuario con ese correo.')
    assert.equal(panel.creado, null)
    assert.equal(panel.usuarios.length, 4)
  })

  it('modo correo: sin enlace que copiar', async () => {
    const { panel } = preparar({
      crear: async (datos) => ({ usuario: { ...usuario('u-n', datos.nombre, 'profesional'), email: datos.email }, modo: 'correo', enlace: null }),
    })
    panel.abrirNuevo()
    panel.nuevo = { nombre: 'Marta', email: 'marta@x.cl' }
    await panel.crear()
    assert.equal(panel.creado?.enlace, null)
    assert.equal(panel.aviso, 'Se envió una invitación a marta@x.cl.')
  })

  it('si no se puede copiar, lo explica', async () => {
    const { panel } = preparar({}, async () => { throw new Error('sin permiso') })
    panel.abrirNuevo()
    panel.nuevo = { nombre: 'Marta', email: 'marta@x.cl' }
    await panel.crear()
    await panel.copiarEnlace()
    assert.equal(panel.copiado, false)
    assert.equal(panel.errorNuevo, 'No se pudo copiar. Selecciona el enlace y cópialo manualmente.')
  })
})

describe('administración: renovar invitación', () => {
  const conPendiente = () => [...INICIALES(), { ...usuario('u-marta', 'Marta', 'profesional'), estado: 'pendiente' as const }]
  const marta = (panel: { usuarios: UsuarioAdministrado[] }) => panel.usuarios.find((u) => u.id === 'u-marta')!

  it('solo se ofrece a invitaciones pendientes', async () => {
    const { panel } = preparar({ listar: async () => conPendiente() })
    await panel.cargar()
    assert.deepEqual(panel.usuarios.filter((u) => panel.puedeRenovar(u)).map((u) => u.id), ['u-marta'])
    assert.equal(panel.puedeRenovar({ ...marta(panel), estado: null }), false)
    assert.equal(panel.etiquetaRenovar, 'Generar nuevo enlace')
  })

  it('muestra el enlace nuevo en el mismo modal y lo borra al cerrar', async () => {
    const copias: string[] = []
    const { panel, de } = preparar({ listar: async () => conPendiente() }, async (t) => { copias.push(t) })
    await panel.cargar()
    await panel.renovar(marta(panel))

    assert.deepEqual(de('renovar')[0].args, ['u-marta'])
    assert.equal(panel.modalNuevo, true)
    assert.equal(panel.renovada, true)
    assert.equal(panel.creado?.enlace, 'https://ejemplo.supabase.co/auth/v1/verify?token=RENOVADO-1')
    assert.match(panel.aviso, /Nuevo enlace generado para Marta/)

    await panel.copiarEnlace()
    assert.deepEqual(copias, ['https://ejemplo.supabase.co/auth/v1/verify?token=RENOVADO-1'])

    panel.cerrarNuevo()
    assert.equal(panel.creado, null)
    assert.equal(panel.renovada, false)
    // El listado nunca guarda el enlace.
    assert.doesNotMatch(JSON.stringify(panel.usuarios), /RENOVADO/)
    assert.equal(panel.usuarios.length, 5)
    assert.equal(marta(panel).estado, 'pendiente')
  })

  it('una doble pulsación genera un solo enlace', async () => {
    let soltar: () => void = () => {}
    const espera = new Promise<void>((r) => { soltar = r })
    let llamadas = 0
    const { panel } = preparar({
      listar: async () => conPendiente(),
      renovar: async (id) => {
        llamadas += 1
        await espera
        return { usuario: { ...usuario(id, 'Marta', 'profesional'), estado: 'pendiente' }, modo: 'enlace', enlace: 'https://x/RENOVADO' }
      },
    })
    await panel.cargar()
    const primera = panel.renovar(marta(panel))
    assert.equal(panel.renovando, 'u-marta')
    await panel.renovar(marta(panel))
    soltar()
    await primera
    assert.equal(llamadas, 1)
    assert.equal(panel.renovando, '')
    assert.equal(panel.creado?.enlace, 'https://x/RENOVADO')
  })

  it('modo correo: «Reenviar invitación» y sin modal', async () => {
    const { panel } = preparar({
      listar: async () => conPendiente(),
      configuracion: async () => ({ modo_invitacion: 'correo' }),
      renovar: async (id) => ({ usuario: { ...usuario(id, 'Marta', 'profesional'), estado: 'pendiente' }, modo: 'correo', enlace: null }),
    })
    await panel.cargar()
    assert.equal(panel.etiquetaRenovar, 'Reenviar invitación')
    await panel.renovar(marta(panel))
    assert.equal(panel.modalNuevo, false)
    assert.equal(panel.creado, null)
    assert.equal(panel.aviso, 'Se reenvió la invitación a marta@x.cl.')
  })

  it('si la configuración no responde, el listado carga y se usa modo enlace', async () => {
    const { panel } = preparar({
      listar: async () => conPendiente(),
      configuracion: async () => { throw new ErrorApi(503, 'caído') },
    })
    await panel.cargar()
    assert.equal(panel.cargado, true)
    assert.equal(panel.etiquetaRenovar, 'Generar nuevo enlace')
  })

  it('cuenta ya activa: explica el 409 y recarga el listado', async () => {
    let cargas = 0
    const { panel } = preparar({
      listar: async () => { cargas += 1; return conPendiente() },
      renovar: async () => { throw new ErrorApi(409, 'La cuenta ya está activa: no tiene una invitación pendiente.') },
    })
    await panel.cargar()
    await panel.renovar(marta(panel))
    assert.equal(panel.errorRenovar, 'La cuenta ya está activa: no tiene una invitación pendiente.')
    assert.equal(panel.modalNuevo, false)
    assert.equal(panel.creado, null)
    assert.equal(cargas, 2)
  })

  it('sin permisos y límite de envío', async () => {
    const sinPermiso = preparar({ listar: async () => conPendiente(), renovar: async () => { throw new ErrorApi(403, 'x') } })
    await sinPermiso.panel.cargar()
    await sinPermiso.panel.renovar(marta(sinPermiso.panel))
    assert.equal(sinPermiso.panel.errorRenovar, 'Solo un administrador puede renovar invitaciones.')
    assert.equal(mensajeAdministracion(new ErrorApi(429, 'Supabase limitó el envío de invitaciones. Espera unos minutos.'), 'renovar'),
      'Supabase limitó el envío de invitaciones. Espera unos minutos.')
  })

  it('la página usa el mismo modal y texto plano', () => {
    const html = readFileSync(new URL('../administracion.html', import.meta.url), 'utf8')
    assert.match(html, /x-show="panel\.puedeRenovar\(u\)"/)
    assert.match(html, /panel\.etiquetaRenovar/)
    assert.match(html, /panel\.renovada \? 'Nuevo enlace de invitación'/)
    assert.doesNotMatch(html, /x-html/)
    // Un solo campo de enlace: el de creación sirve también para la renovación.
    assert.equal(html.match(/id="enlace-invitacion"/g)?.length, 1)
  })
})

describe('administración: promoción 3/3', () => {
  it('promover crea una solicitud y no cambia el rol', async () => {
    const { panel, de } = preparar()
    await panel.cargar()
    const juan = panel.usuarios[3]
    assert.equal(panel.puedePromover(juan), true)
    assert.equal(panel.puedePromover(panel.usuarios[0]), false)

    panel.pedirPromover(juan)
    await panel.promover()
    assert.deepEqual(de('solicitar')[0].args, ['u-juan'])
    const actualizado = panel.usuarios[3]
    assert.equal(actualizado.rol_global, 'profesional')
    assert.equal(actualizado.solicitud_pendiente?.aprobaciones_recibidas, 0)
    assert.equal(panel.puedePromover(actualizado), false)
    assert.equal(panel.porPromover, null)
    assert.equal(panel.aviso, 'Solicitud creada para Juan: 0 de 3 aprobaciones.')
  })

  it('muestra 0/3, 1/3, 2/3 y 3/3', () => {
    assert.deepEqual([0, 1, 2, 3].map((n) => progreso(solicitud(n))),
      ['0 de 3 aprobaciones', '1 de 3 aprobaciones', '2 de 3 aprobaciones', '3 de 3 aprobaciones'])
    assert.deepEqual(solicitud(2).aprobaciones.map((a) => a.aprobada), [true, true, false])
  })

  it('Aprobar solo para un principal que no votó y con la solicitud pendiente', () => {
    const { panel } = preparar()
    assert.equal(panel.puedeAprobar(solicitud(2, { puedo_aprobar: true })), true)
    assert.equal(panel.puedeAprobar(solicitud(2, { puedo_aprobar: false })), false)
    assert.equal(panel.puedeAprobar(solicitud(3, { puedo_aprobar: true })), false)
    assert.equal(panel.puedeAprobar(null), false)
    panel.aprobando = 's-otra'
    assert.equal(panel.puedeAprobar(solicitud(1)), false)
  })

  it('1/3 y 2/3 actualizan el progreso sin promover', async () => {
    const { panel } = preparar({ aprobar: async () => solicitud(2, { puedo_aprobar: false }) })
    await panel.cargar()
    panel.usuarios[3] = { ...panel.usuarios[3], solicitud_pendiente: solicitud(1), puede_solicitar_administrador: false }
    await panel.aprobar(panel.usuarios[3].solicitud_pendiente!)
    const juan = panel.usuarios[3]
    assert.equal(juan.rol_global, 'profesional')
    assert.equal(juan.solicitud_pendiente?.aprobaciones_recibidas, 2)
    assert.equal(panel.puedeAprobar(juan.solicitud_pendiente), false)
    assert.equal(panel.aviso, 'Aprobación registrada: 2 de 3 aprobaciones.')
  })

  it('3/3 promueve y quita la solicitud', async () => {
    const { panel } = preparar({ aprobar: async () => solicitud(3, { puedo_aprobar: false }) })
    await panel.cargar()
    panel.usuarios[3] = { ...panel.usuarios[3], solicitud_pendiente: solicitud(2), puede_solicitar_administrador: false }
    await panel.aprobar(panel.usuarios[3].solicitud_pendiente!)
    const juan = panel.usuarios[3]
    assert.equal(juan.rol_global, 'administrador')
    assert.equal(juan.solicitud_pendiente, null)
    assert.equal(etiquetaRolGlobal(juan), 'Administrador')
    assert.equal(panel.puedePromover(juan), false)
    assert.equal(panel.aviso, 'Juan ahora es administrador.')
  })

  it('si otro principal ya la completó, muestra el error y recarga', async () => {
    const { panel, de } = preparar({ aprobar: async () => { throw new ErrorApi(409, 'La solicitud ya fue completada.') } })
    await panel.cargar()
    await panel.aprobar(solicitud(2))
    assert.equal(panel.errorAprobar, 'La solicitud ya fue completada.')
    assert.equal(de('listar').length, 2)
    assert.equal(panel.aprobando, '')
  })

  it('un 403 al aprobar lo explica', async () => {
    const { panel } = preparar({ aprobar: async () => { throw new ErrorApi(403, 'x') } })
    await panel.aprobar(solicitud(1))
    assert.equal(panel.errorAprobar, 'Solo los administradores principales aprueban promociones.')
  })
})
