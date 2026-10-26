import { api } from './api'
import { estimarPlazo } from './motorCosto'
import type { Proyecto } from '../tipos/api'
import type { Estimacion } from '../tipos/estimacion'

/* Apoyo común de estimacion.ts y documento.ts. */

/** El plazo no es parte del motor de costos del backend: sigue siendo la
 *  regla paramétrica provisional, calculada sobre los datos estimados. */
export interface PlazoEstimado {
  plazoDias: number
  plazoMin: number
  plazoMax: number
}

export type EstimacionConPlazo = Estimacion & PlazoEstimado

export function conPlazo(estimacion: Estimacion): EstimacionConPlazo {
  const { superficieM2, numeroPisos, estandarTerminaciones } = estimacion.proyecto
  const plazo = estimarPlazo(superficieM2, numeroPisos, estandarTerminaciones)
  return { ...estimacion, plazoDias: plazo.dias, plazoMin: plazo.min, plazoMax: plazo.max }
}

/** La estimación más reciente del proyecto, o null si no tiene ninguna. */
export async function ultimaEstimacion(proyectoId: string): Promise<Estimacion | null> {
  const [ultima] = await api.listarEstimaciones(proyectoId)
  return ultima ? api.obtenerEstimacion(proyectoId, ultima.id) : null
}

/** true si el proyecto se editó después de estimar. */
export function proyectoCambio(estimacion: Estimacion, proyecto: Proyecto): boolean {
  const e = estimacion.proyecto
  return e.comuna !== proyecto.comuna
    || e.tipoObra !== proyecto.tipo_obra
    || e.materialidad !== proyecto.material
    || Number(e.superficieM2) !== Number(proyecto.superficie_m2)
    || Number(e.numeroPisos) !== Number(proyecto.pisos)
    || e.estandarTerminaciones !== proyecto.estandar_terminaciones
}
