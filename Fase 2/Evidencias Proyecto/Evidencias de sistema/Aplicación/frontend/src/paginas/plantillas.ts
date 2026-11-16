import Alpine from 'alpinejs'
import { api, ErrorApi } from '../lib/api'
import { MENSAJE_GUARDAR_PLANTILLA, resolverGuardado } from '../lib/errores'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir } from '../lib/sesion'
import { confirmar } from '../lib/confirmar'
import { pesos } from '../lib/formato'
import { MATERIALES, TIPOS_OBRA } from '../lib/catalogos'
import type {
  CategoriaPartida, FilaBanco, PartidaPlantilla, PlantillaDetalle, PlantillaNueva, PlantillaResumen,
} from '../tipos/api'

type FilaPlantilla = Omit<PartidaPlantilla, 'orden'>

interface PantallaPlantillas {
  plantillas: PlantillaResumen[]
  categorias: CategoriaPartida[]
  catalogo: FilaBanco[]
  seleccionada: PlantillaDetalle | null
  datos: PlantillaNueva & { vigente: boolean }
  lista: FilaPlantilla[]
  cambios: boolean
  busqueda: string
  cargando: boolean
  /** Id de la plantilla que se está abriendo: da respuesta inmediata al pulsar «Editar». */
  abriendo: string
  guardando: boolean
  error: string
  mensaje: string
  formNueva: boolean
  nueva: PlantillaNueva
  errorNueva: string
  tipos: string[]
  materiales: string[]
  pesos: typeof pesos

  get ordenadas(): PlantillaResumen[]
  get resultados(): FilaBanco[]

  cargar(): Promise<void>
  abrir(p: PlantillaResumen): Promise<void>
  mostrar(p: PlantillaDetalle): void
  volver(): Promise<void>
  guardarDatos(): Promise<void>
  agregar(f: FilaBanco): void
  quitar(i: number): void
  mover(i: number, paso: number): void
  cambiarCantidad(fila: FilaPlantilla, valor: string): void
  guardarPartidas(): Promise<void>
  abrirNueva(): void
  crear(): Promise<void>
  nombreCategoria(id: number): string
  salir(): void
}

const mensajeDe = (e: unknown, porDefecto: string) => (e instanceof ErrorApi ? e.message : porDefecto)

// El aviso queda arriba de los botones de guardar.
const avisar = () => window.scrollTo({ top: 0, behavior: 'smooth' })

