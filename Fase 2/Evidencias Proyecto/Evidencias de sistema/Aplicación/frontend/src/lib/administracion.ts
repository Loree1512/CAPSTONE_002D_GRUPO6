import { ErrorApi } from './errores.ts'
import type {
  ConfiguracionAdministracion, EstadoCuenta, ModoInvitacion, SolicitudAdministrador, UsuarioAdministrado,
  UsuarioCreado, UsuarioNuevo,
} from '../tipos/administracion.ts'

/* Panel global de usuarios. La API autoriza cada operación; aquí solo se decide qué
   controles mostrar y cómo explicar los errores. */

export interface ApiAdministracion {
  listar(): Promise<UsuarioAdministrado[]>
  crear(datos: UsuarioNuevo): Promise<UsuarioCreado>
  solicitar(usuarioId: string): Promise<SolicitudAdministrador>
  aprobar(solicitudId: string): Promise<SolicitudAdministrador>
  renovar(usuarioId: string): Promise<UsuarioCreado>
  /** Solo decide el texto de la acción; si falla, se asume modo enlace. */
  configuracion?(): Promise<ConfiguracionAdministracion>
}

type Accion = 'cargar' | 'crear' | 'solicitar' | 'aprobar' | 'renovar' | 'copiar'

const GENERICO: Record<Accion, string> = {
  cargar: 'No se pudieron cargar los usuarios. Inténtalo nuevamente.',
  crear: 'No fue posible crear el usuario. Inténtalo nuevamente.',
  solicitar: 'No fue posible crear la solicitud. Inténtalo nuevamente.',
  aprobar: 'No fue posible registrar la aprobación. Inténtalo nuevamente.',
  renovar: 'No fue posible renovar la invitación. Inténtalo nuevamente.',
  copiar: 'No se pudo copiar. Selecciona el enlace y cópialo manualmente.',
}

const SIN_PERMISO: Record<Accion, string> = {
  cargar: 'Esta sección es solo para administradores.',
  crear: 'Solo un administrador puede crear usuarios.',
  solicitar: 'Solo un administrador puede solicitar una promoción.',
  aprobar: 'Solo los administradores principales aprueban promociones.',
  renovar: 'Solo un administrador puede renovar invitaciones.',
  copiar: GENERICO.copiar,
}

export function mensajeAdministracion(e: unknown, accion: Accion): string {
  if (!(e instanceof ErrorApi)) return GENERICO[accion]
  switch (e.estado) {
    case 0: return 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo nuevamente.'
    case 401: return 'Tu sesión expiró. Vuelve a iniciar sesión.'
    case 403: return SIN_PERMISO[accion]
    // La API explica qué pasó: correo existente, solicitud duplicada o completada…
    case 404:
    case 409: return e.message || GENERICO[accion]
    case 422: return accion === 'crear' ? e.message || 'Revisa el nombre y el correo.' : GENERICO[accion]
    case 429:
    case 503: return e.message || GENERICO[accion]
    default: return GENERICO[accion]
  }
}

export function etiquetaRolGlobal(u: Pick<UsuarioAdministrado, 'rol_global' | 'es_administrador_principal'>): string {
  if (u.es_administrador_principal) return 'Admin. principal'
  return u.rol_global === 'administrador' ? 'Administrador' : 'Profesional'
}

export function etiquetaEstado(estado: EstadoCuenta | null | undefined): string {
  if (estado === 'activo') return 'Activo'
  if (estado === 'pendiente') return 'Invitación pendiente'
  return '—'
}

export function progreso(s: Pick<SolicitudAdministrador, 'aprobaciones_recibidas' | 'aprobaciones_requeridas'>): string {
  return `${s.aprobaciones_recibidas} de ${s.aprobaciones_requeridas} aprobaciones`
}

export const nombreVisible = (u: { nombre: string | null; email: string | null }): string =>
  u.nombre || u.email || 'Usuario sin correo'

export function etiquetaRenovar(modo: ModoInvitacion): string {
  return modo === 'correo' ? 'Reenviar invitación' : 'Generar nuevo enlace'
}

