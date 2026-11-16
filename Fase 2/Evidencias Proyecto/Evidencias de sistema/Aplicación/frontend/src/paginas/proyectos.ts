import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir } from '../lib/sesion'
import {
  accionSugerida, claseEstado, contarEstado, estadoDe, etiquetaEstado, montoCartera, ordenarPorPrioridad,
  requiereAtencion,
} from '../lib/cartera'
import { pesos, dias, superficie, montoCompacto } from '../lib/formato'
import { plazoDelProyecto } from '../lib/plazo'
import { MENSAJE_PROYECTO_ELIMINADO } from '../lib/errores'
import type { EstadoProyecto, Proyecto } from '../tipos/api'

type Filtro = 'todos' | 'atencion' | EstadoProyecto
type Orden = 'prioridad' | 'recientes' | 'monto' | 'nombre'

const FILTROS: { valor: Filtro; etiqueta: string }[] = [
  { valor: 'todos', etiqueta: 'Todos' },
  { valor: 'atencion', etiqueta: 'Requieren atención' },
  { valor: 'vigente', etiqueta: 'Vigentes' },
  { valor: 'recalcular', etiqueta: 'Por recalcular' },
  { valor: 'sin_estimar', etiqueta: 'Sin estimar' },
  { valor: 'ejecutada', etiqueta: 'Ejecutadas' },
]

interface Listado {
  proyectos: Proyecto[]
  versionBanco: string
  cargando: boolean
  error: string
  mensaje: string
  busqueda: string
  filtro: Filtro
  orden: Orden
  filtros: typeof FILTROS
  get conEstimacion(): number
  get enAtencion(): number
  get montoTotal(): string
  get superficieTotal(): string
  get visibles(): Proyecto[]
  cuenta(filtro: Filtro): number
  limpiar(): void
  cargar(): Promise<void>
  abrir(p: Proyecto): void
  salir(): void
  etiquetaEstado(p: Proyecto): string
  claseEstado(p: Proyecto): string
  accionSugerida(p: Proyecto): string
  requiereAtencion(p: Proyecto): boolean
  pesos: typeof pesos
  dias: typeof dias
  superficie: typeof superficie
  plazoDelProyecto: typeof plazoDelProyecto
  get hayReferenciales(): boolean
}

function cumple(p: Proyecto, filtro: Filtro): boolean {
  if (filtro === 'todos') return true
  if (filtro === 'atencion') return requiereAtencion(p)
  return estadoDe(p) === filtro
}

const fecha = (p: Proyecto) => Date.parse(p.actualizado_en ?? p.creado_en ?? '') || 0

Alpine.data('listado', (): Listado => ({
  proyectos: [],
  versionBanco: '—',
  cargando: true,
  error: '',
  mensaje: '',
  busqueda: '',
  filtro: 'todos',
  orden: 'prioridad',
  filtros: FILTROS,
  pesos,
  dias,
  superficie,
  plazoDelProyecto,

  get hayReferenciales() {
    return this.visibles.some((p) => plazoDelProyecto(p).nota !== '')
  },

  async cargar() {
    this.cargando = true
    this.error = ''
    const parametros = new URLSearchParams(window.location.search)
    // Viene de eliminar un proyecto desde su ficha.
    if (parametros.get('eliminado') === '1') {
      this.mensaje = MENSAJE_PROYECTO_ELIMINADO
      window.history.replaceState(null, '', window.location.pathname)
    }
    // El panel enlaza aquí con el filtro de atención ya puesto.
    const estado = parametros.get('estado')
    if (estado && FILTROS.some((f) => f.valor === estado)) this.filtro = estado as Filtro
    try {
      const [proyectos, versiones] = await Promise.all([api.listarProyectos(), api.listarVersiones()])
      this.proyectos = proyectos
      this.versionBanco = versiones.find((v) => v.vigente)?.version ?? '—'
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudieron cargar los proyectos.'
    } finally {
      this.cargando = false
    }
  },

  salir,

  // Mismas reglas que el panel (lib/cartera.ts).
  get conEstimacion() {
    return contarEstado(this.proyectos, 'vigente')
  },

  get enAtencion() {
    return this.proyectos.filter(requiereAtencion).length
  },

  get montoTotal() {
    const total = montoCartera(this.proyectos)
    return total === 0 ? '—' : montoCompacto(total)
  },

  get superficieTotal() {
    const m2 = this.proyectos.reduce((suma, p) => suma + (p.superficie_m2 ?? 0), 0)
    return `${new Intl.NumberFormat('es-CL').format(m2)} m²`
  },

  get visibles() {
    const texto = this.busqueda.trim().toLowerCase()
    const filtrados = this.proyectos.filter((p) => cumple(p, this.filtro) && (!texto
      || [p.nombre, p.comuna, p.tipo_obra].some((v) => (v ?? '').toLowerCase().includes(texto))))
    if (this.orden === 'prioridad') return ordenarPorPrioridad(filtrados)
    const copia = [...filtrados]
    if (this.orden === 'recientes') return copia.sort((a, b) => fecha(b) - fecha(a))
    if (this.orden === 'monto') return copia.sort((a, b) => (b.costo_total ?? -1) - (a.costo_total ?? -1))
    return copia.sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'))
  },

  cuenta(filtro) {
    return this.proyectos.filter((p) => cumple(p, filtro)).length
  },

  limpiar() {
    this.busqueda = ''
    this.filtro = 'todos'
  },

  abrir(p) {
    window.location.assign(`/estimacion.html?id=${p.id}`)
  },

  etiquetaEstado,
  claseEstado,
  accionSugerida,
  requiereAtencion,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
  void prepararNavegacion()
  iniciarBotonTema()
}
