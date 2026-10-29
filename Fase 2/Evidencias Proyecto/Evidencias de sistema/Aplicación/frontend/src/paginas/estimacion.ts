import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { exigirSesion, salir } from '../lib/sesion'
import { pesos, numero, fecha, factor, leerPrecioEscrito, precioUnitario } from '../lib/formato'
import { ESTANDARES } from '../lib/catalogos'
import { CONFIGURACION_BASE } from '../lib/configuracion'
import { conPlazo, proyectoCambio, ultimaEstimacion } from '../lib/estimaciones'
import type { EstimacionConPlazo } from '../lib/estimaciones'
import { LIMITE_GASTOS_GENERALES, LIMITE_UTILIDAD } from '../tipos/estimacion'
import type { Estimacion, LineaEstimacion } from '../tipos/estimacion'
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

interface PantallaEstimacion {
  proyecto: Proyecto | null
  presupuesto: EstimacionConPlazo | null
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
  pestana: 'presupuesto' | 'cronograma' | 'transparencia'
  cargando: boolean
  guardando: boolean
  editando: string
  nombreEditando: string
  error: string
  errorCalculo: string
  errorPartidas: string

  // Agregar partida
  modalAgregar: boolean
  modoAgregar: 'catalogo' | 'manual'
  catalogo: FilaBanco[]
  busqueda: string
  cantidadCatalogo: number | null
  manual: PartidaManual
  errorAgregar: string
  avisoAgregar: string
  unidades: string[]

  // Plantilla
  modalPlantilla: boolean
  plantillas: PlantillaResumen[]
  plantillaElegida: string
  confirmaReemplazo: boolean
  errorPlantilla: string

  pesos: typeof pesos
  numero: typeof numero
  fecha: typeof fecha
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
  get textoAplicar(): string
  get tolerancia(): number
  get etapas(): { nombre: string; desde: number; hasta: number; dias: number }[]
  get enlaceDocumento(): string
  get resultadosCatalogo(): FilaBanco[]
  get plantillaSeleccionada(): PlantillaResumen | undefined

  iniciar(): Promise<void>
  cargarPartidas(): Promise<void>
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
  editando: '',
  nombreEditando: '',
  error: '',
  errorCalculo: '',
  errorPartidas: '',

  modalAgregar: false,
  modoAgregar: 'catalogo',
  catalogo: [],
  busqueda: '',
  cantidadCatalogo: null,
  manual: manualVacia(),
  errorAgregar: '',
  avisoAgregar: '',
  unidades: UNIDADES,

  modalPlantilla: false,
  plantillas: [],
  plantillaElegida: '',
  confirmaReemplazo: false,
  errorPlantilla: '',

  pesos,
  numero,
  fecha,
  factor,
  precioUnitario,

