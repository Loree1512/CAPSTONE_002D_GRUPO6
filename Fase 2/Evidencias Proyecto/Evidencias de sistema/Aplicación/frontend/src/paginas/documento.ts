import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { exigirSesion } from '../lib/sesion'
import { pesos, numero, factor } from '../lib/formato'
import { ESTANDARES } from '../lib/catalogos'
import { conPlazo, ultimaEstimacion } from '../lib/estimaciones'
import { plazoDocumento } from '../lib/plazo'
import type { Proyecto } from '../tipos/api'
import type { Estimacion } from '../tipos/estimacion'

interface Documento {
  proyectoId: string | null
  proyecto: Proyecto | null
  presupuesto: Estimacion | null
  folio: string
  fecha: string
  versionBanco: string
  cargando: boolean
  error: string
  pesos: typeof pesos
  numero: typeof numero
  factor: typeof factor

  get etiquetaEstandar(): string
  /** Solo el plazo definido por el profesional; nada del modelo de plazo. */
  get plazoCliente(): { pendiente: boolean; texto: string }
  iniciar(): Promise<void>
  /** Abre el diálogo del navegador. El PDF se obtiene eligiendo «Guardar como PDF» en el destino;
   *  el título temporal es el nombre que el navegador propone para el archivo. */
  imprimir(): void
}

/** Folio del documento: BC-año-correlativo derivado del id del proyecto. */
function folioDe(proyecto: Proyecto): string {
  const año = new Date(proyecto.creado_en ?? Date.now()).getFullYear()
  const digitos = (proyecto.id.match(/\d/g) ?? ['0']).join('').slice(-4).padStart(4, '0')
  return `BC-${año}-${digitos}`
}

Alpine.data('documento', (): Documento => ({
  proyectoId: new URLSearchParams(window.location.search).get('id'),
  proyecto: null,
  presupuesto: null,
  folio: '',
  fecha: new Date().toLocaleDateString('es-CL', { day: '2-digit', month: 'long', year: 'numeric' }),
  versionBanco: '—',
  cargando: true,
  error: '',
  pesos,
  numero,
  factor,

  // El documento es para el cliente: muestra el plazo para la cotización y nunca la
  // sugerencia del modelo, su rango, su versión ni sus métricas.
  get plazoCliente() {
    return plazoDocumento(this.presupuesto?.plazoProfesional)
  },

  get etiquetaEstandar() {
    return ESTANDARES.find((e) => e.valor === this.proyecto?.estandar_terminaciones)?.etiqueta ?? '—'
  },

  async iniciar() {
    const id = this.proyectoId
    const estimacionId = new URLSearchParams(window.location.search).get('estimacion')
    if (!id) {
      this.error = 'No se indicó el proyecto.'
      this.cargando = false
      return
    }

    try {
      // Solo lee estimaciones guardadas: abrir el documento no calcula una nueva.
      const [proyecto, estimacion] = await Promise.all([
        api.obtenerProyecto(id),
        estimacionId ? api.obtenerEstimacion(id, estimacionId) : ultimaEstimacion(id),
      ])

      if (!estimacion) {
        this.error = 'Este proyecto todavía no tiene una estimación. Ábrelo primero en la pantalla de estimación.'
        return
      }

      // Antecedentes tal como se estimaron, para que calcen con las cifras.
      const e = estimacion.proyecto
      this.proyecto = {
        ...proyecto,
        comuna: e.comuna,
        tipo_obra: e.tipoObra,
        material: e.materialidad,
        superficie_m2: e.superficieM2,
        pisos: e.numeroPisos,
        estandar_terminaciones: e.estandarTerminaciones,
      }
      this.folio = folioDe(proyecto)
      this.versionBanco = estimacion.versionPrecios.version
      this.presupuesto = conPlazo(estimacion)
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo preparar el documento.'
    } finally {
      this.cargando = false
    }
  },

  imprimir() {
    const titulo = document.title
    if (this.folio) document.title = `Estimación ${this.folio}${this.proyecto ? ' · ' + this.proyecto.nombre : ''}`
    window.addEventListener('afterprint', () => { document.title = titulo }, { once: true })
    window.print()
  },
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
}
