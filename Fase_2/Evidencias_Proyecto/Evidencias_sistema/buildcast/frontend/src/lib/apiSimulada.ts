import type {
  CierreObra, CategoriaPartida, FilaBanco, Partida, PartidaEditada, PartidaNueva, PartidaProyecto,
  PartidaProyectoEditada, PartidaProyectoNueva, PartidasProyecto, PlantillaDetalle, PlantillaNueva,
  PlantillaResumen, PrecioEditado, Proyecto, ProyectoNuevo, RespuestaSesion, Unidad, Usuario, VersionPrecios,
} from '../tipos/api'
import { estadoVersion } from '../tipos/api'
import type {
  Estimacion, EstimacionResumen, LineaEstimacion, OpcionesEstimacion,
} from '../tipos/estimacion'
import { LIMITE_GASTOS_GENERALES, LIMITE_UTILIDAD } from '../tipos/estimacion'
import { CATEGORIAS_BASE, PARTIDAS_BASE } from './catalogoBase'
import { PRECIOS_REFERENCIALES } from './preciosReferenciales'
import { calcularPresupuesto, estadoPartida, precioResuelto, subtotalPartida } from './motorCosto'
import type { LineaEntrada, LineaPresupuesto } from './motorCosto'
import { guardarConfig, leerConfig } from './configuracion'
import type { Configuracion } from './configuracion'
import { MATERIALES, TIPOS_OBRA } from './catalogos'
import { proyectoCambio } from './estimaciones'
import { ErrorApi } from './errores'

/* Datos en memoria para recorrer la plataforma sin API ni usuario real.
   Se activa con VITE_SIMULACION=true. Los cambios persisten en
   localStorage para que crear y editar se comporten como en la app real:
   mismas plantillas, partidas del proyecto y estimaciones guardadas. */

const CLAVE = 'buildcast.simulacion.proyectos'
const CLAVE_BANCO = 'buildcast.simulacion.banco'
const CLAVE_PLANTILLAS = 'buildcast.simulacion.plantillas'
const CLAVE_PARTIDAS = 'buildcast.simulacion.partidas'
const CLAVE_ESTIMACIONES = 'buildcast.simulacion.estimaciones'
const DEMORA = 280 // ms, para que se vean los estados de carga

// Proyectos de ejemplo sin partidas: se arman desde la pantalla de estimación.
const SEMILLA: Proyecto[] = [
  { id: 'p-1', nombre: 'Casa Bravo', comuna: 'Villa Alemana', tipo_obra: 'Vivienda unifamiliar',
    material: 'Albañilería confinada', superficie_m2: 142, pisos: 2, estandar_terminaciones: 'medio' },
  { id: 'p-2', nombre: 'Ampliación Quiroz', comuna: 'Quilpué', tipo_obra: 'Ampliación',
    material: 'Tabiquería de madera', superficie_m2: 48, pisos: 1, estandar_terminaciones: 'economico' },
  { id: 'p-3', nombre: 'Casa Molina', comuna: 'Concón', tipo_obra: 'Vivienda unifamiliar',
    material: 'Hormigón armado', superficie_m2: 196, pisos: 2, estandar_terminaciones: 'alto' },
  { id: 'p-4', nombre: 'Dúplex Los Almendros', comuna: 'Viña del Mar', tipo_obra: 'Edificación habitacional',
    material: 'Albañilería confinada', superficie_m2: 168, pisos: 2, estandar_terminaciones: 'medio',
    estado: 'ejecutada', costo_total: 189100000, plazo_dias: 204 },
  { id: 'p-5', nombre: 'Casa Ibarra', comuna: 'Limache', tipo_obra: 'Vivienda unifamiliar',
    material: 'Estructura metálica', superficie_m2: 110, pisos: 1, estandar_terminaciones: 'medio' },
]

const USUARIO: Usuario = {
  id: 'u-demo', correo: 'demo@ramarquitectura.cl', nombre: 'Usuaria de demostración', rol: 'estimador',
}

function leerJson<T>(clave: string, semilla: () => T): T {
  const crudo = localStorage.getItem(clave)
  if (crudo) {
    try {
      return JSON.parse(crudo) as T
    } catch {
      // Datos corruptos: se vuelve a la semilla.
    }
  }
  const valor = semilla()
  localStorage.setItem(clave, JSON.stringify(valor))
  return valor
}

function escribirJson(clave: string, valor: unknown): void {
  localStorage.setItem(clave, JSON.stringify(valor))
}

const leer = () => leerJson<Proyecto[]>(CLAVE, () => structuredClone(SEMILLA))
const escribir = (proyectos: Proyecto[]) => escribirJson(CLAVE, proyectos)

