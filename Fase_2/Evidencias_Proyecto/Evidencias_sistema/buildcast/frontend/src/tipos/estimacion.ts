import type { EstandarTerminaciones, OrigenPartida } from './api'

/* Estimaciones de FastAPI (/proyectos/{id}/estimaciones).
   Presupuesto por partidas: cantidad × precio unitario. Montos en CLP entero. */

/** calculada suma al costo directo; las demás quedan fuera con su motivo. */
export type EstadoLinea = 'calculada' | 'sin_cantidad' | 'sin_precio'

export interface VersionPreciosUsada {
  id: string
  version: string
  fuente: string | null
}

/** Datos del proyecto tal como estaban al estimar. */
export interface ProyectoEstimado {
  comuna: string
  tipoObra: string
  materialidad: string
  superficieM2: number
  numeroPisos: number
  estandarTerminaciones: EstandarTerminaciones
}

/** Valores usados: 1 si la estimación no aplicó factores. */
export interface FactoresEstimacion {
  comuna: number
  pisos: number
  /** comuna × pisos */
  ajuste: number
}

export interface LineaEstimacion {
  /** Partida del proyecto de origen. */
  id: string | null
  codigo: string | null
  nombre: string
  unidad: string
  categoriaCodigo: string
  categoriaNombre: string
  cantidad: number | null
  /** Precio usado, sin factor. */
  precioUnitario: number | null
  subtotal: number

  partidaId: string | null
  origen: OrigenPartida
  observacion: string | null
  estado: EstadoLinea
  precioUnitarioBase: number | null
  precioUnitarioOverride: number | null
  fuentePrecio: string | null
  factorAplicado: number
  subtotalBase: number
}

export interface CapituloEstimacion {
  codigo: string
  nombre: string
  subtotal: number
  incidencia: number
  lineas: LineaEstimacion[]
}

/** Respuesta de GET /proyectos/{id}/estimaciones. */
export interface EstimacionResumen {
  id: string
  proyectoId: string
  fechaCreacion: string
  versionMotor: string
  versionPrecios: VersionPreciosUsada
  costoDirecto: number
  total: number
  costoM2: number
  completa: boolean
  partidasCalculadas: number
  partidasSinPrecio: number
  partidasSinCantidad: number
}

/** Respuesta de POST y GET de una estimación. */
export interface Estimacion extends EstimacionResumen {
  proyecto: ProyectoEstimado
  capitulos: CapituloEstimacion[]
  /** Suma de partidas antes de factores. */
  costoDirectoBase: number
  gastosGeneralesPct: number
  gastosGenerales: number
  utilidadPct: number
  utilidad: number
  aplicarFactores: boolean
  factores: FactoresEstimacion
  sinPrecio: LineaEstimacion[]
  sinCantidad: LineaEstimacion[]
}

/** Cuerpo opcional de POST /proyectos/{id}/estimaciones. */
export interface OpcionesEstimacion {
  version_precio_id?: string
  gastos_generales_pct?: number
  utilidad_pct?: number
  /** Factores de comuna y pisos; apagados si no se envía. */
  aplicar_factores?: boolean
}

/** Mismos límites que FastAPI. */
export const LIMITE_GASTOS_GENERALES = 25
export const LIMITE_UTILIDAD = 30
