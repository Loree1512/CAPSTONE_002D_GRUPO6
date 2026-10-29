import type { RespuestaSesion, Usuario } from '../tipos/api'

/* ── Contrato confirmado: POST /autenticacion/iniciar-sesion devuelve
   RespuestaToken (access_token, refresh_token, token_type), sin datos de
   usuario ni vencimiento. `guardar()` sólo persiste el access_token.
   ──────────────────────────────────────────────────────────────────────── */

const CLAVE_TOKEN = 'buildcast.token'
const CLAVE_USUARIO = 'buildcast.usuario'

/* No hay CLAVE_VENCE: el login real no informa expires_in. El backend
   sigue rechazando con 401 un token vencido; `pedir()` en apiReal.ts ya
   limpia la sesión y redirige cuando eso ocurre. */

export function guardar(respuesta: RespuestaSesion): boolean {
  if (!respuesta.access_token) return false
  localStorage.setItem(CLAVE_TOKEN, respuesta.access_token)
  return true
}

export function token(): string | null {
  return localStorage.getItem(CLAVE_TOKEN)
}

export function usuario(): Usuario | null {
  const crudo = localStorage.getItem(CLAVE_USUARIO)
  if (!crudo) return null
  try {
    return JSON.parse(crudo) as Usuario
  } catch {
    return null
  }
}

export function haySesion(): boolean {
  return token() !== null
}

export function cerrar(): void {
  localStorage.removeItem(CLAVE_TOKEN)
  localStorage.removeItem(CLAVE_USUARIO)
}

/** Guardia de página: envía al acceso si no hay sesión. */
export function exigirSesion(): boolean {
  if (haySesion()) return true
  window.location.replace('/acceso.html')
  return false
}

export function salir(): void {
  cerrar()
  window.location.replace('/acceso.html')
}
