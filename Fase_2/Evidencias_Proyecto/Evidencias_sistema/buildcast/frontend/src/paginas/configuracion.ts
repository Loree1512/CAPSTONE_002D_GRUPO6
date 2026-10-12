import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir } from '../lib/sesion'
import { pesos } from '../lib/formato'
import { CONFIGURACION_BASE } from '../lib/configuracion'
import type { Configuracion } from '../lib/configuracion'
import { ESTANDARES } from '../lib/catalogos'
import { LIMITE_GASTOS_GENERALES, LIMITE_UTILIDAD } from '../tipos/estimacion'

interface PantallaConfig {
  config: Configuracion
  comunas: string[]
  materiales: string[]
  estandares: typeof ESTANDARES
  limiteGg: number
  limiteUtilidad: number
  cargando: boolean
  guardando: boolean
  guardado: boolean
  listo: boolean
  error: string
  pesos: typeof pesos

  iniciar(): Promise<void>
  mostrar(config: Configuracion): void
  validar(): string
  guardar(): Promise<void>
  restaurar(): Promise<void>
  salir(): void
}

Alpine.data('configuracion', (): PantallaConfig => ({
  // Solo para que las plantillas tengan forma mientras carga; no se muestra.
  config: structuredClone(CONFIGURACION_BASE),
  comunas: [],
  materiales: [],
  estandares: ESTANDARES,
  limiteGg: LIMITE_GASTOS_GENERALES,
  limiteUtilidad: LIMITE_UTILIDAD,
  cargando: true,
  guardando: false,
  guardado: false,
  listo: false,
  error: '',
  pesos,

  async iniciar() {
    try {
      this.mostrar(await api.obtenerConfiguracion())
      this.listo = true
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar la configuración.'
    } finally {
      this.cargando = false
    }
  },

  mostrar(config) {
    this.config = config
    this.comunas = Object.keys(config.factoresComuna)
    this.materiales = Object.keys(config.factoresMaterial)
  },

  // Mismas reglas que FastAPI, para avisar antes de enviar.
  validar() {
    const c = this.config
    const numero = (v: unknown) => typeof v === 'number' && Number.isFinite(v)
    if (!numero(c.valorHoraHombre) || c.valorHoraHombre < 0) return 'Revisa el valor de la hora hombre.'
    if (!numero(c.gastosGeneralesPct) || c.gastosGeneralesPct < 0 || c.gastosGeneralesPct > LIMITE_GASTOS_GENERALES) {
      return `Los gastos generales deben estar entre 0 y ${LIMITE_GASTOS_GENERALES} %.`
    }
    if (!numero(c.utilidadPct) || c.utilidadPct < 0 || c.utilidadPct > LIMITE_UTILIDAD) {
      return `La utilidad debe estar entre 0 y ${LIMITE_UTILIDAD} %.`
    }
    const factores = [
      ...Object.values(c.factoresComuna),
      ...Object.values(c.factoresMaterial),
      ...Object.values(c.factoresEstandar),
      ...c.tramosPisos.map((t) => t.factor),
    ]
    if (factores.some((f) => !numero(f) || f <= 0)) return 'Todos los factores deben ser mayores que 0.'
    return ''
  },

  async guardar() {
    if (this.guardando) return
    this.error = this.validar()
    if (this.error) return

    this.guardando = true
    try {
      this.mostrar(await api.guardarConfiguracion(this.config))
      this.guardado = true
      window.setTimeout(() => { this.guardado = false }, 2500)
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo guardar la configuración.'
    } finally {
      this.guardando = false
    }
  },

  async restaurar() {
    if (this.guardando) return
    if (!window.confirm('Se vuelve a los valores de fábrica. ¿Continuar?')) return

    this.guardando = true
    this.error = ''
    try {
      this.mostrar(await api.guardarConfiguracion(structuredClone(CONFIGURACION_BASE)))
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo restaurar la configuración.'
    } finally {
      this.guardando = false
    }
  },

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
}
