import { ErrorApi } from './errores.ts'
import type { CategoriaPartida, PartidasProyecto, PlantillaResumen, PartidaProyecto, Proyecto, VersionPrecios } from '../tipos/api.ts'
import type { Estimacion } from '../tipos/estimacion.ts'

/* Carga del detalle de un proyecto (estimacion.html).

   La pantalla solo tiene tres estados y se dibuja uno a la vez:
     cargando → esqueleto, sin textos de estado vacío ni valores por defecto
     listo    → datos reales (recién aquí puede decir «Sin plantilla» o «Sin partidas»)
     error    → aviso explícito con «Reintentar»; nunca un estado vacío

   Para que «listo» no muestre nada a medias, todas las peticiones se resuelven
   antes de asignar: el detalle llega completo o no llega. */

export type VistaDetalle = 'cargando' | 'listo' | 'error'

export interface EstadoCarga {
  cargando: boolean
  proyecto: unknown
  error: string
}

export function vistaDetalle({ cargando, proyecto, error }: EstadoCarga): VistaDetalle {
  if (cargando) return 'cargando'
  return proyecto && !error ? 'listo' : 'error'
}

export interface AjustesBase { gastosGeneralesPct: number; utilidadPct: number }

export interface FuenteDetalle {
  obtenerProyecto(id: string): Promise<Proyecto>
  listarVersiones(): Promise<VersionPrecios[]>
  listarCategorias(): Promise<CategoriaPartida[]>
  listarPartidasProyecto(id: string): Promise<PartidasProyecto>
  ultimaEstimacion(id: string): Promise<Estimacion | null>
  obtenerConfiguracion(): Promise<AjustesBase>
}

export interface DetalleProyecto {
  proyecto: Proyecto
  versionVigenteId: string | null
  categorias: CategoriaPartida[]
  partidas: PartidaProyecto[]
  plantillaAplicada: PlantillaResumen | null
  plantillaSugerida: PlantillaResumen | null
  estimacion: Estimacion | null
  /** Ajustes que propone el formulario cuando todavía no hay estimación. */
  ajustes: AjustesBase
}

export const MENSAJE_SIN_ID = 'No se indicó el proyecto.'

/** Todo en paralelo; si falla una petición necesaria, falla la carga completa.
 *  La configuración es opcional: sin ella se usan los ajustes base. */
export async function cargarDetalleProyecto(
  fuente: FuenteDetalle, id: string, ajustesBase: AjustesBase,
): Promise<DetalleProyecto> {
  const [proyecto, versiones, categorias, datos, estimacion, ajustes] = await Promise.all([
    fuente.obtenerProyecto(id),
    fuente.listarVersiones(),
    fuente.listarCategorias(),
    fuente.listarPartidasProyecto(id),
    fuente.ultimaEstimacion(id),
    fuente.obtenerConfiguracion().catch(() => ajustesBase),
  ])
  return {
    proyecto,
    versionVigenteId: versiones.find((v) => v.vigente)?.id ?? null,
    categorias,
    partidas: datos.partidas,
    plantillaAplicada: datos.plantilla_aplicada,
    plantillaSugerida: datos.plantilla_sugerida,
    estimacion,
    ajustes: { gastosGeneralesPct: ajustes.gastosGeneralesPct, utilidadPct: ajustes.utilidadPct },
  }
}

/** Detalle para el aviso de error; el título fijo lo pone la página. */
export function mensajeCargaProyecto(e: unknown): string {
  if (e instanceof ErrorApi) {
    if (e.estado === 404) return 'El proyecto no existe o fue eliminado.'
    if (e.estado === 403) return 'No tienes acceso a este proyecto.'
    if (e.estado === 401) return 'Tu sesión expiró. Vuelve a iniciar sesión.'
    if (e.estado === 0) return 'No hubo respuesta del servidor. Revisa tu conexión e inténtalo de nuevo.'
    return e.message
  }
  return 'Ocurrió un problema inesperado al obtener los datos.'
}

/** Sin proyecto que pedir, reintentar no cambia nada. */
export function puedeReintentar(error: string): boolean {
  return error !== MENSAJE_SIN_ID
}
