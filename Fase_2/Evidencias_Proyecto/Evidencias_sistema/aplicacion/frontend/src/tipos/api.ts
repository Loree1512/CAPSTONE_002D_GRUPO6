/* Contrato de la API de BuildCast.
   Los nombres siguen los endpoints en español expuestos en /docs. */

export type EstandarTerminaciones = 'economico' | 'medio' | 'alto'
export type EstadoProyecto = 'sin_estimar' | 'vigente' | 'recalcular' | 'ejecutada'

/** id + correo vienen de auth.users (GET /autenticacion/yo).
 *  nombre/rol quedan undefined hasta que exista la tabla perfiles. */
export interface Usuario {
  id: string
  correo: string
  nombre?: string
  rol?: string
}

/** Respuesta real de POST /autenticacion/iniciar-sesion (RespuestaToken). */
export interface RespuestaSesion {
  access_token: string
  refresh_token?: string
  token_type?: string
}

/** Respuesta real de POST /autenticacion/registro (RespuestaRegistro).
 *  No es una sesión: no trae access_token. */
export interface RespuestaRegistro {
  id: string
  email: string
  sesion_creada: boolean
}

export interface Proyecto {
  id: string
  nombre: string
  comuna: string
  tipo_obra: string
  material: string
  superficie_m2: number
  pisos: number
  estandar_terminaciones: EstandarTerminaciones
  /** Con la API real sale de estado_estimacion (resumen de la última estimación). */
  estado?: EstadoProyecto | null
  ultima_estimacion_id?: string | null
  costo_total?: number | null
  costo_m2?: number | null
  fecha_estimacion?: string | null
  /** null mientras el plazo no esté integrado en el backend. */
  plazo_dias?: number | null
  creado_en?: string | null
  actualizado_en?: string | null
}

export type ProyectoNuevo = Omit<
  Proyecto,
  | 'id' | 'estado' | 'ultima_estimacion_id' | 'costo_total' | 'costo_m2' | 'fecha_estimacion'
  | 'plazo_dias' | 'creado_en' | 'actualizado_en'
>

/* --- Banco de precios ---------------------------------------------------- */

export type Unidad = 'm2' | 'm3' | 'ml' | 'kg' | 'un' | 'gl' | 'pto'

export interface CategoriaPartida {
  id: number
  codigo: string
  nombre: string
  orden: number
}

export interface Partida {
  id: string
  categoria_id: number
  codigo: string
  nombre: string
  unidad: Unidad
  es_base: boolean
  vigente: boolean
}

export type PartidaNueva = Pick<Partida, 'categoria_id' | 'nombre' | 'unidad'>

/** PUT /banco/partidas/{id}. El código no se edita. */
export type PartidaEditada = Partial<PartidaNueva>

/** borrador: editable · vigente: la que usan las estimaciones nuevas ·
 *  historica: publicada antes y ya no vigente. Las publicadas no se editan. */
export type EstadoVersion = 'borrador' | 'vigente' | 'historica'

export interface VersionPrecios {
  id: string
  version: string
  trimestre: string
  fuente?: string | null
  vigente: boolean
  cargado_en?: string | null
  /** null = borrador; con fecha = publicada alguna vez e inmutable. */
  fecha_publicacion?: string | null
  estado?: EstadoVersion
}

export function estadoVersion(v: Pick<VersionPrecios, 'vigente' | 'fecha_publicacion'>): EstadoVersion {
  if (v.vigente) return 'vigente'
  return v.fecha_publicacion ? 'historica' : 'borrador'
}

/** Fila del banco: la partida con su precio en una versión dada. */
export interface FilaBanco extends Partida {
  precio_unitario: number | null
  rendimiento_mo: number | null
  fuente?: string | null
  /** Tiene precio en alguna versión: su unidad ya no se puede cambiar. */
  tiene_precios?: boolean
}

export interface PrecioEditado {
  precio_unitario: number | null
  rendimiento_mo: number | null
  fuente?: string | null
}

/* --- Plantillas y partidas del proyecto ------------------------------------ */

export type OrigenPartida = 'plantilla' | 'catalogo' | 'manual'
export type EstadoPartida = 'calculada' | 'sin_cantidad' | 'sin_precio'

export interface PlantillaResumen {
  id: string
  nombre: string
  tipo_obra: string
  materialidad: string
  vigente: boolean
  cantidad_partidas: number
  fecha_actualizacion?: string | null
}

export interface PartidaPlantilla {
  partida_id: string
  orden: number
  cantidad_sugerida: number | null
  codigo: string
  nombre: string
  unidad: string
  categoria_id: number
  vigente: boolean
}

export interface PlantillaDetalle extends PlantillaResumen {
  partidas: PartidaPlantilla[]
}

export interface PlantillaNueva {
  nombre: string
  tipo_obra: string
  materialidad: string
  vigente?: boolean
}

/** Una línea del presupuesto del proyecto (GET /proyectos/{id}/partidas). */
export interface PartidaProyecto {
  id: string
  proyecto_id: string
  /** null = partida manual, exclusiva del proyecto. */
  partida_id: string | null
  codigo: string | null
  categoria_id: number
  categoria_codigo: string
  categoria_nombre: string
  categoria_orden: number
  nombre: string
  unidad: string
  cantidad: number | null
  precio_unitario_override: number | null
  /** Precio de la versión vigente del banco. */
  precio_banco: number | null
  /** El que se usa: particular si hay, si no el del banco. */
  precio_unitario: number | null
  /** cantidad × precio_unitario, sin factores. */
  subtotal: number | null
  estado: EstadoPartida
  origen: OrigenPartida
  orden: number
  observacion: string | null
}

export interface PartidasProyecto {
  plantilla_aplicada: PlantillaResumen | null
  plantilla_sugerida: PlantillaResumen | null
  version_precios: { id: string; version: string } | null
  partidas: PartidaProyecto[]
}

export interface PartidaProyectoNueva {
  origen: 'catalogo' | 'manual'
  partida_id?: string | null
  categoria_id?: number | null
  nombre?: string | null
  unidad?: string | null
  cantidad?: number | null
  precio_unitario_override?: number | null
  observacion?: string | null
}

export type PartidaProyectoEditada = Partial<Pick<
  PartidaProyecto,
  'nombre' | 'unidad' | 'categoria_id' | 'cantidad' | 'precio_unitario_override' | 'observacion'
>>

/** Cierre real de obra (HU-22). */
export interface CierreObra {
  fecha_inicio_real: string
  fecha_termino_real: string
  costo_real?: number | null
  plazo_real_dias?: number | null
}
