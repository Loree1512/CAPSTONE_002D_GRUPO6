import type { EstandarTerminaciones } from '../tipos/api'

/* Configuración del cálculo (RNF-06).

   Con la API real vive en FastAPI: las páginas usan api.obtenerConfiguracion
   y api.guardarConfiguracion. Las funciones de este archivo guardan en el
   navegador y solo las usan el modo demostración y motorCosto.ts.

   El motor actual solo usa GG, utilidad, comuna y pisos. Hora hombre,
   estándar y materialidad se conservan para uso posterior. */

export interface TramoPisos { desde: number; hasta: number; factor: number }

export interface Configuracion {
  valorHoraHombre: number
  gastosGeneralesPct: number
  utilidadPct: number
  factoresComuna: Record<string, number>
  tramosPisos: TramoPisos[]
  factoresEstandar: Record<EstandarTerminaciones, number>
  factoresMaterial: Record<string, number>
  /** Capítulos a los que se aplica cada factor. Los entrega el backend;
   *  si no se envían al guardar, se conservan los que tenga. */
  capitulosEstandar?: string[]
  capitulosMaterialidad?: string[]
}

export const CONFIGURACION_BASE: Configuracion = {
  valorHoraHombre: 9000,
  gastosGeneralesPct: 12,
  utilidadPct: 10,
  factoresComuna: {
    'Viña del Mar': 1.05,
    'Valparaíso': 1.04,
    'Concón': 1.06,
    'Quilpué': 1.00,
    'Villa Alemana': 0.99,
    'Limache': 0.98,
    'Olmué': 1.00,
    'Quillota': 0.98,
    'Casablanca': 1.02,
  },
  tramosPisos: [
    { desde: 1, hasta: 1, factor: 1.00 },
    { desde: 2, hasta: 2, factor: 1.05 },
    { desde: 3, hasta: 99, factor: 1.12 },
  ],
  factoresEstandar: { economico: 0.85, medio: 1.00, alto: 1.28 },
  factoresMaterial: {
    'Albañilería confinada': 0.94,
    'Hormigón armado': 1.03,
    'Tabiquería de madera': 0.97,
    'Estructura metálica': 1.02,
  },
}

const CLAVE = 'buildcast.configuracion'

export function leerConfig(): Configuracion {
  const crudo = localStorage.getItem(CLAVE)
  if (!crudo) return structuredClone(CONFIGURACION_BASE)
  try {
    return { ...structuredClone(CONFIGURACION_BASE), ...JSON.parse(crudo) as Configuracion }
  } catch {
    return structuredClone(CONFIGURACION_BASE)
  }
}

export function guardarConfig(config: Configuracion): void {
  localStorage.setItem(CLAVE, JSON.stringify(config))
}

export function restaurarConfig(): void {
  localStorage.removeItem(CLAVE)
}

export function factorPisos(config: Pick<Configuracion, 'tramosPisos'>, pisos: number): number {
  return config.tramosPisos.find((t) => pisos >= t.desde && pisos <= t.hasta)?.factor ?? 1
}
