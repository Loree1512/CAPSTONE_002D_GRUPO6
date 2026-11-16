import { ErrorApi } from './errores.ts'

/* Cliente HTTP de la API real: clasifica los errores y renueva la sesión ante un 401.
   No depende de window ni de import.meta para poder probarlo en Node. */

export type Metodo = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface Opciones {
  metodo?: Metodo
  cuerpo?: unknown
  autenticado?: boolean
}

export interface Tokens {
  access_token: string
  refresh_token?: string
}

export interface AlmacenSesion {
  token(): string | null
  refresco(): string | null
  guardar(tokens: Tokens): boolean
  cerrar(): void
}

export interface ConfigCliente {
  base: string
  sesion: AlmacenSesion
  fetch?: (url: string, init: RequestInit) => Promise<Response>
  /** Después de borrar la sesión: la app lleva al acceso. */
  alCerrarSesion?: () => void
  /** La API rechazó la sesión de un invitado que aún no crea su contraseña. */
  alAccesoPendiente?: () => void
}

/** Cabecera con la que el backend marca un 403 por invitación pendiente. */
export const CABECERA_ACCESO = 'X-BuildCast-Acceso'

export const MENSAJES = {
  conexion: 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo nuevamente.',
  sesionVencida: 'Tu sesión expiró. Vuelve a iniciar sesión.',
  sesionRechazada: 'No se pudo validar tu sesión. Si el problema sigue, vuelve a iniciar sesión.',
  renovacion: 'No se pudo renovar tu sesión en este momento. Tus cambios no se perdieron: inténtalo nuevamente.',
  permisos: 'No tienes permisos para realizar esta acción.',
  noEncontrado: 'No se encontró lo que buscas.',
  validacion: 'Revisa los datos ingresados.',
  servidor: 'El servidor no pudo completar la solicitud. Inténtalo nuevamente en unos minutos.',
  invalida: 'El servidor envió una respuesta inesperada. Inténtalo nuevamente.',
} as const

/** FastAPI manda `detail` como texto o como lista de errores de Pydantic. */
function detalle(cuerpo: unknown): string | undefined {
  if (!cuerpo || typeof cuerpo !== 'object' || !('detail' in cuerpo)) return undefined
  const valor = (cuerpo as { detail: unknown }).detail
  if (typeof valor === 'string' && valor.trim()) return valor
  if (Array.isArray(valor) && typeof valor[0]?.msg === 'string') return valor[0].msg
  return undefined
}

function mensajePorEstado(estado: number, cuerpo: unknown): string {
  // En 5xx el detalle es técnico o genérico: se muestra un texto propio.
  if (estado >= 500) return MENSAJES.servidor
  const propio = detalle(cuerpo)
  if (propio) return propio
  if (estado === 401) return MENSAJES.sesionVencida
  if (estado === 403) return MENSAJES.permisos
  if (estado === 404) return MENSAJES.noEncontrado
  if (estado === 422) return MENSAJES.validacion
  return `La solicitud falló (${estado}).`
}

type Cuerpo = { valido: true; datos: unknown } | { valido: false }

async function leerCuerpo(respuesta: Response): Promise<Cuerpo> {
  let texto: string
  try {
    texto = await respuesta.text()
  } catch {
    // La conexión se cortó a mitad de la respuesta.
    throw new ErrorApi(0, MENSAJES.conexion)
  }
  if (!texto) return { valido: true, datos: null }
  try {
    return { valido: true, datos: JSON.parse(texto) }
  } catch {
    return { valido: false }
  }
}

type Renovacion = 'renovada' | 'invalida' | 'sin_conexion' | 'no_disponible'

