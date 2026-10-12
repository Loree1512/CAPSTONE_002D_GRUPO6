import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir } from '../lib/sesion'
import { claseEstado, contarEstado, etiquetaEstado, montoCartera } from '../lib/cartera'
import { pesos, dias, superficie } from '../lib/formato'
import type { Proyecto } from '../tipos/api'

interface Listado {
  proyectos: Proyecto[]
  versionBanco: string
  cargando: boolean
  error: string
  get conEstimacion(): number
  get montoTotal(): string
  get superficieTotal(): string
  cargar(): Promise<void>
  abrir(p: Proyecto): void
  salir(): void
  etiquetaEstado(p: Proyecto): string
  claseEstado(p: Proyecto): string
  pesos: typeof pesos
  dias: typeof dias
  superficie: typeof superficie
}

Alpine.data('listado', (): Listado => ({
  proyectos: [],
  versionBanco: '—',
  cargando: true,
  error: '',
  pesos,
  dias,
  superficie,

  async cargar() {
    this.cargando = true
    this.error = ''
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

  get montoTotal() {
    const total = montoCartera(this.proyectos)
    if (total === 0) return '—'
    // Las cifras grandes se abrevian a millones, como el resto del panel.
    return total >= 1_000_000
      ? `$${new Intl.NumberFormat('es-CL').format(Math.round(total / 1_000_000))} M`
      : pesos(total)
  },

  get superficieTotal() {
    const m2 = this.proyectos.reduce((suma, p) => suma + (p.superficie_m2 ?? 0), 0)
    return `${new Intl.NumberFormat('es-CL').format(m2)} m²`
  },

  abrir(p) {
    window.location.assign(`/estimacion.html?id=${p.id}`)
  },

  etiquetaEstado,
  claseEstado,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
}
