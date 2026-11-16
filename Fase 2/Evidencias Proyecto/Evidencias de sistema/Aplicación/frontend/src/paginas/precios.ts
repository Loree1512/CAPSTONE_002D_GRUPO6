import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir } from '../lib/sesion'
import { confirmar } from '../lib/confirmar'
import { leerPrecioEscrito, pesos, precioUnitario } from '../lib/formato'
import { coberturaBanco, esPrecioReferencial, type Cobertura } from '../lib/banco'
import type {
  CategoriaPartida, EstadoVersion, FilaBanco, PartidaNueva, Unidad, VersionPrecios,
} from '../tipos/api'
import { estadoVersion } from '../tipos/api'

const UNIDADES: Unidad[] = ['m2', 'm3', 'ml', 'kg', 'un', 'gl', 'pto']

interface GrupoCategoria {
  categoria: CategoriaPartida
  filas: FilaBanco[]
}

/** De dónde sale el precio de una partida en la versión mostrada. */
type Origen = 'sin_precio' | 'referencial' | 'oficina'
type FiltroOrigen = '' | Origen

const FILTROS_ORIGEN: { valor: FiltroOrigen; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todas' },
  { valor: 'sin_precio', etiqueta: 'Sin precio' },
  { valor: 'referencial', etiqueta: 'Referencial' },
  { valor: 'oficina', etiqueta: 'De la oficina' },
]

function origenDe(f: FilaBanco): Origen {
  if (f.precio_unitario == null) return 'sin_precio'
  return esPrecioReferencial(f) ? 'referencial' : 'oficina'
}

interface Banco {
  categorias: CategoriaPartida[]
  versiones: VersionPrecios[]
  versionId: string
  filas: FilaBanco[]
  busqueda: string
  categoriaFiltro: string
  origenFiltro: FiltroOrigen
  filtrosOrigen: typeof FILTROS_ORIGEN
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
  precioUnitario: typeof precioUnitario
  leerPrecioEscrito: typeof leerPrecioEscrito

  get version(): VersionPrecios | undefined
  get estado(): EstadoVersion
  get esEditable(): boolean
  etiquetaVersion(v: VersionPrecios): string
  get visibles(): FilaBanco[]
  get grupos(): GrupoCategoria[]
  get cobertura(): Cobertura
  get esReferencial(): boolean
  esReferencia(fila: FilaBanco): boolean
  origen(fila: FilaBanco): Origen
  cuentaOrigen(origen: FiltroOrigen): number
  coberturaCategoria(id: number): Cobertura
  get categoriasConFaltantes(): { categoria: CategoriaPartida; cobertura: Cobertura }[]
  get categoriasCompletas(): number
  verFaltantes(categoriaId: number): void
  fecha(iso: string | null | undefined): string

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
  origenFiltro: '',
  filtrosOrigen: FILTROS_ORIGEN,
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
  precioUnitario,
  leerPrecioEscrito,

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
      if (this.origenFiltro && origenDe(f) !== this.origenFiltro) return false
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

  // Con precio, sin precio y corregidos por la oficina, sobre las partidas vigentes.
  get cobertura() {
    return coberturaBanco(this.filas)
  },

  origen(fila) {
    return origenDe(fila)
  },

  cuentaOrigen(origen) {
    const vigentes = this.filas.filter((f) => f.vigente)
    return origen ? vigentes.filter((f) => origenDe(f) === origen).length : vigentes.length
  },

  coberturaCategoria(id) {
    return coberturaBanco(this.filas.filter((f) => f.categoria_id === id))
  },

  // Solo las categorías con huecos: las completas se resumen en una cifra.
  get categoriasConFaltantes() {
    return this.categorias
      .map((categoria) => ({ categoria, cobertura: this.coberturaCategoria(categoria.id) }))
      .filter((c) => c.cobertura.sinPrecio > 0)
      .sort((a, b) => b.cobertura.sinPrecio - a.cobertura.sinPrecio)
  },

  get categoriasCompletas() {
    return this.categorias.filter((c) => {
      const cobertura = this.coberturaCategoria(c.id)
      return cobertura.total > 0 && cobertura.sinPrecio === 0
    }).length
  },

  // Lleva a la tabla con esa categoría y solo sus partidas sin precio.
  verFaltantes(categoriaId) {
    this.categoriaFiltro = String(categoriaId)
    this.origenFiltro = 'sin_precio'
    document.getElementById('tabla-banco')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  },

  fecha(iso) {
    if (!iso) return '—'
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' })
  },

  get esReferencial() {
    return (this.version?.fuente ?? '').toLowerCase().includes('referencial')
  },

  esReferencia(fila) {
    return esPrecioReferencial(fila)
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
    const ok = await confirmar({
      rotulo: 'Banco de precios', titulo: 'Dar de baja la partida',
      mensaje: `¿Dar de baja «${fila.nombre}»? Las estimaciones ya emitidas la conservan.`, confirmar: 'Dar de baja',
    })
    if (!ok) return
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
    const reutilizar = this.estado === 'historica'
    const mensaje = reutilizar
      ? 'Se vuelve a usar esta versión en las estimaciones nuevas, sin cambiar sus precios. ¿Continuar?'
      : 'Al publicarla, las estimaciones nuevas usarán esta versión y sus precios ya no se podrán editar. ¿Continuar?'
    const ok = await confirmar({
      rotulo: 'Banco de precios', titulo: reutilizar ? 'Volver a usar esta versión' : 'Publicar versión',
      mensaje, confirmar: reutilizar ? 'Usar versión' : 'Publicar',
    })
    if (!ok) return
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
  void prepararNavegacion()
  iniciarBotonTema()
}