const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export interface PanelAdministracion {
  usuarios: UsuarioAdministrado[]
  cargando: boolean
  cargado: boolean
  error: string
  aviso: string
  /** La API respondió 403: quien entra no es administrador. */
  sinPermiso: boolean

  modalNuevo: boolean
  nuevo: UsuarioNuevo
  creando: boolean
  errorNuevo: string
  /** Resultado de crear o renovar; el enlace vive solo aquí y se borra al cerrar. */
  creado: UsuarioCreado | null
  /** El modal muestra un enlace renovado, no un usuario recién creado. */
  renovada: boolean
  copiado: boolean

  modoInvitacion: ModoInvitacion
  /** id del usuario cuya invitación se está renovando. */
  renovando: string
  errorRenovar: string

  porPromover: UsuarioAdministrado | null
  solicitando: boolean
  errorPromover: string

  /** id de la solicitud que se está aprobando. */
  aprobando: string
  errorAprobar: string

  get puedeCrear(): boolean
  puedeAprobar(s: SolicitudAdministrador | null | undefined): boolean
  puedePromover(u: UsuarioAdministrado): boolean
  puedeRenovar(u: UsuarioAdministrado): boolean
  get etiquetaRenovar(): string
  cargar(): Promise<void>
  renovar(u: UsuarioAdministrado): Promise<void>
  abrirNuevo(): void
  cerrarNuevo(): void
  crear(): Promise<void>
  copiarEnlace(): Promise<void>
  pedirPromover(u: UsuarioAdministrado): void
  cancelarPromover(): void
  promover(): Promise<void>
  aprobar(s: SolicitudAdministrador): Promise<void>
}

