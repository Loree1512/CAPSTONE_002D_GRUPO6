import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir } from '../lib/sesion'
import { confirmar } from '../lib/confirmar'
import {
  conCalculo, crearSecuencia, estadoTrasCalcular, filaEnProceso, hayFilasEnProceso, iniciarFila, puedeCalcular,
  terminarFila, textoBotonCalcular,
} from '../lib/calculoPresupuesto'
import type { FilasEnProceso } from '../lib/calculoPresupuesto'
import { partidaDeCatalogoAgregada } from '../lib/duplicados'
import { pesos, numero, fecha, factor, leerPrecioEscrito, precioUnitario } from '../lib/formato'
import { ESTANDARES } from '../lib/catalogos'
import { CONFIGURACION_BASE } from '../lib/configuracion'
import { conPlazo, proyectoCambio, ultimaEstimacion } from '../lib/estimaciones'
import {
  cargarDetalleProyecto, mensajeCargaProyecto, MENSAJE_SIN_ID, puedeReintentar, vistaDetalle,
} from '../lib/detalleProyecto'
import type { VistaDetalle } from '../lib/detalleProyecto'
import {
  advertenciaSugerencia, avisoPlazo, bloqueoCronograma, confirmarSugerencia, diasParaCronograma, ERROR_PLAZO_ESCRITO,
  etiquetaModelo, filasTransparenciaModelo, filasTransparenciaProfesional, hayPlazo, leerPlazoEscrito, lineaErrorMedio,
  PLAZO_PROFESIONAL_MAX, PLAZO_PROFESIONAL_MIN, presentarPlazo, presentarPlazoProfesional, puedeGuardarPlazoEscrito,
  rotuloCronograma, textoDias, textoEstadoModelo, textoPlazo, textoRango,
} from '../lib/plazo'
import type { FilaTransparencia, PresentacionPlazo, PresentacionProfesional } from '../lib/plazo'
import { presentarUfUtilizada, type PresentacionUf } from '../lib/uf'
import { crearMiembros, etiquetaRol, ROLES_ASIGNABLES } from '../lib/miembros'
import type { GestionMiembros } from '../lib/miembros'
import { crearHistorial, describirEvento } from '../lib/historial'
import type { EntradaHistorial, Historial } from '../lib/historial'
import {
  accionCotizacion, errorObservaciones, normalizarObservaciones, observacionesCambiaron, OBSERVACIONES_MAX,
  puedeEditarObservaciones, puedeEditarPlazo,
} from '../lib/observaciones'
import type { AccionCotizacion } from '../lib/observaciones'
import { LIMITE_GASTOS_GENERALES, LIMITE_UTILIDAD } from '../tipos/estimacion'
import type { DefinirPlazoProfesional, Estimacion, LineaEstimacion } from '../tipos/estimacion'
import type {
  CategoriaPartida, FilaBanco, PartidaProyecto, PartidaProyectoEditada, PlantillaResumen, Proyecto,
} from '../tipos/api'

interface GrupoPartidas {
  codigo: string
  nombre: string
  partidas: PartidaProyecto[]
  subtotal: number
}

interface PartidaManual {
  categoria_id: number
  nombre: string
  unidad: string
  cantidad: number | null
  precio: number | null
}

type Pestana = 'presupuesto' | 'cronograma' | 'transparencia' | 'miembros' | 'historial'

interface PantallaEstimacion {
  proyecto: Proyecto | null
  presupuesto: Estimacion | null
  partidas: PartidaProyecto[]
  plantillaAplicada: PlantillaResumen | null
  plantillaSugerida: PlantillaResumen | null
  versionVigenteId: string | null
  categorias: CategoriaPartida[]
  gg: number
  utilidad: number
  aplicarFactores: boolean
  limiteGg: number
  limiteUtilidad: number
  pestana: Pestana
  cargando: boolean
  guardando: boolean
  /** Partidas que se están guardando, por id: cada fila avisa lo suyo sin bloquear a las demás. */
  enProceso: FilasEnProceso
  /** Numera los refrescos del proyecto: solo el último aplica su respuesta. */
  refresco: ReturnType<typeof crearSecuencia>
  /** Partida de catálogo que el usuario intentó agregar y ya está en el presupuesto. */
  duplicada: PartidaProyecto | null
  agregandoCatalogo: boolean
  /** Partida resaltada un momento tras «Ver partida». */
  destacada: string
  nombreEditando: string
  error: string
  /** Único interruptor de la pantalla: esqueleto, contenido real o error. */
  get vista(): VistaDetalle
  get puedeReintentar(): boolean
  errorCalculo: string
  errorPartidas: string

  // Observaciones de la cotización
  observaciones: string
  limiteObservaciones: number
  actualizandoCotizacion: boolean
  errorCotizacion: string
  get puedeEditarObservaciones(): boolean
  get observacionCambio(): boolean
  get errorTextoObservaciones(): string
  get costoPendiente(): boolean
  get accion(): AccionCotizacion
  get puedeActualizarCotizacion(): boolean
  actualizarCotizacion(): Promise<void>

