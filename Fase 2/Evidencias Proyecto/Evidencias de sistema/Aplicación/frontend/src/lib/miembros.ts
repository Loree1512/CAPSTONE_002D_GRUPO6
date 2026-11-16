import { ErrorApi } from './errores.ts'
import type { CandidatoMiembro, MiembroProyecto, RolAsignable, RolProyecto } from '../tipos/api.ts'

export const ROLES_ASIGNABLES: { valor: RolAsignable; etiqueta: string }[] = [
  { valor: 'editor', etiqueta: 'Editor' },
  { valor: 'lector', etiqueta: 'Lector' },
]

const ETIQUETAS_ROL: Record<RolProyecto, string> = {
  propietario: 'Propietario',
  editor: 'Editor',
  lector: 'Lector',
}

export function etiquetaRol(rol: unknown): string | undefined {
  return typeof rol === 'string' ? ETIQUETAS_ROL[rol as RolProyecto] : undefined
}

const ORDEN: Record<RolProyecto, number> = { propietario: 0, editor: 1, lector: 2 }

// Mismo orden que el backend: propietario primero, luego por rol y correo.
function ordenar(miembros: MiembroProyecto[]): MiembroProyecto[] {
  return [...miembros].sort((a, b) =>
    (ORDEN[a.rol] ?? 9) - (ORDEN[b.rol] ?? 9) || (a.email ?? '').localeCompare(b.email ?? ''))
}

type Accion = 'cargar' | 'candidatos' | 'agregar' | 'cambiar' | 'quitar'

const GENERICO: Record<Accion, string> = {
  cargar: 'No se pudieron cargar los miembros. Inténtalo nuevamente.',
  candidatos: 'No se pudieron cargar los usuarios disponibles. Inténtalo nuevamente.',
  agregar: 'No fue posible agregar al miembro. Inténtalo nuevamente.',
  cambiar: 'No fue posible cambiar el rol. Inténtalo nuevamente.',
  quitar: 'No fue posible quitar al miembro. Inténtalo nuevamente.',
}

export function mensajeMiembros(e: unknown, accion: Accion): string {
  if (!(e instanceof ErrorApi)) return GENERICO[accion]
  switch (e.estado) {
    case 0: return 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo nuevamente.'
    case 401: return 'Tu sesión expiró. Vuelve a iniciar sesión.'
    case 403: return 'Solo el propietario puede administrar los miembros del proyecto.'
    // La API explica cuál falta (usuario, miembro o proyecto) o por qué no se puede.
    case 404:
    case 409: return e.message || GENERICO[accion]
    case 422: return 'Revisa el usuario y el rol elegido.'
    default: return GENERICO[accion]
  }
}

export interface ApiMiembros {
  listar(): Promise<MiembroProyecto[]>
  candidatos(buscar: string): Promise<CandidatoMiembro[]>
  agregar(email: string, rol: RolAsignable): Promise<MiembroProyecto>
  cambiarRol(usuarioId: string, rol: RolAsignable): Promise<MiembroProyecto>
  quitar(usuarioId: string): Promise<unknown>
}

export interface GestionMiembros {
  miRol: RolProyecto | null
  miembros: MiembroProyecto[]
  cargando: boolean
  cargado: boolean
  error: string
  aviso: string

  modalAgregar: boolean
  busqueda: string
  candidatos: CandidatoMiembro[]
  cargandoCandidatos: boolean
  candidatosCargados: boolean
  errorCandidatos: string
  seleccionado: CandidatoMiembro | null
  rolNuevo: RolAsignable
  agregando: boolean
  errorAgregar: string

  /** usuario_id del cambio de rol en curso. */
  cambiando: string

  porQuitar: MiembroProyecto | null
  quitando: boolean
  errorQuitar: string

  get puedeAdministrar(): boolean
  get puedeAgregar(): boolean
  get nombres(): Record<string, string>
  modificable(m: MiembroProyecto): boolean
  cargar(): Promise<void>
  abrirAgregar(): void
  buscarCandidatos(): Promise<void>
  seleccionar(c: CandidatoMiembro): void
  cancelarAgregar(): void
  agregar(): Promise<void>
  cambiarRol(m: MiembroProyecto, rol: string): Promise<boolean>
  pedirQuitar(m: MiembroProyecto): void
  cancelarQuitar(): void
  quitar(): Promise<void>
}