export function crearPanelAdministracion(
  api: ApiAdministracion,
  copiar: (texto: string) => Promise<void> = (texto) => navigator.clipboard.writeText(texto),
): PanelAdministracion {
  return {
    usuarios: [],
    cargando: false,
    cargado: false,
    error: '',
    aviso: '',
    sinPermiso: false,

    modalNuevo: false,
    nuevo: { nombre: '', email: '' },
    creando: false,
    errorNuevo: '',
    creado: null,
    renovada: false,
    copiado: false,

    modoInvitacion: 'enlace',
    renovando: '',
    errorRenovar: '',

    porPromover: null,
    solicitando: false,
    errorPromover: '',

    aprobando: '',
    errorAprobar: '',

    get puedeCrear() {
      return !this.creando && this.nuevo.nombre.trim() !== '' && this.nuevo.email.trim() !== ''
    },

    puedeAprobar(s) {
      return !!s && s.estado === 'pendiente' && s.puedo_aprobar && this.aprobando === ''
    },

    puedePromover(u) {
      return u.puede_solicitar_administrador && !u.solicitud_pendiente
    },

    // Solo cuentas que no completaron la invitación; el backend vuelve a comprobarlo.
    puedeRenovar(u) {
      return u.estado === 'pendiente'
    },

    get etiquetaRenovar() {
      return etiquetaRenovar(this.modoInvitacion)
    },

    async cargar() {
      if (this.cargando) return
      this.cargando = true
      this.error = ''
      try {
        const [usuarios, config] = await Promise.all([
          api.listar(),
          api.configuracion?.().catch(() => null),
        ])
        this.usuarios = usuarios
        if (config) this.modoInvitacion = config.modo_invitacion
        this.cargado = true
      } catch (e) {
        this.error = mensajeAdministracion(e, 'cargar')
        this.sinPermiso = e instanceof ErrorApi && e.estado === 403
      } finally {
        this.cargando = false
      }
    },

    abrirNuevo() {
      this.modalNuevo = true
      this.nuevo = { nombre: '', email: '' }
      this.errorNuevo = ''
      this.creado = null
      this.renovada = false
      this.copiado = false
    },

    cerrarNuevo() {
      if (this.creando) return
      this.modalNuevo = false
      // El enlace no queda en memoria ni se vuelve a mostrar.
      this.creado = null
      this.renovada = false
      this.copiado = false
    },

    async renovar(u) {
      if (!this.puedeRenovar(u) || this.renovando !== '') return
      this.renovando = u.id
      this.errorRenovar = ''
      try {
        const resultado = await api.renovar(u.id)
        this.modoInvitacion = resultado.modo
        this.usuarios = this.usuarios.map((x) => x.id === u.id ? { ...x, estado: resultado.usuario.estado } : x)
        if (resultado.enlace) {
          // Mismo modal que al crear: Copiar enlace y se borra al cerrar.
          this.creado = resultado
          this.renovada = true
          this.copiado = false
          this.errorNuevo = ''
          this.modalNuevo = true
          this.aviso = `Nuevo enlace generado para ${nombreVisible(u)}. El anterior ya no sirve.`
        } else {
          this.aviso = `Se reenvió la invitación a ${u.email ?? nombreVisible(u)}.`
        }
      } catch (e) {
        this.errorRenovar = mensajeAdministracion(e, 'renovar')
        // La persona ya completó su invitación: se muestra el estado vigente.
        if (e instanceof ErrorApi && (e.estado === 409 || e.estado === 404)) await this.cargar()
      } finally {
        this.renovando = ''
      }
    },

    async crear() {
      const nombre = this.nuevo.nombre.trim()
      const email = this.nuevo.email.trim()
      this.errorNuevo = ''
      if (!nombre) { this.errorNuevo = 'Escribe el nombre del usuario.'; return }
      if (!CORREO.test(email)) { this.errorNuevo = 'Escribe un correo válido.'; return }

      this.creando = true
      try {
        const creado = await api.crear({ nombre, email })
        this.creado = creado
        this.usuarios = [...this.usuarios, creado.usuario]
        this.aviso = creado.modo === 'correo'
          ? `Se envió una invitación a ${creado.usuario.email}.`
          : `Usuario creado: ${nombreVisible(creado.usuario)}.`
      } catch (e) {
        this.errorNuevo = mensajeAdministracion(e, 'crear')
      } finally {
        this.creando = false
      }
    },

    async copiarEnlace() {
      if (!this.creado?.enlace) return
      try {
        await copiar(this.creado.enlace)
        this.copiado = true
      } catch (e) {
        this.errorNuevo = mensajeAdministracion(e, 'copiar')
      }
    },

    pedirPromover(u) {
      this.porPromover = u
      this.errorPromover = ''
    },

    cancelarPromover() {
      if (this.solicitando) return
      this.porPromover = null
    },

    async promover() {
      const objetivo = this.porPromover
      if (!objetivo) return
      this.solicitando = true
      this.errorPromover = ''
      try {
        const solicitud = await api.solicitar(objetivo.id)
        this.usuarios = this.usuarios.map((u) => u.id === objetivo.id
          ? { ...u, solicitud_pendiente: solicitud, puede_solicitar_administrador: false }
          : u)
        this.aviso = `Solicitud creada para ${nombreVisible(objetivo)}: ${progreso(solicitud)}.`
        this.porPromover = null
      } catch (e) {
        this.errorPromover = mensajeAdministracion(e, 'solicitar')
      } finally {
        this.solicitando = false
      }
    },

    async aprobar(s) {
      if (!this.puedeAprobar(s)) return
      this.aprobando = s.id
      this.errorAprobar = ''
      try {
        const actual = await api.aprobar(s.id)
        const promovido = actual.estado === 'aprobada'
        this.usuarios = this.usuarios.map((u) => {
          if (u.id !== actual.usuario_id) return u
          return promovido
            ? { ...u, rol_global: 'administrador', solicitud_pendiente: null, puede_solicitar_administrador: false }
            : { ...u, solicitud_pendiente: actual }
        })
        const nombre = nombreVisible({ nombre: actual.usuario_nombre, email: actual.usuario_email })
        this.aviso = promovido
          ? `${nombre} ahora es administrador.`
          : `Aprobación registrada: ${progreso(actual)}.`
      } catch (e) {
        this.errorAprobar = mensajeAdministracion(e, 'aprobar')
        // Otro principal pudo completarla mientras tanto: se muestra lo vigente.
        if (e instanceof ErrorApi && (e.estado === 409 || e.estado === 404)) await this.cargar()
      } finally {
        this.aprobando = ''
      }
    },
  }
}