export function crearCliente(config: ConfigCliente) {
  const { base, sesion } = config
  const hacerFetch = config.fetch ?? ((url, init) => fetch(url, init))

  // Una sola renovación a la vez: los 401 simultáneos esperan la misma.
  let renovando: Promise<Renovacion> | null = null

  async function enviar(ruta: string, opciones: Opciones, token: string | null): Promise<Response> {
    const cabeceras: Record<string, string> = { Accept: 'application/json' }
    if (opciones.cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json'
    if (token) cabeceras['Authorization'] = `Bearer ${token}`
    try {
      return await hacerFetch(`${base}${ruta}`, {
        method: opciones.metodo ?? 'GET',
        headers: cabeceras,
        body: opciones.cuerpo === undefined ? undefined : JSON.stringify(opciones.cuerpo),
      })
    } catch {
      // Sin respuesta HTTP: red, servidor caído o CORS. El navegador no permite distinguirlos.
      throw new ErrorApi(0, MENSAJES.conexion)
    }
  }

  async function intentarRenovar(): Promise<Renovacion> {
    const refresco = sesion.refresco()
    if (!refresco) return 'invalida'

    let respuesta: Response
    try {
      respuesta = await enviar('/autenticacion/refrescar', { metodo: 'POST', cuerpo: { refresh_token: refresco } }, null)
    } catch {
      return 'sin_conexion'
    }
    // 401: Supabase rechazó el refresh token (vencido, revocado o ya usado).
    if (respuesta.status === 401) return 'invalida'
    if (!respuesta.ok) return 'no_disponible'

    try {
      const cuerpo = await leerCuerpo(respuesta)
      const tokens = cuerpo.valido ? (cuerpo.datos as Partial<Tokens> | null) : null
      if (!tokens?.access_token || !tokens.refresh_token) return 'no_disponible'
      sesion.guardar({ access_token: tokens.access_token, refresh_token: tokens.refresh_token })
      return 'renovada'
    } catch {
      return 'sin_conexion'
    }
  }

  function renovar(): Promise<Renovacion> {
    renovando ??= intentarRenovar().finally(() => { renovando = null })
    return renovando
  }

  async function repetirConSesionNueva(ruta: string, opciones: Opciones, usado: string | null): Promise<Response> {
    const actual = sesion.token()
    // Si otra petición ya renovó mientras esta viajaba, basta con repetirla.
    if (!actual || actual === usado) {
      const resultado = await renovar()
      if (resultado === 'invalida') {
        sesion.cerrar()
        config.alCerrarSesion?.()
        throw new ErrorApi(401, MENSAJES.sesionVencida)
      }
      if (resultado === 'sin_conexion') throw new ErrorApi(0, MENSAJES.renovacion)
      if (resultado === 'no_disponible') throw new ErrorApi(503, MENSAJES.renovacion)
    }

    // Una sola repetición: otro 401 no vuelve a renovar, así no hay ciclos.
    const repetida = await enviar(ruta, opciones, sesion.token())
    if (repetida.status === 401) throw new ErrorApi(401, MENSAJES.sesionRechazada)
    return repetida
  }

  async function pedir<T>(ruta: string, opciones: Opciones = {}): Promise<T> {
    const autenticado = opciones.autenticado ?? true
    const usado = autenticado ? sesion.token() : null

    let respuesta = await enviar(ruta, opciones, usado)
    if (respuesta.status === 401 && autenticado) {
      respuesta = await repetirConSesionNueva(ruta, opciones, usado)
    }

    const cuerpo = await leerCuerpo(respuesta)
    if (!respuesta.ok) {
      const mensaje = mensajePorEstado(respuesta.status, cuerpo.valido ? cuerpo.datos : null)
      // La sesión sigue siendo válida: no se cierra, se lleva a crear la contraseña.
      if (respuesta.status === 403 && respuesta.headers.get(CABECERA_ACCESO) === 'pendiente') {
        config.alAccesoPendiente?.()
        throw new ErrorApi(403, mensaje, 'acceso_pendiente')
      }
      throw new ErrorApi(respuesta.status, mensaje)
    }
    if (!cuerpo.valido) throw new ErrorApi(respuesta.status, MENSAJES.invalida, 'respuesta_invalida')
    return cuerpo.datos as T
  }

  return { pedir }
}
