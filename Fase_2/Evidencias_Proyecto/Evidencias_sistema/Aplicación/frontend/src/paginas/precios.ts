import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir } from '../lib/sesion'
import { pesos } from '../lib/formato'
import type {
  CategoriaPartida, EstadoVersion, FilaBanco, PartidaNueva, Unidad, VersionPrecios,
} from '../tipos/api'
import { estadoVersion } from '../tipos/api'

const UNIDADES: Unidad[] = ['m2', 'm3', 'ml', 'kg', 'un', 'gl', 'pto']

interface GrupoCategoria {
  categoria: CategoriaPartida
  filas: FilaBanco[]
}

interface Banco {
  categorias: CategoriaPartida[]
  versiones: VersionPrecios[]
  versionId: string
  filas: FilaBanco[]
  busqueda: string
  categoriaFiltro: string
  soloSinPrecio: boolean
  cargando: boolean
  error: string
  guardando: string        // id de la partida que se está guardando
  formPartida: boolean
  formVersion: boolean
  nueva: PartidaNueva
  errorNueva: string
  nombreVersion: string
  copiarPrecios: boolean
  formEditar: boolean
  edicion: { id: string; nombre: string; unidad: Unidad; categoria_id: number; unidadOriginal: Unidad; unidadFija: boolean }
  errorEditar: string
  unidades: Unidad[]
  pesos: typeof pesos

  get version(): VersionPrecios | undefined
  get estado(): EstadoVersion
  get esEditable(): boolean
  etiquetaVersion(v: VersionPrecios): string
  get visibles(): FilaBanco[]
  get grupos(): GrupoCategoria[]
  get conPrecio(): number
  get sinPrecio(): number
  get deOficina(): number
  get esReferencial(): boolean
  esReferencia(fila: FilaBanco): boolean

  cargar(): Promise<void>
  cambiarVersion(): Promise<void>
  nombreCategoria(id: number): string
  editarPrecio(fila: FilaBanco, valor: string): Promise<void>
  abrirPartida(): void
  crearPartida(): Promise<void>
  abrirEditar(fila: FilaBanco): void
  guardarEdicion(): Promise<void>
  darDeBaja(fila: FilaBanco): Promise<void>
  abrirVersion(): void
  crearVersion(): Promise<void>
  publicar(): Promise<void>
  salir(): void
}