  // Plazo para la cotización (lo define el profesional; el modelo solo sugiere)
  plazoEscrito: string
  plazoMin: number
  plazoMax: number
  guardandoPlazo: boolean
  errorPlazo: string
  get puedeEditarPlazo(): boolean
  get profesional(): PresentacionProfesional
  get errorMedio(): string
  get estadoModelo(): string
  get sugerenciaDisponible(): boolean
  get textoUsarSugerencia(): string
  get advertenciaSugerencia(): string
  get errorPlazoEscrito(): string
  get puedeGuardarPlazo(): boolean
  get textoMantener(): string
  get transparenciaModelo(): FilaTransparencia[]
  get transparenciaProfesional(): FilaTransparencia[]
  definirPlazo(cuerpo: DefinirPlazoProfesional): Promise<void>
  guardarPlazo(): Promise<void>
  usarSugerencia(): Promise<void>
  mantenerPlazo(): Promise<void>

  // Agregar partida
  modalAgregar: boolean
  modoAgregar: 'catalogo' | 'manual'
  catalogo: FilaBanco[]
  cargandoCatalogo: boolean
  busqueda: string
  cantidadCatalogo: number | null
  manual: PartidaManual
  errorAgregar: string
  avisoAgregar: string
  unidades: string[]

  // Plantilla
  modalPlantilla: boolean
  plantillas: PlantillaResumen[]
  cargandoPlantillas: boolean
  plantillaElegida: string
  confirmaReemplazo: boolean
  errorPlantilla: string

  // Miembros e historial
  miembros: GestionMiembros
  historial: Historial
  roles: typeof ROLES_ASIGNABLES
  etiquetaRol: typeof etiquetaRol
  get entradasHistorial(): EntradaHistorial[]
  abrirPestana(p: Pestana): void

  pesos: typeof pesos
  numero: typeof numero
  fecha: typeof fecha
  textoPlazo: typeof textoPlazo
  textoRango: typeof textoRango
  etiquetaModelo: typeof etiquetaModelo
  avisoPlazo: typeof avisoPlazo
  hayPlazo: typeof hayPlazo
  bloqueoCronograma: typeof bloqueoCronograma
  get presentacion(): PresentacionPlazo
  get ufUtilizada(): PresentacionUf
  factor: typeof factor
  precioUnitario: typeof precioUnitario

  get etiquetaEstandar(): string
  get grupos(): GrupoPartidas[]
  get sumaPartidas(): number
  get pendientes(): number
  get datosCambiaron(): boolean
  get versionCambio(): boolean
  get partidasCambiaron(): boolean
  get ajustesCambiaron(): boolean
  get errorAjustes(): string
  get puedeAplicar(): boolean
  get hayFilasEnProceso(): boolean
  filaEnProceso(id: string): boolean
  verPartidaExistente(): Promise<void>
  get textoAplicar(): string
  get etapas(): { nombre: string; desde: number; hasta: number; dias: number }[]
  /** Días que reparte el cronograma: el plazo para la cotización o, si falta, la sugerencia. */
  get diasCronograma(): number
  get rotuloCronograma(): string
  get enlaceDocumento(): string
  get resultadosCatalogo(): FilaBanco[]
  get plantillaSeleccionada(): PlantillaResumen | undefined

  iniciar(): Promise<void>
  reintentar(): void
  refrescarEstado(): Promise<void>
  mostrar(estimacion: Estimacion): void
  aplicar(): Promise<void>

  editar(p: PartidaProyecto, cambios: PartidaProyectoEditada): Promise<void>
  cambiarCantidad(p: PartidaProyecto, valor: string): void
  cambiarPrecio(p: PartidaProyecto, valor: string): void
  cambiarNombre(p: PartidaProyecto, valor: string): void
  editarNombre(p: PartidaProyecto, celda: HTMLElement): void
  terminarNombre(p: PartidaProyecto, valor: string): void
  precioAlEditar(p: PartidaProyecto): string
  cambiarPrecioEscrito(p: PartidaProyecto, texto: string): void
  origenPartida(p: PartidaProyecto): string
  usarPrecioBanco(p: PartidaProyecto): void
  quitar(p: PartidaProyecto): Promise<void>
  mover(p: PartidaProyecto, paso: number): Promise<void>
  puedeMover(p: PartidaProyecto, paso: number): boolean

  abrirAgregar(): Promise<void>
  agregarDelCatalogo(f: FilaBanco): Promise<void>
  agregarManual(): Promise<void>

  abrirPlantilla(): Promise<void>
  aplicarPlantilla(): Promise<void>
  nombrePlantilla(p: PlantillaResumen | null | undefined): string

  origen(l: LineaEstimacion): string
  salir(): void
}

/* Reparto del plazo por etapa, proporcional a la incidencia de los
   capítulos que la componen. Es una distribución referencial: sirve para
   ordenar la conversación con el mandante, no para programar la obra. */
const ETAPAS: { nombre: string; capitulos: string[] }[] = [
  { nombre: 'Instalación de faenas y movimiento de tierras', capitulos: ['01', '02'] },
  { nombre: 'Fundaciones',                                    capitulos: ['03'] },
  { nombre: 'Obra gruesa y estructura',                       capitulos: ['04'] },
  { nombre: 'Techumbre',                                      capitulos: ['05'] },
  { nombre: 'Terminaciones y carpinterías',                   capitulos: ['06', '07'] },
  { nombre: 'Instalaciones',                                  capitulos: ['08', '09', '10'] },
  { nombre: 'Obras exteriores, aseo y entrega',               capitulos: ['11', '12'] },
]

