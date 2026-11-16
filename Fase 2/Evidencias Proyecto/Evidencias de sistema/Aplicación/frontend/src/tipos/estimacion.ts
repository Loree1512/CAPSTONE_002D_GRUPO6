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

/** Solo dentro_dominio corresponde al rango histórico del modelo; el resto es referencial. */
export type EstadoPlazo =
  | 'dentro_dominio' | 'fuera_rango_costo' | 'tipo_obra_no_representado'
  | 'costo_incompleto' | 'respaldo' | 'no_disponible'

/** Plazo sugerido por el modelo, guardado con la estimación por el backend (migración 009).
 *  Es una referencia interna para el profesional: nunca va al documento de entrega. */
export interface PlazoEstimacion {
  /** null si no se pudo calcular. */
  dias: number | null
  minDias: number | null
  maxDias: number | null
  metodo: string | null
  estado: EstadoPlazo
  fueraDominio: boolean
  provisional: boolean | null
  motivo: string | null
  versionModelo: string | null
  tipoObraModelo: string | null
  ufValor: number | null
  ufFecha: string | null
  /** Error medio observado del modelo (MAE de la versión, desde versiones_modelo). No es un
   *  intervalo de esta predicción. null si no corresponde (p. ej. valor de respaldo). */
  errorMedioDias?: number | null
  /** Estado de la versión del modelo: provisional, validado o retirado. */
  estadoModelo?: string | null
}

/** sin_definir: el profesional aún no decide. definido: decidió sobre esta estimación.
 *  por_revisar: decidió sobre una anterior y el costo se recalculó después. */
export type EstadoPlazoProfesional = 'sin_definir' | 'definido' | 'por_revisar'
export type OrigenPlazoProfesional = 'sugerencia' | 'manual'

/** Plazo para la cotización, definido por el profesional (migración 010).
 *  Es el que muestra el documento de entrega. */
export interface PlazoProfesional {
  dias: number | null
  estado: EstadoPlazoProfesional
  origen: OrigenPlazoProfesional | null
  fecha: string | null
  usuarioId: string | null
  /** Nombre o correo de quien lo definió; null si la cuenta ya no existe. */
  usuarioNombre: string | null
}

/** Cuerpo de POST /proyectos/{id}/estimaciones/{eid}/plazo-profesional: uno de los dos. */
export type DefinirPlazoProfesional = { dias: number } | { usarSugerencia: true }

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
  /** Sugerencia del modelo (interna). */
  plazo: PlazoEstimacion
  /** Plazo para la cotización (documento de entrega). */
  plazoProfesional: PlazoProfesional
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
  /** Texto plano guardado con esta estimación; nunca se interpreta como HTML. */
  observaciones?: string | null
}

/** Cuerpo opcional de POST /proyectos/{id}/estimaciones. */
export interface OpcionesEstimacion {
  version_precio_id?: string
  gastos_generales_pct?: number
  utilidad_pct?: number
  /** Factores de comuna y pisos; apagados si no se envía. */
  aplicar_factores?: boolean
  /** Se guarda con la estimación nueva; null la deja sin observación. */
  observaciones?: string | null
}

/** Mismos límites que FastAPI. */
export const LIMITE_GASTOS_GENERALES = 25
export const LIMITE_UTILIDAD = 30