  // Datos con que se calculó, no los actuales del proyecto.
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
    if (this.guardando || this.errorAjustes || this.partidas.length === 0) return false
    if (!this.presupuesto) return true
    return this.ajustesCambiaron || this.proyecto?.estado === 'recalcular' || this.datosCambiaron || this.versionCambio
  },

  get textoAplicar() {
    if (this.guardando) return 'Calculando…'
    if (!this.presupuesto) return 'Generar estimación'
    return this.ajustesCambiaron ? 'Aplicar cambios' : 'Recalcular'
  },

  get tolerancia() {
    if (!this.presupuesto) return 0
    return Math.round(((this.presupuesto.plazoMax - this.presupuesto.plazoDias) / this.presupuesto.plazoDias) * 100)
  },

  get etapas() {
    if (!this.presupuesto) return []
    const total = this.presupuesto.costoDirecto
    let acumulado = 0

    return ETAPAS.map((etapa) => {
      const peso = this.presupuesto!.capitulos
        .filter((c) => etapa.capitulos.includes(c.codigo))
        .reduce((suma, c) => suma + c.subtotal, 0) / (total || 1)

      const dias = Math.round(this.presupuesto!.plazoDias * peso)
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

  async iniciar() {
    const id = new URLSearchParams(window.location.search).get('id')
    if (!id) {
      this.error = 'No se indicó el proyecto.'
      this.cargando = false
      return
    }

    try {
      const [proyecto, versiones, categorias, guardada] = await Promise.all([
        api.obtenerProyecto(id),
        api.listarVersiones(),
        api.listarCategorias(),
        ultimaEstimacion(id),
      ])
      this.proyecto = proyecto
      this.versionVigenteId = versiones.find((v) => v.vigente)?.id ?? null
      this.categorias = categorias
      await this.cargarPartidas()

      // Recargar muestra la guardada; sin estimación no se calcula sola.
      if (guardada) {
        this.mostrar(guardada)
      } else {
        const config = await api.obtenerConfiguracion().catch(() => CONFIGURACION_BASE)
        this.gg = config.gastosGeneralesPct
        this.utilidad = config.utilidadPct
      }
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo cargar la estimación.'
    } finally {
      this.cargando = false
    }
  },

  async cargarPartidas() {
    if (!this.proyecto) return
    const datos = await api.listarPartidasProyecto(this.proyecto.id)
    this.partidas = datos.partidas
    this.plantillaAplicada = datos.plantilla_aplicada
    this.plantillaSugerida = datos.plantilla_sugerida
  },

  // El backend decide si la estimación quedó desactualizada.
  async refrescarEstado() {
    if (!this.proyecto) return
    try {
      this.proyecto = await api.obtenerProyecto(this.proyecto.id)
    } catch {
      // Solo informativo: la tabla ya quedó guardada.
    }
  },

  mostrar(estimacion) {
    this.presupuesto = conPlazo(estimacion)
    this.gg = estimacion.gastosGeneralesPct
    this.utilidad = estimacion.utilidadPct
    this.aplicarFactores = estimacion.aplicarFactores
  },

  async aplicar() {
    if (!this.proyecto || !this.puedeAplicar) return
    this.guardando = true
    this.errorCalculo = ''
    try {
      this.mostrar(await api.crearEstimacion(this.proyecto.id, {
        gastos_generales_pct: this.gg,
        utilidad_pct: this.utilidad,
        aplicar_factores: this.aplicarFactores,
      }))
      await this.refrescarEstado()
    } catch (e) {
      // Se conservan los valores editados para corregir y reintentar.
      this.errorCalculo = e instanceof ErrorApi ? e.message : 'No se pudo calcular la estimación.'
    } finally {
      this.guardando = false
    }
  },

  // --- Edición de partidas ---------------------------------------------------

  async editar(p, cambios) {
    if (!this.proyecto) return
    this.editando = p.id
    this.errorPartidas = ''
    try {
      const actualizada = await api.editarPartidaProyecto(this.proyecto.id, p.id, cambios)
      this.partidas = this.partidas.map((x) => (x.id === p.id ? actualizada : x))
      await this.refrescarEstado()
    } catch (e) {
      this.errorPartidas = e instanceof ErrorApi ? e.message : 'No se pudo guardar la partida.'
      // Vuelve a mostrar lo guardado.
      this.partidas = [...this.partidas]
    } finally {
      this.editando = ''
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
    if (!window.confirm(`¿Quitar «${p.nombre}» del presupuesto de este proyecto?`)) return
    this.errorPartidas = ''
    try {
      await api.eliminarPartidaProyecto(this.proyecto.id, p.id)
      this.partidas = this.partidas.filter((x) => x.id !== p.id)
      await this.refrescarEstado()
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
    this.busqueda = ''
    this.cantidadCatalogo = null
    this.manual = manualVacia(this.categorias[0]?.id)
    if (this.catalogo.length === 0) {
      try {
        this.catalogo = await api.listarBanco()
      } catch (e) {
        this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo cargar el catálogo.'
      }
    }
  },

  async agregarDelCatalogo(f) {
    if (!this.proyecto) return
    this.errorAgregar = ''
    const cantidad = this.cantidadCatalogo
    if (cantidad != null && (!Number.isFinite(cantidad) || cantidad < 0)) {
      this.errorAgregar = 'La cantidad debe ser un número mayor o igual a 0.'
      return
    }
    try {
      const nueva = await api.crearPartidaProyecto(this.proyecto.id, {
        origen: 'catalogo', partida_id: f.id, cantidad: cantidad ?? null,
      })
      this.partidas = [...this.partidas, nueva]
      this.avisoAgregar = `Agregada: ${nueva.nombre}.`
      this.cantidadCatalogo = null
      await this.refrescarEstado()
    } catch (e) {
      this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo agregar la partida.'
    }
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
      await this.refrescarEstado()
    } catch (e) {
      this.errorAgregar = e instanceof ErrorApi ? e.message : 'No se pudo agregar la partida.'
    }
  },

  // --- Plantilla ---------------------------------------------------------------

  async abrirPlantilla() {
    this.modalPlantilla = true
    this.errorPlantilla = ''
    this.confirmaReemplazo = false
    try {
      this.plantillas = (await api.listarPlantillas()).filter((p) => p.vigente)
      this.plantillaElegida = this.plantillaSugerida?.id ?? this.plantillaAplicada?.id ?? this.plantillas[0]?.id ?? ''
    } catch (e) {
      this.errorPlantilla = e instanceof ErrorApi ? e.message : 'No se pudieron cargar las plantillas.'
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
      await this.refrescarEstado()
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
}