// Unidades sugeridas; en una partida manual se puede escribir otra.
const UNIDADES = ['m2', 'm3', 'ml', 'kg', 'un', 'gl', 'pto', 'día', 'mes']

const enRango = (valor: unknown, maximo: number) =>
  typeof valor === 'number' && Number.isFinite(valor) && valor >= 0 && valor <= maximo

/** '' = sin valor; texto no numérico o negativo = inválido (undefined). */
function leerNumero(valor: string): number | null | undefined {
  if (valor.trim() === '') return null
  const n = Number(valor)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

const manualVacia = (categoriaId = 1): PartidaManual =>
  ({ categoria_id: categoriaId, nombre: '', unidad: 'gl', cantidad: null, precio: null })

const idProyecto = new URLSearchParams(window.location.search).get('id') ?? ''

Alpine.data('estimacion', (): PantallaEstimacion => ({
  proyecto: null,
  presupuesto: null,
  partidas: [],
  plantillaAplicada: null,
  plantillaSugerida: null,
  versionVigenteId: null,
  categorias: [],
  gg: 0,
  utilidad: 0,
  aplicarFactores: false,
  limiteGg: LIMITE_GASTOS_GENERALES,
  limiteUtilidad: LIMITE_UTILIDAD,
  pestana: 'presupuesto',
  cargando: true,
  guardando: false,
  enProceso: {},
  refresco: crearSecuencia(),
  duplicada: null,
  agregandoCatalogo: false,
  destacada: '',
  nombreEditando: '',
  error: '',
  errorCalculo: '',
  errorPartidas: '',

  observaciones: '',
  limiteObservaciones: OBSERVACIONES_MAX,
  actualizandoCotizacion: false,
  errorCotizacion: '',

  plazoEscrito: '',
  plazoMin: PLAZO_PROFESIONAL_MIN,
  plazoMax: PLAZO_PROFESIONAL_MAX,
  guardandoPlazo: false,
  errorPlazo: '',

  modalAgregar: false,
  modoAgregar: 'catalogo',
  catalogo: [],
  cargandoCatalogo: false,
  busqueda: '',
  cantidadCatalogo: null,
  manual: manualVacia(),
  errorAgregar: '',
  avisoAgregar: '',
  unidades: UNIDADES,

  modalPlantilla: false,
  plantillas: [],
  cargandoPlantillas: false,
  plantillaElegida: '',
  confirmaReemplazo: false,
  errorPlantilla: '',

  miembros: crearMiembros({
    listar: () => api.listarMiembros(idProyecto),
    candidatos: (buscar) => api.listarCandidatosMiembro(idProyecto, buscar),
    agregar: (email, rol) => api.agregarMiembro(idProyecto, email, rol),
    cambiarRol: (usuarioId, rol) => api.cambiarRolMiembro(idProyecto, usuarioId, rol),
    quitar: (usuarioId) => api.quitarMiembro(idProyecto, usuarioId),
  }),
  historial: crearHistorial(() => api.listarHistorial(idProyecto)),
  roles: ROLES_ASIGNABLES,
  etiquetaRol,

  pesos,
  numero,
  fecha,
  factor,
  precioUnitario,
  textoPlazo,
  textoRango,
  etiquetaModelo,
  avisoPlazo,
  hayPlazo,
  bloqueoCronograma,

  // Datos con que se calculó, no los actuales del proyecto.
  get vista() {
    return vistaDetalle(this)
  },

  get puedeReintentar() {
    return puedeReintentar(this.error)
  },

  get etiquetaEstandar() {
    const estandar = this.presupuesto?.proyecto.estandarTerminaciones ?? this.proyecto?.estandar_terminaciones
    return ESTANDARES.find((e) => e.valor === estandar)?.etiqueta ?? '—'
  },

  /** Partidas por categoría, en el orden del presupuesto. */
  get grupos() {
    const grupos: GrupoPartidas[] = []
    const ordenadas = [...this.partidas].sort((a, b) => a.categoria_orden - b.categoria_orden || a.orden - b.orden)
    for (const p of ordenadas) {
      let grupo = grupos.find((g) => g.codigo === p.categoria_codigo)
      if (!grupo) {
        grupo = { codigo: p.categoria_codigo, nombre: p.categoria_nombre, partidas: [], subtotal: 0 }
        grupos.push(grupo)
      }
      grupo.partidas.push(p)
      grupo.subtotal += p.subtotal ?? 0
    }
    return grupos
  },

  // Suma en vivo, sin factores ni GG/utilidad: la oficial es la estimación guardada.
  get sumaPartidas() {
    return this.partidas.reduce((suma, p) => suma + (p.subtotal ?? 0), 0)
  },

  get pendientes() {
    return this.partidas.filter((p) => p.estado !== 'calculada').length
  },

  get datosCambiaron() {
    return !!this.presupuesto && !!this.proyecto && proyectoCambio(this.presupuesto, this.proyecto)
  },

  get versionCambio() {
    return !!this.presupuesto && !!this.versionVigenteId
      && this.presupuesto.versionPrecios.id !== this.versionVigenteId
  },

  // El backend compara partidas, datos y versión; aquí quedan solo las partidas.
  get partidasCambiaron() {
    return !!this.presupuesto && this.proyecto?.estado === 'recalcular'
      && !this.datosCambiaron && !this.versionCambio
  },

  get ajustesCambiaron() {
    return !!this.presupuesto
      && (this.gg !== this.presupuesto.gastosGeneralesPct
        || this.utilidad !== this.presupuesto.utilidadPct
        || this.aplicarFactores !== this.presupuesto.aplicarFactores)
  },

  // Mismos límites que FastAPI; el backend vuelve a validar.
  get errorAjustes() {
    if (!enRango(this.gg, LIMITE_GASTOS_GENERALES)) {
      return `Los gastos generales deben estar entre 0 y ${LIMITE_GASTOS_GENERALES} %.`
    }
    if (!enRango(this.utilidad, LIMITE_UTILIDAD)) {
      return `La utilidad debe estar entre 0 y ${LIMITE_UTILIDAD} %.`
    }
    return ''
  },

  get puedeAplicar() {
    return puedeCalcular({
      guardando: this.guardando,
      hayFilasEnProceso: this.hayFilasEnProceso,
      errorAjustes: this.errorAjustes,
      errorTextoObservaciones: this.errorTextoObservaciones,
      hayPartidas: this.partidas.length > 0,
      hayPresupuesto: !!this.presupuesto,
      costoPendiente: this.costoPendiente,
    })
  },

  get hayFilasEnProceso() {
    return hayFilasEnProceso(this.enProceso)
  },

  filaEnProceso(id) {
    return filaEnProceso(this.enProceso, id)
  },

  // Lo que cambia el costo. La observación no está aquí: no pide recalcular.
  get costoPendiente() {
    return this.ajustesCambiaron || this.proyecto?.estado === 'recalcular' || this.datosCambiaron || this.versionCambio
  },

  // --- Observaciones -----------------------------------------------------------

  get puedeEditarObservaciones() {
    return puedeEditarObservaciones(this.miembros.miRol)
  },

  // Comparada con la de la estimación mostrada, que el formulario propone por defecto.
  get observacionCambio() {
    return !!this.presupuesto && observacionesCambiaron(this.observaciones, this.presupuesto.observaciones)
  },

  get errorTextoObservaciones() {
    return errorObservaciones(this.observaciones)
  },

  get accion() {
    return accionCotizacion({
      hayEstimacion: !!this.presupuesto,
      costoPendiente: this.costoPendiente,
      observacionCambio: this.observacionCambio,
    })
  },

  get puedeActualizarCotizacion() {
    return this.accion === 'actualizar' && this.puedeEditarObservaciones
      && !this.actualizandoCotizacion && !this.guardando && !this.errorTextoObservaciones
  },

  // Nueva estimación con los mismos montos: no pasa por el motor.
  async actualizarCotizacion() {
    if (!this.proyecto || !this.presupuesto || !this.puedeActualizarCotizacion) return
    this.actualizandoCotizacion = true
    this.errorCotizacion = ''
    try {
      this.mostrar(await api.actualizarCotizacion(
        this.proyecto.id, this.presupuesto.id, normalizarObservaciones(this.observaciones)))
    } catch (e) {
      this.errorCotizacion = e instanceof ErrorApi ? e.message : 'No se pudo actualizar la cotización.'
    } finally {
      this.actualizandoCotizacion = false
    }
  },

  get textoAplicar() {
    return textoBotonCalcular({
      guardando: this.guardando,
      hayFilasEnProceso: this.hayFilasEnProceso,
      hayPresupuesto: !!this.presupuesto,
      ajustesCambiaron: this.ajustesCambiaron,
    })
  },

  // --- Plazo ---------------------------------------------------------------------

  // Sugerencia del modelo: referencia interna para el profesional.
  get presentacion() {
    return presentarPlazo(this.presupuesto?.plazo)
  },

  // Error medio y estado del modelo: salen de la versión del modelo (backend), no de aquí.
  get errorMedio() {
    return lineaErrorMedio(this.presupuesto?.plazo)
  },

  get estadoModelo() {
    return textoEstadoModelo(this.presupuesto?.plazo)
  },

  // Plazo para la cotización: el que va al documento de entrega.
  get puedeEditarPlazo() {
    return puedeEditarPlazo(this.miembros.miRol)
  },

  get profesional() {
    return presentarPlazoProfesional(this.presupuesto?.plazoProfesional)
  },

  // En la demostración no hay modelo: no hay sugerencia que usar.
  get sugerenciaDisponible() {
    return hayPlazo(this.presupuesto?.plazo)
  },

  get textoUsarSugerencia() {
    const plazo = this.presupuesto?.plazo
    return hayPlazo(plazo) ? `Usar sugerencia de ${textoDias(plazo.dias)}` : 'Usar sugerencia'
  },

  get advertenciaSugerencia() {
    return advertenciaSugerencia(this.presupuesto?.plazo)
  },

  get errorPlazoEscrito() {
    return leerPlazoEscrito(this.plazoEscrito) === undefined ? ERROR_PLAZO_ESCRITO : ''
  },

  get puedeGuardarPlazo() {
    return !!this.presupuesto && this.puedeEditarPlazo && !this.guardandoPlazo && !this.guardando
      && !this.actualizandoCotizacion && puedeGuardarPlazoEscrito(this.plazoEscrito, this.presupuesto.plazoProfesional)
  },

  get textoMantener() {
    const dias = this.presupuesto?.plazoProfesional.dias
    return typeof dias === 'number' ? `Mantener ${textoDias(dias)}` : 'Mantener'
  },

  get transparenciaModelo() {
    return filasTransparenciaModelo(this.presupuesto?.plazo)
  },

  get transparenciaProfesional() {
    return filasTransparenciaProfesional(this.presupuesto?.plazoProfesional, this.presupuesto?.plazo)
  },

  // Nueva estimación con el plazo definido y lo demás igual: no recalcula ni toca la sugerencia.
  async definirPlazo(cuerpo) {
    if (!this.proyecto || !this.presupuesto || !this.puedeEditarPlazo || this.guardandoPlazo) return
    this.guardandoPlazo = true
    this.errorPlazo = ''
    try {
      const nueva = conPlazo(await api.definirPlazoProfesional(this.proyecto.id, this.presupuesto.id, cuerpo))
      // Solo el presupuesto mostrado: el formulario (ajustes, observaciones) conserva lo que se esté editando.
      this.presupuesto = nueva
      this.plazoEscrito = nueva.plazoProfesional.dias === null ? '' : String(nueva.plazoProfesional.dias)
    } catch (e) {
      this.errorPlazo = e instanceof ErrorApi ? e.message : 'No se pudo guardar el plazo para la cotización.'
    } finally {
      this.guardandoPlazo = false
    }
  },

  async guardarPlazo() {
    const dias = leerPlazoEscrito(this.plazoEscrito)
    if (!this.puedeGuardarPlazo || typeof dias !== 'number') return
    await this.definirPlazo({ dias })
  },

  // Fuera del dominio o con el respaldo, se pide confirmación antes de guardar.
  async usarSugerencia() {
    if (!this.presupuesto || !this.puedeEditarPlazo || !this.sugerenciaDisponible || this.guardandoPlazo) return
    if (!(await confirmarSugerencia(this.presupuesto.plazo, confirmar))) return
    await this.definirPlazo({ usarSugerencia: true })
  },

  // Resuelve «por revisar» con el mismo valor.
  async mantenerPlazo() {
    const dias = this.presupuesto?.plazoProfesional.dias
    if (typeof dias !== 'number') return
    await this.definirPlazo({ dias })
  },

  // Snapshot guardado con la estimación, no la UF de hoy.
  get ufUtilizada() {
    return presentarUfUtilizada(this.presupuesto?.plazo)
  },

  // Sin plazo, o con la estimación incompleta, no se reparte nada: con pocas partidas
  // las etapas quedarían en 0 días y parecería un cronograma real.
  // Con el plazo para la cotización (definido o por revisar) se reparte ese; si no, la
  // sugerencia del modelo, rotulada como distribución interna.
  get diasCronograma() {
    if (!this.presupuesto) return 0
    return diasParaCronograma(this.presupuesto.plazo, this.presupuesto.completa, this.presupuesto.plazoProfesional)
  },

  get rotuloCronograma() {
    return rotuloCronograma(this.presupuesto?.plazo, this.presupuesto?.plazoProfesional)
  },

  get etapas() {
    if (!this.presupuesto) return []
    const plazo = this.diasCronograma
    if (plazo === 0) return []
    const total = this.presupuesto.costoDirecto
    let acumulado = 0

    return ETAPAS.map((etapa) => {
      const peso = this.presupuesto!.capitulos
        .filter((c) => etapa.capitulos.includes(c.codigo))
        .reduce((suma, c) => suma + c.subtotal, 0) / (total || 1)

      const dias = Math.round(plazo * peso)
      const desde = acumulado
      acumulado += dias
      return { nombre: etapa.nombre, desde, hasta: acumulado, dias }
    })
  },

  get enlaceDocumento() {
    if (!this.proyecto || !this.presupuesto) return '#'
    return `/documento.html?id=${this.proyecto.id}&estimacion=${this.presupuesto.id}`
  },

  get resultadosCatalogo() {
    const texto = this.busqueda.trim().toLowerCase()
    return this.catalogo
      .filter((f) => f.vigente)
      .filter((f) => !texto || f.nombre.toLowerCase().includes(texto) || f.codigo.includes(texto))
      .slice(0, 40)
  },

  get plantillaSeleccionada() {
    return this.plantillas.find((p) => p.id === this.plantillaElegida)
  },

  get entradasHistorial() {
    const categorias = Object.fromEntries(this.categorias.map((c) => [c.id, c.nombre]))
    return this.historial.eventos.map((e) => describirEvento(e, { nombres: this.miembros.nombres, categorias }))
  },

  abrirPestana(p) {
    this.pestana = p
    if (p === 'miembros' && !this.miembros.cargado) void this.miembros.cargar()
    if (p === 'historial') {
      // Se recarga cada vez: puede haber cambios desde la última visita.
      void this.historial.cargar()
      // Con los miembros, el historial muestra nombres en vez de correos.
      if (!this.miembros.cargado) void this.miembros.cargar()
    }
  },

  async iniciar() {
    this.cargando = true
    this.error = ''
    if (!idProyecto) {
      this.error = MENSAJE_SIN_ID
      this.cargando = false
      return
    }

    try {
      const detalle = await cargarDetalleProyecto(
        {
          obtenerProyecto: api.obtenerProyecto,
          listarVersiones: api.listarVersiones,
          listarCategorias: api.listarCategorias,
          listarPartidasProyecto: api.listarPartidasProyecto,
          obtenerConfiguracion: api.obtenerConfiguracion,
          ultimaEstimacion,
        },
        idProyecto, CONFIGURACION_BASE)
      // Se asigna todo junto y el proyecto al final: la vista real nunca ve
      // partidas, plantilla o estimación a medio llegar.
      this.miembros.miRol = detalle.proyecto.mi_rol ?? null
      this.versionVigenteId = detalle.versionVigenteId
      this.categorias = detalle.categorias
      this.partidas = detalle.partidas
      this.plantillaAplicada = detalle.plantillaAplicada
      this.plantillaSugerida = detalle.plantillaSugerida
      // Recargar muestra la guardada; sin estimación no se calcula sola.
      if (detalle.estimacion) {
        this.mostrar(detalle.estimacion)
      } else {
        this.gg = detalle.ajustes.gastosGeneralesPct
        this.utilidad = detalle.ajustes.utilidadPct
      }
      this.proyecto = detalle.proyecto
    } catch (e) {
      this.error = mensajeCargaProyecto(e)
    } finally {
      this.cargando = false
    }
  },

  reintentar() {
    if (this.cargando || !this.puedeReintentar) return
    void this.iniciar()
  },

  // El backend decide si la estimación quedó desactualizada.
  // Se lanza sin esperarlo: la acción ya terminó y esta lectura solo actualiza el aviso de estado.
  async refrescarEstado() {
    if (!this.proyecto) return
    const id = this.proyecto.id
    const numero = this.refresco.nueva()
    try {
      const actual = await api.obtenerProyecto(id)
      // Una respuesta lenta y vieja no pisa a una más reciente.
      if (this.refresco.vigente(numero) && this.proyecto?.id === id) this.proyecto = actual
    } catch {
      // Solo informativo: la tabla ya quedó guardada.
    }
  },

  mostrar(estimacion) {
    this.presupuesto = conPlazo(estimacion)
    this.gg = estimacion.gastosGeneralesPct
    this.utilidad = estimacion.utilidadPct
    this.aplicarFactores = estimacion.aplicarFactores
    // La siguiente estimación propone la misma observación; se puede cambiar antes de generarla.
    this.observaciones = estimacion.observaciones ?? ''
    // El campo parte del plazo ya decidido (también si está por revisar); vacío si no hay.
    const dias = this.presupuesto.plazoProfesional.dias
    this.plazoEscrito = dias === null ? '' : String(dias)
    this.errorPlazo = ''
  },

  async aplicar() {
    if (!this.proyecto || !this.puedeAplicar) return
    const proyecto = this.proyecto
    // Un solo cálculo a la vez; el botón se libera con éxito o con error. En error se conservan
    // los valores editados para corregir y reintentar.
    const estimacion = await conCalculo(this, async () => {
      const nueva = await api.crearEstimacion(proyecto.id, {
        gastos_generales_pct: this.gg,
        utilidad_pct: this.utilidad,
        aplicar_factores: this.aplicarFactores,
        observaciones: normalizarObservaciones(this.observaciones),
      })
      this.mostrar(nueva)
      // La estimación recién guardada ya está al día: no se espera a releer el proyecto para dejar
      // de mostrar «por recalcular». La lectura real corre aparte y confirma el estado.
      if (this.proyecto) this.proyecto = { ...this.proyecto, estado: estadoTrasCalcular(this.proyecto.estado) }
      void this.refrescarEstado()
      return nueva
    }, (e) => (e instanceof ErrorApi ? e.message : 'No se pudo calcular la estimación.'))
    if (!estimacion) return

    // El botón queda bajo las partidas y el resultado arriba: se lleva la vista hasta él.
    await Alpine.nextTick()
    const resultado = document.getElementById('resultado-estimacion')
    if (resultado) {
      // La barra superior es fija y en pantallas angostas ocupa dos líneas: se descuenta su alto real.
      const barra = document.querySelector('.bc-barra')?.getBoundingClientRect().bottom ?? 0
      const suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
      window.scrollTo({ top: window.scrollY + resultado.getBoundingClientRect().top - barra - 24, behavior: suave ? 'smooth' : 'auto' })
    }
  },

  // --- Edición de partidas ---------------------------------------------------

  async editar(p, cambios) {
    if (!this.proyecto) return
    this.enProceso = iniciarFila(this.enProceso, p.id)
    this.errorPartidas = ''
    try {
      const actualizada = await api.editarPartidaProyecto(this.proyecto.id, p.id, cambios)
      this.partidas = this.partidas.map((x) => (x.id === p.id ? actualizada : x))
      // La fila se libera con lo guardado; el aviso de estado se actualiza aparte.
      void this.refrescarEstado()
    } catch (e) {
      this.errorPartidas = e instanceof ErrorApi ? e.message : 'No se pudo guardar la partida.'
      // Vuelve a mostrar lo guardado.
      this.partidas = [...this.partidas]
    } finally {
      this.enProceso = terminarFila(this.enProceso, p.id)
    }
  },

  cambiarCantidad(p, valor) {
    const cantidad = leerNumero(valor)
    if (cantidad === undefined) {
      this.errorPartidas = 'La cantidad debe ser un número mayor o igual a 0.'
      return
    }
    if (cantidad !== p.cantidad) void this.editar(p, { cantidad })
  },

  // Editar el precio deja un precio particular del proyecto; vacío vuelve al banco.
  cambiarPrecio(p, valor) {
    const precio = leerNumero(valor)
    if (precio === undefined) {
      this.errorPartidas = 'El precio debe ser un número mayor o igual a 0.'
      return
    }
    // Sin cambios reales no se guarda nada.
    if (precio === p.precio_unitario_override) return
    if (p.precio_unitario_override == null && precio === p.precio_banco) return
    void this.editar(p, { precio_unitario_override: precio })
  },

  // El nombre se lee completo en varias líneas; al hacer clic pasa a un campo editable.
  editarNombre(p, celda) {
    this.nombreEditando = p.id
    window.setTimeout(() => celda.querySelector('input')?.focus(), 0)
  },

  terminarNombre(p, valor) {
    this.nombreEditando = ''
    this.cambiarNombre(p, valor)
  },

  // Al entrar a la celda se muestra el número sin formato, para editarlo cómodo.
  precioAlEditar(p) {
    return p.precio_unitario == null ? '' : String(p.precio_unitario).replace('.', ',')
  },

  // Solo traduce el texto con formato CLP; guardar sigue siendo cambiarPrecio.
  cambiarPrecioEscrito(p, texto) {
    this.cambiarPrecio(p, leerPrecioEscrito(texto))
  },

  origenPartida(p) {
    const origen = p.origen === 'manual' ? 'Partida del proyecto' : p.origen === 'plantilla' ? 'Desde plantilla' : 'Desde catálogo'
    return p.codigo ? `${p.codigo} · ${origen}` : origen
  },

  cambiarNombre(p, valor) {
    const nombre = valor.trim()
    if (!nombre) {
      this.errorPartidas = 'La partida necesita un nombre.'
      this.partidas = [...this.partidas]
      return
    }
    if (nombre !== p.nombre) void this.editar(p, { nombre })
  },

  usarPrecioBanco(p) {
    void this.editar(p, { precio_unitario_override: null })
  },

  async quitar(p) {
    if (!this.proyecto) return
    const ok = await confirmar({
      rotulo: 'Presupuesto', titulo: 'Quitar partida',
      mensaje: `¿Quitar «${p.nombre}» del presupuesto de este proyecto?`, confirmar: 'Quitar',
    })
    if (!ok) return
    this.errorPartidas = ''
    try {
      await api.eliminarPartidaProyecto(this.proyecto.id, p.id)
      this.partidas = this.partidas.filter((x) => x.id !== p.id)
      void this.refrescarEstado()
    } catch (e) {
      this.errorPartidas = e instanceof ErrorApi ? e.message : 'No se pudo quitar la partida.'
    }
  },

  puedeMover(p, paso) {
    const grupo = this.grupos.find((g) => g.codigo === p.categoria_codigo)
    const i = grupo ? grupo.partidas.findIndex((x) => x.id === p.id) : -1
    return i + paso >= 0 && !!grupo && i + paso < grupo.partidas.length
  },

  // Mueve dentro de su categoría y guarda el orden completo.
  async mover(p, paso) {
    if (!this.proyecto || !this.puedeMover(p, paso)) return
    const orden = this.grupos.flatMap((g) => g.partidas.map((x) => x.id))
    const i = orden.indexOf(p.id)
    ;[orden[i], orden[i + paso]] = [orden[i + paso], orden[i]]
    this.errorPartidas = ''
    try {
      this.partidas = await api.ordenarPartidasProyecto(this.proyecto.id, orden)
    } catch (e) {
      this.errorPartidas = e instanceof ErrorApi ? e.message : 'No se pudo cambiar el orden.'
    }
  },

  // --- Agregar partida ----------------------------------------------------------

  async abrirAgregar() {
    this.modalAgregar = true
    this.errorAgregar = ''
    this.avisoAgregar = ''
    this.duplicada = null
    this.busqueda = ''
    this.cantidadCatalogo = null
    this.manual = manualVacia(this.categorias[0]?.id)
    if (this.catalogo.length === 0) {
      // Mientras llega no se dice «ninguna partida coincide»: sería un vacío falso.
      this.cargandoCatalogo = true
      try {
        this.catalogo = await api.listarBanco()
      } catch (e) {
        this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo cargar el catálogo.'
      } finally {
        this.cargandoCatalogo = false
      }
    }
  },

  async agregarDelCatalogo(f) {
    // Un clic repetido mientras llega la respuesta no agrega la misma partida dos veces.
    if (!this.proyecto || this.agregandoCatalogo) return
    this.errorAgregar = ''
    this.avisoAgregar = ''
    // Misma partida de catálogo (mismo partida_id, sea de plantilla o agregada antes): no se duplica.
    // Se avisa y se ofrece ir a la fila existente, donde se puede cambiar la cantidad.
    const existente = partidaDeCatalogoAgregada(this.partidas, f.id)
    if (existente) {
      this.duplicada = existente
      return
    }
    this.duplicada = null
    const cantidad = this.cantidadCatalogo
    if (cantidad != null && (!Number.isFinite(cantidad) || cantidad < 0)) {
      this.errorAgregar = 'La cantidad debe ser un número mayor o igual a 0.'
      return
    }
    this.agregandoCatalogo = true
    try {
      const nueva = await api.crearPartidaProyecto(this.proyecto.id, {
        origen: 'catalogo', partida_id: f.id, cantidad: cantidad ?? null,
      })
      this.partidas = [...this.partidas, nueva]
      this.avisoAgregar = `Agregada: ${nueva.nombre}.`
      this.cantidadCatalogo = null
      void this.refrescarEstado()
    } catch (e) {
      this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo agregar la partida.'
    } finally {
      this.agregandoCatalogo = false
    }
  },

  // Cierra el catálogo, lleva la vista a la partida que ya estaba y la resalta un momento.
  async verPartidaExistente() {
    const existente = this.duplicada
    if (!existente) return
    this.duplicada = null
    this.modalAgregar = false
    this.pestana = 'presupuesto'
    this.destacada = existente.id
    await Alpine.nextTick()
    const fila = document.getElementById(`partida-${existente.id}`)
    const suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    fila?.scrollIntoView({ block: 'center', behavior: suave ? 'smooth' : 'auto' })
    window.setTimeout(() => { if (this.destacada === existente.id) this.destacada = '' }, 2400)
  },

  async agregarManual() {
    if (!this.proyecto) return
    const m = this.manual
    this.errorAgregar = ''
    if (!m.nombre.trim()) { this.errorAgregar = 'Escribe el nombre de la partida.'; return }
    if (!m.unidad.trim()) { this.errorAgregar = 'Indica la unidad.'; return }
    if (m.cantidad == null || !(m.cantidad >= 0)) { this.errorAgregar = 'Indica la cantidad.'; return }
    if (m.precio == null || !(m.precio >= 0)) { this.errorAgregar = 'Indica el precio unitario.'; return }
    try {
      const nueva = await api.crearPartidaProyecto(this.proyecto.id, {
        origen: 'manual',
        categoria_id: m.categoria_id,
        nombre: m.nombre.trim(),
        unidad: m.unidad.trim(),
        cantidad: m.cantidad,
        precio_unitario_override: m.precio,
      })
      this.partidas = [...this.partidas, nueva]
      this.avisoAgregar = `Agregada: ${nueva.nombre}.`
      this.manual = manualVacia(m.categoria_id)
      void this.refrescarEstado()
    } catch (e) {
      this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo agregar la partida.'
    }
  },

  // --- Plantilla ---------------------------------------------------------------

  async abrirPlantilla() {
    this.modalPlantilla = true
    this.errorPlantilla = ''
    this.confirmaReemplazo = false
    this.cargandoPlantillas = true
    try {
      this.plantillas = (await api.listarPlantillas()).filter((p) => p.vigente)
      this.plantillaElegida = this.plantillaSugerida?.id ?? this.plantillaAplicada?.id ?? this.plantillas[0]?.id ?? ''
    } catch (e) {
      this.errorPlantilla = e instanceof ErrorApi ? e.message : 'No se pudieron cargar las plantillas.'
    } finally {
      this.cargandoPlantillas = false
    }
  },

  async aplicarPlantilla() {
    if (!this.proyecto || !this.plantillaElegida) return
    const reemplazar = this.partidas.length > 0
    // Reemplazar exige confirmación explícita.
    if (reemplazar && !this.confirmaReemplazo) {
      this.errorPlantilla = 'Confirma que quieres reemplazar las partidas actuales.'
      return
    }
    this.errorPlantilla = ''
    try {
      const datos = await api.aplicarPlantilla(this.proyecto.id, this.plantillaElegida, reemplazar)
      this.partidas = datos.partidas
      this.plantillaAplicada = datos.plantilla_aplicada
      this.plantillaSugerida = datos.plantilla_sugerida
      this.modalPlantilla = false
      void this.refrescarEstado()
    } catch (e) {
      this.errorPlantilla = e instanceof ErrorApi ? e.message : 'No se pudo aplicar la plantilla.'
    }
  },

  nombrePlantilla(p) {
    return p ? `${p.tipo_obra} · ${p.materialidad}` : ''
  },

  origen(l) {
    const partes: string[] = []
    if (l.fuentePrecio) partes.push(l.fuentePrecio)
    if (l.origen === 'manual') partes.push('partida del proyecto')
    if (l.factorAplicado !== 1) partes.push(`factor ${factor(l.factorAplicado)}`)
    return partes.join(' · ')
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
