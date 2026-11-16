import { api } from './api'
import type { Proyecto } from '../tipos/api'
import type { Estimacion } from '../tipos/estimacion'

/* Apoyo común de estimacion.ts y documento.ts. */

export { conPlazo } from './plazo'

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
