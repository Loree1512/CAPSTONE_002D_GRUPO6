import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir } from '../lib/sesion'
import { COMUNAS, ESTANDARES, MATERIALES, TIPOS_OBRA } from '../lib/catalogos'
import type { EstandarTerminaciones, ProyectoNuevo } from '../tipos/api'

interface Formulario {
  id: string | null
  datos: ProyectoNuevo
  comunas: string[]
  tipos: string[]
  materiales: string[]
  estandares: { valor: EstandarTerminaciones; etiqueta: string }[]
  cargando: boolean
  guardando: boolean
  error: string
  errores: Partial<Record<keyof ProyectoNuevo, string>>
  get edicion(): boolean
  get titulo(): string
  iniciar(): Promise<void>
  guardar(): Promise<void>
  volver(): void
  salir(): void
  etiquetaEstandar(): string
  cierre: { fecha_inicio_real: string; fecha_termino_real: string; costo_real: number | null }
  guardandoCierre: boolean
  cierreGuardado: boolean
  get plazoReal(): number | null
  guardarCierre(): Promise<void>
}

const VACIO: ProyectoNuevo = {
  nombre: '',
  comuna: COMUNAS[0],
  tipo_obra: TIPOS_OBRA[0],
  material: MATERIALES[0],
  superficie_m2: 0,
  pisos: 1,
  estandar_terminaciones: 'medio',
}

Alpine.data('formularioProyecto', (): Formulario => ({
  id: new URLSearchParams(window.location.search).get('id'),
  datos: { ...VACIO },
  comunas: COMUNAS,
  tipos: TIPOS_OBRA,
  materiales: MATERIALES,
  estandares: ESTANDARES,
  cargando: false,
  guardando: false,
  cierre: { fecha_inicio_real: '', fecha_termino_real: '', costo_real: null },
  guardandoCierre: false,
  cierreGuardado: false,
  error: '',
  errores: {},

  get edicion() {
    return this.id !== null
  },

  get titulo() {
    return this.edicion ? 'Editar proyecto' : 'Crear proyecto'
  },

  async iniciar() {
    if (!this.edicion) return
    this.cargando = true
    try {
      const p = await api.obtenerProyecto(this.id as string)
      this.datos = {
        nombre: p.nombre,
        comuna: p.comuna,
        tipo_obra: p.tipo_obra,
        material: p.material,
        superficie_m2: p.superficie_m2,
        pisos: p.pisos,
        estandar_terminaciones: p.estandar_terminaciones,
      }
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar el proyecto.'
    } finally {
      this.cargando = false
    }
  },

  async guardar() {
    this.error = ''
    this.errores = {}

    if (!this.datos.nombre.trim()) this.errores.nombre = 'Escribe un nombre para el proyecto.'
    if (!(Number(this.datos.superficie_m2) > 0)) this.errores.superficie_m2 = 'La superficie debe ser mayor que cero.'
    if (!(Number(this.datos.pisos) >= 1)) this.errores.pisos = 'Debe haber al menos un piso.'
    if (Object.keys(this.errores).length > 0) return

    const carga: ProyectoNuevo = {
      ...this.datos,
      nombre: this.datos.nombre.trim(),
      superficie_m2: Number(this.datos.superficie_m2),
      pisos: Number(this.datos.pisos),
    }

    this.guardando = true
    try {
      if (this.edicion) {
        await api.actualizarProyecto(this.id as string, carga)
        window.location.assign('/proyectos.html')
      } else {
        // Recién creado: directo a revisar sus partidas.
        const creado = await api.crearProyecto(carga)
        window.location.assign(`/estimacion.html?id=${creado.id}`)
      }
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo guardar el proyecto.'
    } finally {
      this.guardando = false
    }
  },

  get plazoReal() {
    const { fecha_inicio_real: inicio, fecha_termino_real: termino } = this.cierre
    if (!inicio || !termino) return null
    const dias = (new Date(termino).getTime() - new Date(inicio).getTime()) / 86_400_000
    return dias > 0 ? Math.round(dias) : null
  },

  async guardarCierre() {
    if (!this.id || !this.plazoReal) {
      this.error = 'Revisa las fechas: el término debe ser posterior al inicio.'
      return
    }
    this.guardandoCierre = true
    try {
      await api.registrarCierreObra(this.id, { ...this.cierre, plazo_real_dias: this.plazoReal })
      this.cierreGuardado = true
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo registrar el cierre.'
    } finally {
      this.guardandoCierre = false
    }
  },

  etiquetaEstandar() {
    return ESTANDARES.find((e) => e.valor === this.datos.estandar_terminaciones)?.etiqueta ?? '—'
  },

  volver() {
    window.location.assign('/proyectos.html')
  },

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
}