function esperar<T>(valor: T): Promise<T> {
  return new Promise((resolver) => setTimeout(() => resolver(valor), DEMORA))
}

function nuevoId(prefijo: string): string {
  return `${prefijo}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/* --- Banco de precios ---------------------------------------------------- */

const VERSION_REFERENCIAL = {
  id: 'v-2026-T3-REF',
  version: '2026-T3-REF',
  fuente: 'Referencial de mercado · Región de Valparaíso · no proviene de RAM',
}

interface BancoSimulado {
  partidas: Partida[]
  versiones: VersionPrecios[]
  precios: Record<string, Record<string, PrecioEditado>>  // versionId → partidaId → precio
}

function semillaBanco(): BancoSimulado {
  const partidas: Partida[] = PARTIDAS_BASE.map((p) => ({
    id: `pt-${p.codigo}`,
    categoria_id: p.categoria_id,
    codigo: p.codigo,
    nombre: p.nombre,
    unidad: p.unidad as Unidad,
    es_base: true,
    vigente: true,
  }))

  // Versión inicial con valores referenciales de mercado: la oficina
  // corrige sobre una base en lugar de partir con celdas vacías.
  const versiones: VersionPrecios[] = [{
    ...VERSION_REFERENCIAL,
    trimestre: '2026-T3',
    vigente: true,
    cargado_en: new Date().toISOString(),
    fecha_publicacion: new Date().toISOString(),
  }]

  const precios: Record<string, Record<string, PrecioEditado>> = { 'v-2026-T3-REF': {} }
  partidas.forEach((p) => {
    const referencia = PRECIOS_REFERENCIALES[p.codigo]
    if (!referencia) return
    precios['v-2026-T3-REF'][p.id] = {
      precio_unitario: referencia[0],
      rendimiento_mo: referencia[1],
      fuente: 'Referencial de mercado 2026-T3',
    }
  })

  return { partidas, versiones, precios }
}

function leerBanco(): BancoSimulado {
  const banco = leerJson<BancoSimulado>(CLAVE_BANCO, semillaBanco)
  // Datos guardados antes de fecha_publicacion: la vigente se da por publicada.
  banco.versiones.forEach((v) => {
    if (v.vigente && !v.fecha_publicacion) v.fecha_publicacion = v.cargado_en ?? new Date().toISOString()
    v.estado = estadoVersion(v)
  })
  return banco
}

function tienePrecios(banco: BancoSimulado, partidaId: string): boolean {
  return Object.values(banco.precios).some((porPartida) => partidaId in porPartida)
}
const escribirBanco = (banco: BancoSimulado) => escribirJson(CLAVE_BANCO, banco)

function versionVigente(banco: BancoSimulado): VersionPrecios | undefined {
  return banco.versiones.find((v) => v.vigente)
}

/** Siguiente código libre dentro de la categoría: 04.01, 04.02, … */
function siguienteCodigo(banco: BancoSimulado, categoriaId: number): string {
  const categoria = CATEGORIAS_BASE.find((c) => c.id === categoriaId)
  const usados = banco.partidas
    .filter((p) => p.categoria_id === categoriaId)
    .map((p) => Number(p.codigo.split('.')[1] ?? 0))
  const siguiente = (usados.length ? Math.max(...usados) : 0) + 1
  return `${categoria?.codigo ?? '99'}.${String(siguiente).padStart(2, '0')}`
}

/* --- Plantillas ---------------------------------------------------------- */

interface PlantillaSimulada {
  id: string
  nombre: string
  tipo_obra: string
  materialidad: string
  vigente: boolean
  fecha_actualizacion: string
  partidas: { partida_id: string; cantidad_sugerida: number | null }[]
}

// Las 12 combinaciones, vacías, igual que la migración 005.
function semillaPlantillas(): PlantillaSimulada[] {
  return TIPOS_OBRA.flatMap((tipo) => MATERIALES.map((material) => ({
    id: nuevoId('pl'),
    nombre: `${tipo} · ${material}`,
    tipo_obra: tipo,
    materialidad: material,
    vigente: true,
    fecha_actualizacion: new Date().toISOString(),
    partidas: [],
  })))
}

const leerPlantillas = () => leerJson<PlantillaSimulada[]>(CLAVE_PLANTILLAS, semillaPlantillas)
const escribirPlantillas = (p: PlantillaSimulada[]) => escribirJson(CLAVE_PLANTILLAS, p)

function resumenPlantilla(p: PlantillaSimulada | undefined | null): PlantillaResumen | null {
  if (!p) return null
  const { partidas, ...resto } = p
  return { ...resto, cantidad_partidas: partidas.length }
}

function detallePlantilla(p: PlantillaSimulada): PlantillaDetalle {
  const banco = leerBanco()
  return {
    ...(resumenPlantilla(p) as PlantillaResumen),
    partidas: p.partidas.flatMap((fila, i) => {
      const partida = banco.partidas.find((x) => x.id === fila.partida_id)
      if (!partida) return []
      return [{
        partida_id: partida.id, orden: i + 1, cantidad_sugerida: fila.cantidad_sugerida,
        codigo: partida.codigo, nombre: partida.nombre, unidad: partida.unidad,
        categoria_id: partida.categoria_id, vigente: partida.vigente,
      }]
    }),
  }
}

function plantillaVigente(tipo: string, material: string): PlantillaSimulada | undefined {
  return leerPlantillas().find((p) => p.vigente && p.tipo_obra === tipo && p.materialidad === material)
}

function validarPlantillaUnica(plantillas: PlantillaSimulada[], candidata: PlantillaSimulada): void {
  if (!candidata.vigente) return
  const choca = plantillas.some((p) => p.id !== candidata.id && p.vigente
    && p.tipo_obra === candidata.tipo_obra && p.materialidad === candidata.materialidad)
  if (choca) throw new ErrorApi(409, 'Ya existe una plantilla vigente para ese tipo de obra y materialidad.')
}

/* --- Partidas del proyecto ----------------------------------------------- */

type FilaProyecto = Pick<
  PartidaProyecto,
  'id' | 'partida_id' | 'categoria_id' | 'nombre' | 'unidad' | 'cantidad' | 'precio_unitario_override'
  | 'origen' | 'orden' | 'observacion'
>

interface PartidasSimuladas { plantilla_id: string | null; filas: FilaProyecto[] }

const leerTodasPartidas = () => leerJson<Record<string, PartidasSimuladas>>(CLAVE_PARTIDAS, () => ({}))

function partidasDe(proyectoId: string): PartidasSimuladas {
  return leerTodasPartidas()[proyectoId] ?? { plantilla_id: null, filas: [] }
}

function guardarPartidasDe(proyectoId: string, datos: PartidasSimuladas): void {
  const todas = leerTodasPartidas()
  todas[proyectoId] = datos
  escribirJson(CLAVE_PARTIDAS, todas)
}

/** Completa la fila con categoría, código y precio vigente, como el backend. */
function aRespuesta(proyectoId: string, f: FilaProyecto, banco = leerBanco()): PartidaProyecto & { fuente_banco: string | null } {
  const categoria = CATEGORIAS_BASE.find((c) => c.id === f.categoria_id)
  const version = versionVigente(banco)
  const precio = f.partida_id && version ? banco.precios[version.id]?.[f.partida_id] : undefined
  const precioBanco = precio?.precio_unitario ?? null
  const unitario = precioResuelto(f.precio_unitario_override, precioBanco)
  return {
    ...f,
    proyecto_id: proyectoId,
    codigo: f.partida_id ? banco.partidas.find((p) => p.id === f.partida_id)?.codigo ?? null : null,
    categoria_codigo: categoria?.codigo ?? '',
    categoria_nombre: categoria?.nombre ?? '',
    categoria_orden: categoria?.orden ?? 0,
    precio_banco: precioBanco,
    precio_unitario: unitario,
    subtotal: subtotalPartida(f.cantidad, unitario),
    estado: estadoPartida(f.cantidad, unitario),
    fuente_banco: precio?.fuente ?? null,
  }
}

function listadoPartidas(proyecto: Proyecto): PartidasProyecto {
  const { plantilla_id, filas } = partidasDe(proyecto.id)
  const banco = leerBanco()
  const version = versionVigente(banco)
  return {
    plantilla_aplicada: resumenPlantilla(leerPlantillas().find((p) => p.id === plantilla_id)),
    plantilla_sugerida: resumenPlantilla(plantillaVigente(proyecto.tipo_obra, proyecto.material)),
    version_precios: version ? { id: version.id, version: version.version } : null,
    partidas: [...filas].sort((a, b) => a.orden - b.orden).map((f) => aRespuesta(proyecto.id, f, banco)),
  }
}

function aplicarPlantillaSimulada(proyectoId: string, plantilla: PlantillaSimulada, reemplazar: boolean): void {
  const actual = partidasDe(proyectoId)
  if (actual.filas.length > 0 && !reemplazar) {
    throw new ErrorApi(409, 'El proyecto ya tiene partidas. Confirma si quieres reemplazarlas.')
  }
  const banco = leerBanco()
  // Se copian los valores: cambiar la plantilla después no toca el proyecto.
  const filas: FilaProyecto[] = plantilla.partidas.flatMap((fila) => {
    const partida = banco.partidas.find((p) => p.id === fila.partida_id && p.vigente)
    return partida ? [{
      id: nuevoId('pp'), partida_id: partida.id, categoria_id: partida.categoria_id,
      nombre: partida.nombre, unidad: partida.unidad, cantidad: fila.cantidad_sugerida,
      precio_unitario_override: null, origen: 'plantilla' as const, orden: 0, observacion: null,
    }] : []
  })
  filas.forEach((f, i) => { f.orden = i + 1 })
  guardarPartidasDe(proyectoId, { plantilla_id: plantilla.id, filas })
}

/* --- Estimaciones -------------------------------------------------------- */

/* Se calculan en el navegador con motorCosto.ts y se guardan como en la app
   real: una estimación no cambia si después se editan partidas o precios. */

interface EstimacionGuardada { estimacion: Estimacion; firma: string }

const leerEstimaciones = () => leerJson<Record<string, EstimacionGuardada[]>>(CLAVE_ESTIMACIONES, () => ({}))

/** Solo lo que cambia el costo, igual que firma_partidas del backend. */
function firmaPartidas(filas: FilaProyecto[]): string {
  return JSON.stringify(
    filas.map((f) => [f.id, f.partida_id, f.cantidad, f.precio_unitario_override]).sort(),
  )
}

function aLinea(l: LineaPresupuesto): LineaEstimacion {
  const e = l.entrada
  return {
    id: e.id, codigo: e.codigo, nombre: e.nombre, unidad: e.unidad,
    categoriaCodigo: e.categoria_codigo, categoriaNombre: e.categoria_nombre,
    cantidad: e.cantidad, precioUnitario: l.precioUnitario, subtotal: l.subtotal,
    partidaId: e.partida_id, origen: e.origen, observacion: e.observacion, estado: l.estado,
    precioUnitarioBase: e.precio_banco, precioUnitarioOverride: e.precio_unitario_override,
    fuentePrecio: l.fuentePrecio, factorAplicado: l.factorAplicado, subtotalBase: l.subtotalBase,
  }
}

function estimacionSimulada(proyecto: Proyecto, opciones: OpcionesEstimacion = {}): EstimacionGuardada {
  const { gastos_generales_pct: gg, utilidad_pct: ut } = opciones
  if (gg != null && (gg < 0 || gg > LIMITE_GASTOS_GENERALES)) {
    throw new ErrorApi(422, `Los gastos generales deben estar entre 0 y ${LIMITE_GASTOS_GENERALES} %.`)
  }
  if (ut != null && (ut < 0 || ut > LIMITE_UTILIDAD)) {
    throw new ErrorApi(422, `La utilidad debe estar entre 0 y ${LIMITE_UTILIDAD} %.`)
  }

  const { filas } = partidasDe(proyecto.id)
  if (filas.length === 0) {
    throw new ErrorApi(409, 'El proyecto no tiene partidas. Agrega partidas antes de generar la estimación.')
  }

  const banco = leerBanco()
  const version = versionVigente(banco)
  if (!version) throw new ErrorApi(409, 'No hay una versión de precios vigente. Publica una en el banco de precios.')

  const entradas: LineaEntrada[] = filas.map((f) => aRespuesta(proyecto.id, f, banco))
  const p = calcularPresupuesto(proyecto, entradas, leerConfig(), {
    gastosGeneralesPct: gg, utilidadPct: ut, aplicarFactores: opciones.aplicar_factores ?? false,
  })
  const lineas = p.lineas.map(aLinea)

  const estimacion: Estimacion = {
    id: nuevoId('e'),
    proyectoId: proyecto.id,
    fechaCreacion: new Date().toISOString(),
    versionMotor: 'simulación 2',
    versionPrecios: { id: version.id, version: version.version, fuente: version.fuente ?? null },
    proyecto: {
      comuna: proyecto.comuna,
      tipoObra: proyecto.tipo_obra,
      materialidad: proyecto.material,
      superficieM2: proyecto.superficie_m2,
      numeroPisos: proyecto.pisos,
      estandarTerminaciones: proyecto.estandar_terminaciones,
    },
    capitulos: p.capitulos.map((c) => ({ ...c, lineas: c.lineas.map(aLinea) })),
    costoDirectoBase: p.costoDirectoBase,
    costoDirecto: p.costoDirecto,
    gastosGeneralesPct: p.gastosGeneralesPct,
    gastosGenerales: p.gastosGenerales,
    utilidadPct: p.utilidadPct,
    utilidad: p.utilidad,
    total: p.total,
    costoM2: p.costoM2,
    aplicarFactores: p.factores.aplicar,
    factores: { comuna: p.factores.comuna, pisos: p.factores.pisos, ajuste: p.factores.ajuste },
    completa: p.completa,
    partidasCalculadas: lineas.filter((l) => l.estado === 'calculada').length,
    partidasSinPrecio: p.partidasSinPrecio,
    partidasSinCantidad: p.partidasSinCantidad,
    sinPrecio: lineas.filter((l) => l.estado === 'sin_precio'),
    sinCantidad: lineas.filter((l) => l.estado === 'sin_cantidad'),
  }
  return { estimacion, firma: firmaPartidas(filas) }
}

function aResumen(e: Estimacion): EstimacionResumen {
  const {
    id, proyectoId, fechaCreacion, versionMotor, versionPrecios, costoDirecto, total, costoM2, completa,
    partidasCalculadas, partidasSinPrecio, partidasSinCantidad,
  } = e
  return {
    id, proyectoId, fechaCreacion, versionMotor, versionPrecios, costoDirecto, total, costoM2, completa,
    partidasCalculadas, partidasSinPrecio, partidasSinCantidad,
  }
}

/** Estado y costo de la última estimación, con las mismas reglas del backend. */
function conResumen(proyecto: Proyecto): Proyecto {
  if (proyecto.estado === 'ejecutada') return proyecto
  const [ultima] = leerEstimaciones()[proyecto.id] ?? []
  if (!ultima) return { ...proyecto, estado: 'sin_estimar', costo_total: null, costo_m2: null, ultima_estimacion_id: null }

  const vigente = versionVigente(leerBanco())
  const recalcular = proyectoCambio(ultima.estimacion, proyecto)
    || ultima.firma !== firmaPartidas(partidasDe(proyecto.id).filas)
    || (!!vigente && vigente.id !== ultima.estimacion.versionPrecios.id)

  return {
    ...proyecto,
    estado: recalcular ? 'recalcular' : 'vigente',
    costo_total: ultima.estimacion.total,
    costo_m2: ultima.estimacion.costoM2,
    ultima_estimacion_id: ultima.estimacion.id,
    fecha_estimacion: ultima.estimacion.fechaCreacion,
  }
}

function proyectoSimulado(id: string): Proyecto {
  const proyecto = leer().find((p) => p.id === id)
  if (!proyecto) throw new ErrorApi(404, 'El proyecto no existe.')
  return proyecto
}

function filaDe(proyectoId: string, id: string): { datos: PartidasSimuladas; fila: FilaProyecto } {
  const datos = partidasDe(proyectoId)
  const fila = datos.filas.find((f) => f.id === id)
  if (!fila) throw new ErrorApi(404, 'Partida no encontrada')
  return { datos, fila }
}

/** Borra los datos de demostración y vuelve a la semilla. */
export function reiniciarSimulacion(): void {
  [CLAVE, CLAVE_BANCO, CLAVE_PLANTILLAS, CLAVE_PARTIDAS, CLAVE_ESTIMACIONES].forEach((c) => localStorage.removeItem(c))
}

export const apiSimulada = {
  iniciarSesion: (correo: string): Promise<RespuestaSesion> =>
    esperar({
      access_token: 'demostracion',
      expires_in: 60 * 60 * 8,
      user: { ...USUARIO, correo: correo || USUARIO.correo },
    }),

  registrar: (correo: string): Promise<RespuestaSesion> =>
    esperar({ access_token: 'demostracion', expires_in: 60 * 60 * 8, user: { ...USUARIO, correo } }),

  reenviarConfirmacion: (): Promise<{ mensaje: string }> =>
    esperar({ mensaje: 'En modo demostración no se envían correos.' }),

  yo: (): Promise<Usuario> => esperar(USUARIO),

  listarProyectos: (): Promise<Proyecto[]> => esperar(leer().map(conResumen)),

  obtenerProyecto: async (id: string): Promise<Proyecto> => esperar(conResumen(proyectoSimulado(id))),

  crearProyecto: (datos: ProyectoNuevo): Promise<Proyecto> => {
    const proyectos = leer()
    const nuevo: Proyecto = {
      ...datos,
      id: nuevoId('p'),
      plazo_dias: null,
      creado_en: new Date().toISOString(),
    }
    proyectos.push(nuevo)
    escribir(proyectos)
    // Partidas iniciales desde la plantilla, si existe una vigente.
    const plantilla = plantillaVigente(nuevo.tipo_obra, nuevo.material)
    if (plantilla) aplicarPlantillaSimulada(nuevo.id, plantilla, false)
    return esperar(conResumen(nuevo))
  },

  actualizarProyecto: async (id: string, datos: ProyectoNuevo): Promise<Proyecto> => {
    const proyectos = leer()
    const i = proyectos.findIndex((p) => p.id === id)
    if (i === -1) throw new ErrorApi(404, 'El proyecto no existe.')
    proyectos[i] = { ...proyectos[i], ...datos, actualizado_en: new Date().toISOString() }
    escribir(proyectos)
    return esperar(conResumen(proyectos[i]))
  },

  registrarCierreObra: async (proyectoId: string, datos: CierreObra): Promise<CierreObra> => {
    const proyectos = leer()
    const i = proyectos.findIndex((p) => p.id === proyectoId)
    if (i === -1) throw new ErrorApi(404, 'El proyecto no existe.')
    proyectos[i] = { ...conResumen(proyectos[i]), estado: 'ejecutada' }
    escribir(proyectos)
    localStorage.setItem(`buildcast.simulacion.cierre.${proyectoId}`, JSON.stringify(datos))
    return esperar(datos)
  },

  // --- Banco ----------------------------------------------------------

  listarCategorias: (): Promise<CategoriaPartida[]> => esperar(CATEGORIAS_BASE),

  listarVersiones: (): Promise<VersionPrecios[]> => esperar(leerBanco().versiones),

  crearVersion: (version: string, copiarDe?: string): Promise<VersionPrecios> => {
    const banco = leerBanco()
    const nueva: VersionPrecios = {
      id: `v-${version}`,
      version,
      trimestre: version,
      fuente: copiarDe ? `Copiada de ${copiarDe}` : null,
      vigente: false,
      cargado_en: new Date().toISOString(),
      // Siempre nace borrador, aunque copie una publicada.
      fecha_publicacion: null,
      estado: 'borrador',
    }
    banco.versiones.push(nueva)
    banco.precios[nueva.id] = copiarDe ? { ...(banco.precios[copiarDe] ?? {}) } : {}
    escribirBanco(banco)
    return esperar(nueva)
  },

  publicarVersion: (id: string): Promise<VersionPrecios> => {
    const banco = leerBanco()
    // La primera publicación fija la fecha; volver a publicar una histórica no la cambia.
    banco.versiones = banco.versiones.map((v) => {
      const vigente = v.id === id
      const fecha_publicacion = v.fecha_publicacion ?? (vigente ? new Date().toISOString() : null)
      return { ...v, vigente, fecha_publicacion, estado: estadoVersion({ vigente, fecha_publicacion }) }
    })
    escribirBanco(banco)
    return esperar(banco.versiones.find((v) => v.id === id) as VersionPrecios)
  },

  listarBanco: (versionId?: string): Promise<FilaBanco[]> => {
    const banco = leerBanco()
    const version = versionId ?? versionVigente(banco)?.id ?? ''
    const precios = banco.precios[version] ?? {}
    const filas: FilaBanco[] = banco.partidas.map((p) => ({
      ...p,
      precio_unitario: precios[p.id]?.precio_unitario ?? null,
      rendimiento_mo: precios[p.id]?.rendimiento_mo ?? null,
      fuente: precios[p.id]?.fuente ?? null,
      tiene_precios: tienePrecios(banco, p.id),
    }))
    return esperar(filas)
  },

  crearPartida: (datos: PartidaNueva): Promise<Partida> => {
    const banco = leerBanco()
    const nueva: Partida = {
      id: nuevoId('pt'),
      categoria_id: datos.categoria_id,
      codigo: siguienteCodigo(banco, datos.categoria_id),
      nombre: datos.nombre,
      unidad: datos.unidad,
      es_base: false,
      vigente: true,
    }
    banco.partidas.push(nueva)
    escribirBanco(banco)
    return esperar(nueva)
  },

  editarPartida: async (id: string, datos: PartidaEditada): Promise<Partida> => {
    const banco = leerBanco()
    const i = banco.partidas.findIndex((p) => p.id === id)
    if (i === -1) throw new ErrorApi(404, 'La partida no existe.')
    if (!banco.partidas[i].vigente) throw new ErrorApi(409, 'La partida está dada de baja: no se puede editar.')
    if (datos.unidad && datos.unidad !== banco.partidas[i].unidad && tienePrecios(banco, id)) {
      throw new ErrorApi(409, 'La partida ya tiene precios cargados en el banco, expresados en su unidad actual. Para usar otra unidad, da de baja esta partida y crea una nueva con la unidad correcta.')
    }
    // El código se conserva aunque cambie la categoría.
    banco.partidas[i] = { ...banco.partidas[i], ...datos }
    escribirBanco(banco)
    return esperar(banco.partidas[i])
  },

  darDeBajaPartida: async (id: string): Promise<Partida> => {
    const banco = leerBanco()
    const i = banco.partidas.findIndex((p) => p.id === id)
    if (i === -1) throw new ErrorApi(404, 'La partida no existe.')
    if (banco.partidas[i].es_base) throw new ErrorApi(409, 'Las partidas del catálogo base no se pueden dar de baja.')
    banco.partidas[i] = { ...banco.partidas[i], vigente: false }
    escribirBanco(banco)
    return esperar(banco.partidas[i])
  },

  guardarPrecio: async (versionId: string, partidaId: string, datos: PrecioEditado): Promise<FilaBanco> => {
    const banco = leerBanco()
    if (banco.versiones.find((v) => v.id === versionId)?.fecha_publicacion) {
      throw new ErrorApi(409, 'Una versión publicada no se puede modificar. Para cambiar precios, crea una nueva versión copiando la vigente, edítala y publícala.')
    }
    const partida = banco.partidas.find((p) => p.id === partidaId)
    if (!partida) throw new ErrorApi(404, 'La partida no existe.')
    // Un valor editado por la oficina deja de ser una referencia de mercado.
    banco.precios[versionId] = {
      ...(banco.precios[versionId] ?? {}),
      [partidaId]: { ...datos, fuente: datos.fuente ?? 'Editado por la oficina' },
    }
    escribirBanco(banco)
    return esperar({ ...partida, ...datos })
  },

  // --- Partidas del proyecto -------------------------------------------

  listarPartidasProyecto: async (proyectoId: string): Promise<PartidasProyecto> =>
    esperar(listadoPartidas(proyectoSimulado(proyectoId))),

  crearPartidaProyecto: async (proyectoId: string, datos: PartidaProyectoNueva): Promise<PartidaProyecto> => {
    proyectoSimulado(proyectoId)
    const actual = partidasDe(proyectoId)
    const orden = Math.max(0, ...actual.filas.map((f) => f.orden)) + 1
    let fila: FilaProyecto

    if (datos.origen === 'catalogo') {
      const partida = leerBanco().partidas.find((p) => p.id === datos.partida_id && p.vigente)
      if (!partida) throw new ErrorApi(422, 'La partida del catálogo no existe o está dada de baja.')
      fila = {
        id: nuevoId('pp'), partida_id: partida.id, categoria_id: partida.categoria_id,
        nombre: datos.nombre?.trim() || partida.nombre, unidad: partida.unidad,
        cantidad: datos.cantidad ?? null, precio_unitario_override: datos.precio_unitario_override ?? null,
        origen: 'catalogo', orden, observacion: datos.observacion ?? null,
      }
    } else {
      if (!datos.categoria_id || !datos.nombre?.trim() || !datos.unidad?.trim()
        || datos.cantidad == null || datos.precio_unitario_override == null) {
        throw new ErrorApi(422, 'Completa categoría, nombre, unidad, cantidad y precio.')
      }
      fila = {
        id: nuevoId('pp'), partida_id: null, categoria_id: datos.categoria_id,
        nombre: datos.nombre.trim(), unidad: datos.unidad.trim(), cantidad: datos.cantidad,
        precio_unitario_override: datos.precio_unitario_override, origen: 'manual', orden,
        observacion: datos.observacion ?? null,
      }
    }
    guardarPartidasDe(proyectoId, { ...actual, filas: [...actual.filas, fila] })
    return esperar(aRespuesta(proyectoId, fila))
  },

  editarPartidaProyecto: async (proyectoId: string, id: string, datos: PartidaProyectoEditada): Promise<PartidaProyecto> => {
    const { datos: actual, fila } = filaDe(proyectoId, id)
    if (fila.partida_id && ((datos.unidad != null && datos.unidad !== fila.unidad)
      || (datos.categoria_id != null && datos.categoria_id !== fila.categoria_id))) {
      throw new ErrorApi(422, 'La unidad y la categoría de una partida del catálogo no se cambian en el proyecto.')
    }
    if (datos.nombre !== undefined && !datos.nombre?.trim()) throw new ErrorApi(422, 'Escribe el nombre de la partida.')
    if ((datos.cantidad ?? 0) < 0 || (datos.precio_unitario_override ?? 0) < 0) {
      throw new ErrorApi(422, 'La cantidad y el precio no pueden ser negativos.')
    }
    Object.assign(fila, datos)
    guardarPartidasDe(proyectoId, actual)
    return esperar(aRespuesta(proyectoId, fila))
  },

  eliminarPartidaProyecto: async (proyectoId: string, id: string): Promise<null> => {
    const { datos } = filaDe(proyectoId, id)
    guardarPartidasDe(proyectoId, { ...datos, filas: datos.filas.filter((f) => f.id !== id) })
    return esperar(null)
  },

  ordenarPartidasProyecto: async (proyectoId: string, ids: string[]): Promise<PartidaProyecto[]> => {
    const datos = partidasDe(proyectoId)
    if ([...ids].sort().join() !== datos.filas.map((f) => f.id).sort().join()) {
      throw new ErrorApi(422, 'El nuevo orden debe incluir todas las partidas del proyecto.')
    }
    datos.filas.forEach((f) => { f.orden = ids.indexOf(f.id) + 1 })
    guardarPartidasDe(proyectoId, datos)
    return esperar(listadoPartidas(proyectoSimulado(proyectoId)).partidas)
  },

  aplicarPlantilla: async (proyectoId: string, plantillaId: string | null, reemplazar: boolean): Promise<PartidasProyecto> => {
    const proyecto = proyectoSimulado(proyectoId)
    const plantilla = plantillaId
      ? leerPlantillas().find((p) => p.id === plantillaId && p.vigente)
      : plantillaVigente(proyecto.tipo_obra, proyecto.material)
    if (!plantilla) throw new ErrorApi(404, 'No hay una plantilla vigente para aplicar.')
    aplicarPlantillaSimulada(proyectoId, plantilla, reemplazar)
    return esperar(listadoPartidas(proyecto))
  },

  // --- Plantillas --------------------------------------------------------

  listarPlantillas: (): Promise<PlantillaResumen[]> =>
    esperar(leerPlantillas().map((p) => resumenPlantilla(p) as PlantillaResumen)),

  obtenerPlantilla: async (id: string): Promise<PlantillaDetalle> => {
    const plantilla = leerPlantillas().find((p) => p.id === id)
    if (!plantilla) throw new ErrorApi(404, 'La plantilla no existe.')
    return esperar(detallePlantilla(plantilla))
  },

  crearPlantilla: async (datos: PlantillaNueva): Promise<PlantillaDetalle> => {
    const plantillas = leerPlantillas()
    const nueva: PlantillaSimulada = {
      id: nuevoId('pl'), nombre: datos.nombre.trim(), tipo_obra: datos.tipo_obra,
      materialidad: datos.materialidad, vigente: datos.vigente ?? true,
      fecha_actualizacion: new Date().toISOString(), partidas: [],
    }
    validarPlantillaUnica(plantillas, nueva)
    escribirPlantillas([...plantillas, nueva])
    return esperar(detallePlantilla(nueva))
  },

  editarPlantilla: async (id: string, datos: Partial<PlantillaNueva>): Promise<PlantillaDetalle> => {
    const plantillas = leerPlantillas()
    const i = plantillas.findIndex((p) => p.id === id)
    if (i === -1) throw new ErrorApi(404, 'La plantilla no existe.')
    const editada = { ...plantillas[i], ...datos, fecha_actualizacion: new Date().toISOString() }
    validarPlantillaUnica(plantillas, editada)
    plantillas[i] = editada
    escribirPlantillas(plantillas)
    return esperar(detallePlantilla(editada))
  },

  guardarPartidasPlantilla: async (
    id: string,
    partidas: { partida_id: string; cantidad_sugerida: number | null }[],
  ): Promise<PlantillaDetalle> => {
    const plantillas = leerPlantillas()
    const i = plantillas.findIndex((p) => p.id === id)
    if (i === -1) throw new ErrorApi(404, 'La plantilla no existe.')
    if (new Set(partidas.map((p) => p.partida_id)).size !== partidas.length) {
      throw new ErrorApi(409, 'Una partida está repetida en la plantilla.')
    }
    plantillas[i] = { ...plantillas[i], partidas, fecha_actualizacion: new Date().toISOString() }
    escribirPlantillas(plantillas)
    return esperar(detallePlantilla(plantillas[i]))
  },

  // --- Estimaciones --------------------------------------------------------

  crearEstimacion: async (proyectoId: string, opciones: OpcionesEstimacion = {}): Promise<Estimacion> => {
    const guardada = estimacionSimulada(proyectoSimulado(proyectoId), opciones)
    const todas = leerEstimaciones()
    todas[proyectoId] = [guardada, ...(todas[proyectoId] ?? [])]
    escribirJson(CLAVE_ESTIMACIONES, todas)
    return esperar(guardada.estimacion)
  },

  listarEstimaciones: async (proyectoId: string): Promise<EstimacionResumen[]> =>
    esperar((leerEstimaciones()[proyectoId] ?? []).map((g) => aResumen(g.estimacion))),

  obtenerEstimacion: async (proyectoId: string, estimacionId: string): Promise<Estimacion> => {
    const guardada = (leerEstimaciones()[proyectoId] ?? []).find((g) => g.estimacion.id === estimacionId)
    if (!guardada) throw new ErrorApi(404, 'Estimación no encontrada')
    return esperar(guardada.estimacion)
  },

  obtenerConfiguracion: (): Promise<Configuracion> => esperar(leerConfig()),

  guardarConfiguracion: (configuracion: Configuracion): Promise<Configuracion> => {
    guardarConfig(configuracion)
    return esperar(leerConfig())
  },
}
