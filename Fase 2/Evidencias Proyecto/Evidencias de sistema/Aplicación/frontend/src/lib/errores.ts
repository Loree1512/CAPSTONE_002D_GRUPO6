export type TipoError =
  | 'conexion' | 'autenticacion' | 'permisos' | 'no_encontrado' | 'conflicto'
  | 'validacion' | 'servidor' | 'respuesta_invalida' | 'solicitud' | 'acceso_pendiente'

export function tipoPorEstado(estado: number): TipoError {
  if (estado === 0) return 'conexion'
  if (estado === 401) return 'autenticacion'
  if (estado === 403) return 'permisos'
  if (estado === 404) return 'no_encontrado'
  if (estado === 409) return 'conflicto'
  if (estado === 422) return 'validacion'
  if (estado >= 500) return 'servidor'
  return 'solicitud'
}

/** estado 0 = no hubo respuesta HTTP (sin conexión, CORS, servidor caído). */
export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string, public tipo: TipoError = tipoPorEstado(estado)) {
    super(mensaje)
    this.name = 'ErrorApi'
  }
}

export const MENSAJE_GUARDAR_PLANTILLA =
  'No fue posible guardar la plantilla. Inténtalo nuevamente.'

/** Mensaje para el usuario según la respuesta de la API; lo que no sea ErrorApi cae en el genérico. */
export function mensajeGuardarPlantilla(e: unknown): string {
  if (!(e instanceof ErrorApi)) return MENSAJE_GUARDAR_PLANTILLA
  switch (e.estado) {
    case 401: return 'Tu sesión expiró. Vuelve a iniciar sesión.'
    case 403: return 'No tienes permisos para editar plantillas.'
    case 404: return 'La plantilla no fue encontrada. Puede haber sido eliminada.'
    case 422: return 'Los datos de la plantilla no son válidos. Revísalos e inténtalo nuevamente.'
    // La API explica el conflicto.
    case 409: return e.message
    default: return MENSAJE_GUARDAR_PLANTILLA
  }
}

export type ResultadoGuardado = { ok: true; mensaje: string } | { ok: false; error: string }

/** Solo una respuesta 2xx cuenta como guardado; cualquier fallo es error. */
export async function resolverGuardado(
  guardar: () => Promise<unknown>,
  mensajeExito: string,
  mensajeError: (e: unknown) => string = mensajeGuardarPlantilla,
): Promise<ResultadoGuardado> {
  try {
    await guardar()
    return { ok: true, mensaje: mensajeExito }
  } catch (e) {
    return { ok: false, error: mensajeError(e) }
  }
}

export const MENSAJE_PROYECTO_ELIMINADO = 'Proyecto eliminado.'

export function mensajeEliminarProyecto(e: unknown): string {
  if (e instanceof ErrorApi) {
    if (e.estado === 403) return 'Solo el propietario puede eliminar el proyecto.'
    if (e.estado === 404) return 'El proyecto ya no existe.'
    if (e.estado === 401) return 'Tu sesión expiró. Vuelve a iniciar sesión.'
  }
  return 'No fue posible eliminar el proyecto. Inténtalo nuevamente.'
}
