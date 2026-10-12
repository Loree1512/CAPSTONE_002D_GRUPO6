import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir, usuario } from '../lib/sesion'
import { pesos, numero, superficie, dias } from '../lib/formato'
import { claseEstado, contarEstado, etiquetaEstado, montoCartera } from '../lib/cartera'
import type { Proyecto } from '../tipos/api'

interface Panel {
  proyectos: Proyecto[]
  sinPrecio: number
  versionBanco: string
  bancoReferencial: boolean
  cargando: boolean
  error: string
  nombre: string
  pesos: typeof pesos
  numero: typeof numero
  superficie: typeof superficie
  dias: typeof dias

  get recientes(): Proyecto[]
  get montoCartera(): number
  get superficieCartera(): number
  get porRecalcular(): number
  get sinEstimar(): number

  cargar(): Promise<void>
  abrir(p: Proyecto): void
  etiquetaEstado(p: Proyecto): string
  claseEstado(p: Proyecto): string
  salir(): void
}

Alpine.data('panel', (): Panel => ({
  proyectos: [],
  sinPrecio: 0,
  versionBanco: '—',
  bancoReferencial: false,
  cargando: true,
  error: '',
  nombre: (usuario()?.nombre ?? '').split(' ')[0] || 'equipo',
  pesos,
  numero,
  superficie,
  dias,

  get recientes() {
    return this.proyectos.slice(0, 5)
  },

  get montoCartera() {
    return montoCartera(this.proyectos)
  },

  get superficieCartera() {
    return this.proyectos.reduce((suma, p) => suma + (p.superficie_m2 ?? 0), 0)
  },

  get porRecalcular() {
    return contarEstado(this.proyectos, 'recalcular')
  },

  get sinEstimar() {
    return contarEstado(this.proyectos, 'sin_estimar')
  },

  async cargar() {
    this.cargando = true
    try {
      const [proyectos, versiones] = await Promise.all([api.listarProyectos(), api.listarVersiones()])
      this.proyectos = proyectos

      const vigente = versiones.find((v) => v.vigente)
      this.versionBanco = vigente?.version ?? '—'
      this.bancoReferencial = (vigente?.fuente ?? '').toLowerCase().includes('referencial')

      if (vigente) {
        const filas = await api.listarBanco(vigente.id)
        this.sinPrecio = filas.filter((f) => f.vigente && f.precio_unitario == null).length
      }
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar el panel.'
    } finally {
      this.cargando = false
    }
  },

  abrir(p) {
    window.location.assign(`/estimacion.html?id=${p.id}`)
  },

  etiquetaEstado,
  claseEstado,

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
}