/** Estado de la sección Miembros. `alCambiar` avisa a la página tras cada cambio guardado. */
export function crearMiembros(api: ApiMiembros, alCambiar: () => void = () => {}): GestionMiembros {
  // Solo cuenta la última búsqueda: una respuesta anterior puede llegar tarde.
  let ultimaBusqueda = 0

  return {
    miRol: null,
    miembros: [],
    cargando: false,
    cargado: false,
    error: '',
    aviso: '',

    modalAgregar: false,
    busqueda: '',
    candidatos: [],
    cargandoCandidatos: false,
    candidatosCargados: false,
    errorCandidatos: '',
    seleccionado: null,
    rolNuevo: 'editor',
    agregando: false,
    errorAgregar: '',

    cambiando: '',

    porQuitar: null,
    quitando: false,
    errorQuitar: '',

    get puedeAdministrar() {
      return this.miRol === 'propietario'
    },

    get puedeAgregar() {
      return this.seleccionado !== null && !this.agregando
    },

    // Para el historial: nombre (o correo) de cada miembro actual.
    get nombres() {
      const nombres: Record<string, string> = {}
      for (const m of this.miembros) {
        const nombre = m.nombre || m.email
        if (nombre) nombres[m.usuario_id] = nombre
      }
      return nombres
    },

    modificable(m) {
      return this.puedeAdministrar && m.rol !== 'propietario'
    },

    async cargar() {
      if (this.cargando) return
      this.cargando = true
      this.error = ''
      try {
        this.miembros = ordenar(await api.listar())
        this.cargado = true
      } catch (e) {
        this.error = mensajeMiembros(e, 'cargar')
      } finally {
        this.cargando = false
      }
    },

    abrirAgregar() {
      if (!this.puedeAdministrar) return
      this.busqueda = ''
      this.seleccionado = null
      this.rolNuevo = 'editor'
      this.errorAgregar = ''
      this.candidatos = []
      this.candidatosCargados = false
      this.modalAgregar = true
      void this.buscarCandidatos()
    },

    async buscarCandidatos() {
      if (!this.puedeAdministrar) return
      const numero = ++ultimaBusqueda
      this.cargandoCandidatos = true
      this.errorCandidatos = ''
      try {
        const encontrados = await api.candidatos(this.busqueda.trim())
        if (numero !== ultimaBusqueda) return
        this.candidatos = encontrados
        this.candidatosCargados = true
      } catch (e) {
        if (numero === ultimaBusqueda) this.errorCandidatos = mensajeMiembros(e, 'candidatos')
      } finally {
        if (numero === ultimaBusqueda) this.cargandoCandidatos = false
      }
    },

    seleccionar(c) {
      if (this.agregando) return
      this.seleccionado = c
      this.errorAgregar = ''
    },

    cancelarAgregar() {
      if (this.agregando) return
      this.modalAgregar = false
    },

    async agregar() {
      const elegido = this.seleccionado
      if (this.agregando || !this.puedeAdministrar || !elegido) return
      this.agregando = true
      this.errorAgregar = ''
      this.aviso = ''
      try {
        // El POST sigue recibiendo el correo: su contrato no cambia.
        const nuevo = await api.agregar(elegido.email, this.rolNuevo)
        this.miembros = ordenar([...this.miembros.filter((m) => m.usuario_id !== nuevo.usuario_id), nuevo])
        this.candidatos = this.candidatos.filter((c) => c.usuario_id !== elegido.usuario_id)
        this.seleccionado = null
        this.modalAgregar = false
        this.aviso = `${nuevo.nombre || nuevo.email || elegido.email} ahora es miembro del proyecto.`
        alCambiar()
      } catch (e) {
        this.errorAgregar = mensajeMiembros(e, 'agregar')
        // Otra persona ya lo agregó o la cuenta no existe: los candidatos quedaron desactualizados.
        if (e instanceof ErrorApi && (e.estado === 404 || e.estado === 409)) {
          this.seleccionado = null
          void this.buscarCandidatos()
        }
      } finally {
        this.agregando = false
      }
    },

    async cambiarRol(m, rol) {
      if (this.cambiando || !this.modificable(m)) return false
      if (rol === m.rol) return true
      if (rol !== 'editor' && rol !== 'lector') return false
      this.cambiando = m.usuario_id
      this.error = ''
      this.aviso = ''
      try {
        const actualizado = await api.cambiarRol(m.usuario_id, rol)
        this.miembros = ordenar(this.miembros.map((x) => (x.usuario_id === m.usuario_id ? { ...x, ...actualizado } : x)))
        this.aviso = `Rol actualizado: ${actualizado.nombre || actualizado.email || 'el miembro'} ahora es ${etiquetaRol(actualizado.rol)?.toLowerCase()}.`
        alCambiar()
        return true
      } catch (e) {
        // La lista quedó desactualizada: alguien más lo cambió o lo quitó.
        if (e instanceof ErrorApi && (e.estado === 404 || e.estado === 409)) await this.cargar()
        this.error = mensajeMiembros(e, 'cambiar')
        return false
      } finally {
        this.cambiando = ''
      }
    },

    pedirQuitar(m) {
      if (!this.modificable(m)) return
      this.errorQuitar = ''
      this.porQuitar = m
    },

    cancelarQuitar() {
      if (this.quitando) return
      this.porQuitar = null
    },

    async quitar() {
      const m = this.porQuitar
      if (this.quitando || !m || !this.modificable(m)) return
      this.quitando = true
      this.errorQuitar = ''
      this.aviso = ''
      this.error = ''
      try {
        await api.quitar(m.usuario_id)
        this.miembros = this.miembros.filter((x) => x.usuario_id !== m.usuario_id)
        this.porQuitar = null
        this.aviso = `${m.nombre || m.email || 'El miembro'} ya no es parte del proyecto.`
        alCambiar()
      } catch (e) {
        // Si ya no era miembro, el resultado es el mismo: se refresca la lista.
        if (e instanceof ErrorApi && e.estado === 404) {
          this.porQuitar = null
          await this.cargar()
          this.error = mensajeMiembros(e, 'quitar')
        } else {
          this.errorQuitar = mensajeMiembros(e, 'quitar')
        }
      } finally {
        this.quitando = false
      }
    },
  }
}
