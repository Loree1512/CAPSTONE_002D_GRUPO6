import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir, usuario } from '../lib/sesion'
import { bienvenida, type Bienvenida } from '../lib/bienvenida'
import { pesos, numero, superficie, dias, montoCompacto } from '../lib/formato'
import {
  accionSugerida, claseEstado, contarEstado, distribucionEstados, etiquetaEstado, montoCartera,
  montoPorTipo, ordenarPorPrioridad, requiereAtencion,
} from '../lib/cartera'
import { coberturaBanco, type Cobertura } from '../lib/banco'
import { presentarUfVigente, type PresentacionUf } from '../lib/uf'
import type { MontoTipo, TramoEstado } from '../lib/cartera'
import type { Proyecto } from '../tipos/api'

interface Atencion {
  clave: string
  nivel: 'alta' | 'media' | 'info'
  cifra: string
  titulo: string
  detalle: string
  enlace: string
  accion: string
}

interface Panel {
  proyectos: Proyecto[]
  cobertura: Cobertura
  versionBanco: string
  bancoReferencial: boolean
  uf: PresentacionUf
  cargando: boolean
  error: string
  bienvenida: Bienvenida
  pesos: typeof pesos
  numero: typeof numero
  superficie: typeof superficie
  dias: typeof dias
  montoCompacto: typeof montoCompacto

  get prioridades(): Proyecto[]
  get montoCartera(): number
  get vigentes(): number
  get superficieCartera(): number
  get porRecalcular(): number
  get sinEstimar(): number
  get enAtencion(): number
  get estados(): TramoEstado[]
  get montosPorTipo(): MontoTipo[]
  get atencion(): Atencion[]

  cargar(): Promise<void>
  abrir(p: Proyecto): void
  etiquetaEstado(p: Proyecto): string
  claseEstado(p: Proyecto): string
  accionSugerida(p: Proyecto): string
  requiereAtencion(p: Proyecto): boolean
  salir(): void
}

const SIN_BANCO: Cobertura = { total: 0, conPrecio: 0, oficina: 0, referencial: 0, sinPrecio: 0, porcentaje: 0 }

Alpine.data('panel', (): Panel => ({
  proyectos: [],
  cobertura: SIN_BANCO,
  versionBanco: '—',
  bancoReferencial: false,
  uf: presentarUfVigente(null),
  cargando: true,
  error: '',
  // Con lo guardado al abrir; prepararNavegacion la actualiza con lo que responde la API.
  bienvenida: bienvenida(usuario()),
  pesos,
  numero,
  superficie,
  dias,
  montoCompacto,

  // Lo que pide acción primero; la tabla muestra hasta seis.
  get prioridades() {
    return ordenarPorPrioridad(this.proyectos).slice(0, 6)
  },

  get montoCartera() {
    return montoCartera(this.proyectos)
  },

  get vigentes() {
    return contarEstado(this.proyectos, 'vigente')
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

  get enAtencion() {
    return this.porRecalcular + this.sinEstimar
  },

  get estados() {
    return distribucionEstados(this.proyectos)
  },

  get montosPorTipo() {
    return montoPorTipo(this.proyectos).slice(0, 5)
  },

  get atencion() {
    const lista: Atencion[] = []
    if (this.porRecalcular > 0) {
      lista.push({
        clave: 'recalcular', nivel: 'alta', cifra: String(this.porRecalcular),
        titulo: this.porRecalcular === 1 ? 'Proyecto por recalcular' : 'Proyectos por recalcular',
        detalle: 'Cambiaron sus datos o el banco vigente. No suman al monto de la cartera.',
        enlace: '/proyectos.html?estado=atencion', accion: 'Revisar',
      })
    }
    if (this.sinEstimar > 0) {
      lista.push({
        clave: 'sin_estimar', nivel: 'media', cifra: String(this.sinEstimar),
        titulo: this.sinEstimar === 1 ? 'Proyecto sin estimación' : 'Proyectos sin estimación',
        detalle: 'Registrados, pero todavía sin costo ni plazo calculados.',
        enlace: '/proyectos.html?estado=atencion', accion: 'Estimar',
      })
    }
    if (this.cobertura.sinPrecio > 0) {
      lista.push({
        clave: 'sin_precio', nivel: 'alta', cifra: String(this.cobertura.sinPrecio),
        titulo: 'Partidas sin precio en el banco',
        detalle: 'En los proyectos quedan sin costo salvo que se indique un precio particular.',
        enlace: '/precios.html', accion: 'Completar',
      })
    }
    if (this.bancoReferencial && this.cobertura.referencial > 0) {
      lista.push({
        clave: 'referencial', nivel: 'info', cifra: `${this.cobertura.referencial}`,
        titulo: 'Precios referenciales de mercado',
        detalle: 'Reemplazarlos por valores de la oficina vuelve la estimación una cifra defendible.',
        enlace: '/precios.html', accion: 'Ir al banco',
      })
    }
    return lista
  },

  async cargar() {
    this.cargando = true
    void prepararNavegacion().then((actual) => { if (actual) this.bienvenida = bienvenida(actual) })
    try {
      // La UF es un dato accesorio: si falla, el Panel sigue y la muestra como no disponible.
      const [proyectos, versiones, uf] = await Promise.all([
        api.listarProyectos(), api.listarVersiones(), api.obtenerUfVigente().catch(() => null),
      ])
      this.proyectos = proyectos
      this.uf = presentarUfVigente(uf)

      const vigente = versiones.find((v) => v.vigente)
      this.versionBanco = vigente?.version ?? '—'
      this.bancoReferencial = (vigente?.fuente ?? '').toLowerCase().includes('referencial')

      if (vigente) this.cobertura = coberturaBanco(await api.listarBanco(vigente.id))
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
  accionSugerida,
  requiereAtencion,

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
  iniciarBotonTema()
}