Alpine.data('plantillas', (): PantallaPlantillas => ({
  plantillas: [],
  categorias: [],
  catalogo: [],
  seleccionada: null,
  datos: { nombre: '', tipo_obra: TIPOS_OBRA[0], materialidad: MATERIALES[0], vigente: true },
  lista: [],
  cambios: false,
  busqueda: '',
  cargando: true,
  abriendo: '',
  guardando: false,
  error: '',
  mensaje: '',
  formNueva: false,
  nueva: { nombre: '', tipo_obra: TIPOS_OBRA[0], materialidad: MATERIALES[0] },
  errorNueva: '',
  tipos: TIPOS_OBRA,
  materiales: MATERIALES,
  pesos,

  // Mismo orden que los formularios de proyecto: tipo de obra y luego materialidad.
  get ordenadas() {
    const posicion = (lista: string[], valor: string) => {
      const i = lista.indexOf(valor)
      return i === -1 ? lista.length : i
    }
    return [...this.plantillas].sort((a, b) =>
      posicion(TIPOS_OBRA, a.tipo_obra) - posicion(TIPOS_OBRA, b.tipo_obra)
      || posicion(MATERIALES, a.materialidad) - posicion(MATERIALES, b.materialidad)
      || a.nombre.localeCompare(b.nombre))
  },

  get resultados() {
    const texto = this.busqueda.trim().toLowerCase()
    const incluidas = new Set(this.lista.map((f) => f.partida_id))
    return this.catalogo
      .filter((f) => f.vigente && !incluidas.has(f.id))
      .filter((f) => !texto || f.nombre.toLowerCase().includes(texto) || f.codigo.includes(texto))
      .slice(0, 40)
  },

  async cargar() {
    this.cargando = true
    this.error = ''
    try {
      const [plantillas, categorias] = await Promise.all([api.listarPlantillas(), api.listarCategorias()])
      this.plantillas = plantillas
      this.categorias = categorias
    } catch (e) {
      this.error = mensajeDe(e, 'No se pudieron cargar las plantillas.')
    } finally {
      this.cargando = false
    }
  },

  async abrir(p) {
    if (this.abriendo) return
    this.error = ''
    this.mensaje = ''
    this.abriendo = p.id
    try {
      const [detalle, catalogo] = await Promise.all([
        api.obtenerPlantilla(p.id),
        this.catalogo.length ? Promise.resolve(this.catalogo) : api.listarBanco(),
      ])
      this.catalogo = catalogo
      this.mostrar(detalle)
    } catch (e) {
      this.error = mensajeDe(e, 'No se pudo abrir la plantilla.')
    } finally {
      this.abriendo = ''
    }
  },

  mostrar(p) {
    this.seleccionada = p
    this.datos = { nombre: p.nombre, tipo_obra: p.tipo_obra, materialidad: p.materialidad, vigente: p.vigente }
    this.lista = p.partidas.map(({ orden: _orden, ...fila }) => fila)
    this.cambios = false
    this.busqueda = ''
  },

  async volver() {
    if (this.cambios) {
      const salirIgual = await confirmar({
        rotulo: 'Plantillas', titulo: 'Cambios sin guardar',
        mensaje: 'Hay cambios sin guardar en las partidas. ¿Salir igual?',
        confirmar: 'Salir sin guardar', cancelar: 'Seguir editando',
      })
      if (!salirIgual) return
    }
    this.seleccionada = null
    void this.cargar()
  },

  async guardarDatos() {
    if (!this.seleccionada) return
    // Evita el doble envío.
    if (this.guardando) return
    if (!this.datos.nombre.trim()) {
      this.error = 'Escribe el nombre de la plantilla.'
      avisar()
      return
    }
    this.guardando = true
    this.error = ''
    this.mensaje = ''
    let detalle: PlantillaDetalle | undefined
    const id = this.seleccionada.id
    const nombre = this.datos.nombre.trim()
    const resultado = await resolverGuardado(
      async () => { detalle = await api.editarPlantilla(id, { ...this.datos, nombre }) },
      'Datos de la plantilla guardados.',
    )
    this.guardando = false

    // Si falla, el formulario queda como estaba.
    if (!resultado.ok || !detalle) {
      this.error = resultado.ok ? MENSAJE_GUARDAR_PLANTILLA : resultado.error
      avisar()
      return
    }
    // Conserva las partidas que se estén editando.
    const lista = this.lista
    const cambios = this.cambios
    this.mostrar(detalle)
    if (cambios) {
      this.lista = lista
      this.cambios = true
    }
    this.mensaje = resultado.mensaje
    avisar()
  },

  agregar(f) {
    this.lista = [...this.lista, {
      partida_id: f.id, codigo: f.codigo, nombre: f.nombre, unidad: f.unidad,
      categoria_id: f.categoria_id, vigente: f.vigente, cantidad_sugerida: null,
    }]
    this.cambios = true
  },

  quitar(i) {
    this.lista = this.lista.filter((_, j) => j !== i)
    this.cambios = true
  },

  mover(i, paso) {
    const j = i + paso
    if (j < 0 || j >= this.lista.length) return
    const lista = [...this.lista]
    ;[lista[i], lista[j]] = [lista[j], lista[i]]
    this.lista = lista
    this.cambios = true
  },

  // Vacío = sin cantidad sugerida: se define en cada proyecto.
  cambiarCantidad(fila, valor) {
    const numero = valor.trim() === '' ? null : Number(valor)
    if (numero != null && (!Number.isFinite(numero) || numero < 0)) {
      this.error = 'La cantidad sugerida debe ser un número mayor o igual a 0.'
      return
    }
    fila.cantidad_sugerida = numero
    this.cambios = true
  },

  async guardarPartidas() {
    if (!this.seleccionada || this.guardando) return
    this.guardando = true
    this.error = ''
    this.mensaje = ''
    let detalle: PlantillaDetalle | undefined
    const id = this.seleccionada.id
    const partidas = this.lista.map((f) => ({ partida_id: f.partida_id, cantidad_sugerida: f.cantidad_sugerida }))
    const resultado = await resolverGuardado(
      async () => { detalle = await api.guardarPartidasPlantilla(id, partidas) },
      'Partidas guardadas. Los proyectos ya creados no cambian.',
    )
    this.guardando = false

    // Si falla, se conservan los cambios pendientes.
    if (!resultado.ok || !detalle) {
      this.error = resultado.ok ? MENSAJE_GUARDAR_PLANTILLA : resultado.error
      avisar()
      return
    }
    this.mostrar(detalle)
    this.mensaje = resultado.mensaje
    avisar()
  },

  abrirNueva() {
    this.nueva = { nombre: '', tipo_obra: TIPOS_OBRA[0], materialidad: MATERIALES[0] }
    this.errorNueva = ''
    this.formNueva = true
  },

  async crear() {
    if (this.guardando) return
    const nombre = this.nueva.nombre.trim() || `${this.nueva.tipo_obra} · ${this.nueva.materialidad}`
    this.guardando = true
    this.errorNueva = ''
    let creada: PlantillaDetalle | undefined
    const resultado = await resolverGuardado(
      async () => { creada = await api.crearPlantilla({ ...this.nueva, nombre }) },
      'Plantilla creada.',
    )

    if (!resultado.ok || !creada) {
      this.guardando = false
      this.errorNueva = resultado.ok ? MENSAJE_GUARDAR_PLANTILLA : resultado.error
      return
    }
    try {
      this.catalogo = this.catalogo.length ? this.catalogo : await api.listarBanco()
    } catch (e) {
      // La plantilla ya existe: se abre igual.
      this.error = mensajeDe(e, 'No se pudo cargar el catálogo de partidas.')
    }
    this.guardando = false
    this.formNueva = false
    this.mensaje = ''
    this.mostrar(creada)
  },

  nombreCategoria(id) {
    return this.categorias.find((c) => c.id === id)?.nombre ?? ''
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