Alpine.data('banco', (): Banco => ({
  categorias: [],
  versiones: [],
  versionId: '',
  filas: [],
  busqueda: '',
  categoriaFiltro: '',
  soloSinPrecio: false,
  cargando: true,
  error: '',
  guardando: '',
  formPartida: false,
  formVersion: false,
  nueva: { categoria_id: 1, nombre: '', unidad: 'm2' },
  errorNueva: '',
  nombreVersion: '',
  copiarPrecios: true,
  formEditar: false,
  edicion: { id: '', nombre: '', unidad: 'm2', categoria_id: 1, unidadOriginal: 'm2', unidadFija: false },
  errorEditar: '',
  unidades: UNIDADES,
  pesos,

  get version() {
    return this.versiones.find((v) => v.id === this.versionId)
  },

  get estado() {
    return this.version ? estadoVersion(this.version) : 'borrador'
  },

  // Solo un borrador se edita; una versión publicada queda fija para siempre.
  get esEditable() {
    return !!this.version && this.estado === 'borrador'
  },

  etiquetaVersion(v) {
    const estado = estadoVersion(v)
    return `${v.version} · ${estado === 'vigente' ? 'vigente' : estado === 'historica' ? 'histórica' : 'borrador'}`
  },

  get visibles() {
    const texto = this.busqueda.trim().toLowerCase()
    return this.filas.filter((f) => {
      if (!f.vigente) return false
      if (this.categoriaFiltro && String(f.categoria_id) !== this.categoriaFiltro) return false
      if (this.soloSinPrecio && f.precio_unitario != null) return false
      if (!texto) return true
      return f.nombre.toLowerCase().includes(texto) || f.codigo.includes(texto)
    })
  },

  get grupos() {
    return this.categorias
      .map((categoria) => ({
        categoria,
        filas: this.visibles.filter((f) => f.categoria_id === categoria.id),
      }))
      .filter((g) => g.filas.length > 0)
  },

  get conPrecio() {
    return this.filas.filter((f) => f.vigente && f.precio_unitario != null).length
  },

  get sinPrecio() {
    return this.filas.filter((f) => f.vigente && f.precio_unitario == null).length
  },

  /** Precios que la oficina ya corrigió sobre la referencia de mercado. */
  get deOficina() {
    return this.filas.filter((f) => f.vigente && f.precio_unitario != null && !this.esReferencia(f)).length
  },

  get esReferencial() {
    return (this.version?.fuente ?? '').toLowerCase().includes('referencial')
  },

  esReferencia(fila) {
    return (fila.fuente ?? '').toLowerCase().includes('referencial')
  },

  async cargar() {
    this.cargando = true
    this.error = ''
    try {
      const [categorias, versiones] = await Promise.all([
        api.listarCategorias(),
        api.listarVersiones(),
      ])
      this.categorias = categorias
      this.versiones = versiones
      this.versionId = this.versionId || versiones.find((v) => v.vigente)?.id || versiones[0]?.id || ''
      this.filas = await api.listarBanco(this.versionId)
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar el banco de precios.'
    } finally {
      this.cargando = false
    }
  },

  async cambiarVersion() {
    this.cargando = true
    try {
      this.filas = await api.listarBanco(this.versionId)
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar esa versión.'
    } finally {
      this.cargando = false
    }
  },

  nombreCategoria(id) {
    return this.categorias.find((c) => c.id === id)?.nombre ?? ''
  },

  async editarPrecio(fila, valor) {
    // Las publicadas son inmutables; el backend también lo rechaza.
    if (!this.esEditable) return
    const numero = valor.trim() === '' ? null : Number(valor)
    if (numero != null && (Number.isNaN(numero) || numero < 0)) return

    const anterior = fila.precio_unitario
    fila.precio_unitario = numero
    this.guardando = fila.id
    try {
      // El rendimiento ya no entra al cálculo, pero se conserva tal cual.
      await api.guardarPrecio(this.versionId, fila.id, {
        precio_unitario: fila.precio_unitario,
        rendimiento_mo: fila.rendimiento_mo,
      })
    } catch (e) {
      fila.precio_unitario = anterior
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo guardar el valor.'
    } finally {
      this.guardando = ''
    }
  },

  abrirPartida() {
    this.nueva = { categoria_id: this.categorias[0]?.id ?? 1, nombre: '', unidad: 'm2' }
    this.errorNueva = ''
    this.formPartida = true
  },

  async crearPartida() {
    if (!this.nueva.nombre.trim()) {
      this.errorNueva = 'Escribe el nombre de la partida.'
      return
    }
    try {
      await api.crearPartida({ ...this.nueva, nombre: this.nueva.nombre.trim() })
      this.formPartida = false
      this.filas = await api.listarBanco(this.versionId)
    } catch (e) {
      this.errorNueva = e instanceof ErrorApi ? e.message : 'No se pudo crear la partida.'
    }
  },

  abrirEditar(fila) {
    this.edicion = {
      id: fila.id, nombre: fila.nombre, unidad: fila.unidad,
      categoria_id: fila.categoria_id, unidadOriginal: fila.unidad,
      // Sus precios están en esa unidad: no se ofrece cambiarla.
      unidadFija: !!fila.tiene_precios,
    }
    this.errorEditar = ''
    this.formEditar = true
  },

  async guardarEdicion() {
    const { id, nombre, unidad, categoria_id, unidadOriginal } = this.edicion
    if (!nombre.trim()) {
      this.errorEditar = 'Escribe el nombre de la partida.'
      return
    }
    if (unidad !== unidadOriginal && this.edicion.unidadFija) {
      this.errorEditar = 'La partida ya tiene precios: para usar otra unidad, dala de baja y crea una nueva.'
      return
    }
    try {
      await api.editarPartida(id, { nombre: nombre.trim(), unidad, categoria_id })
      this.formEditar = false
      this.filas = await api.listarBanco(this.versionId)
    } catch (e) {
      this.errorEditar = e instanceof ErrorApi ? e.message : 'No se pudo guardar la partida.'
    }
  },

  async darDeBaja(fila) {
    if (!window.confirm(`Dar de baja «${fila.nombre}»? Las estimaciones ya emitidas la conservan.`)) return
    try {
      await api.darDeBajaPartida(fila.id)
      this.filas = await api.listarBanco(this.versionId)
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo dar de baja la partida.'
    }
  },

  abrirVersion() {
    const hoy = new Date()
    this.nombreVersion = `${hoy.getFullYear()}-T${Math.floor(hoy.getMonth() / 3) + 1}`
    this.copiarPrecios = true
    this.formVersion = true
  },

  async crearVersion() {
    if (!this.nombreVersion.trim()) return
    try {
      const creada = await api.crearVersion(
        this.nombreVersion.trim(),
        this.copiarPrecios ? this.versionId : undefined,
      )
      this.formVersion = false
      this.versiones = await api.listarVersiones()
      this.versionId = creada.id
      await this.cambiarVersion()
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo crear la versión.'
    }
  },

  async publicar() {
    const mensaje = this.estado === 'historica'
      ? 'Se vuelve a usar esta versión en las estimaciones nuevas, sin cambiar sus precios. ¿Continuar?'
      : 'Al publicarla, las estimaciones nuevas usarán esta versión y sus precios ya no se podrán editar. ¿Continuar?'
    if (!window.confirm(mensaje)) return
    try {
      await api.publicarVersion(this.versionId)
      this.versiones = await api.listarVersiones()
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo publicar la versión.'
    }
  },

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
}
