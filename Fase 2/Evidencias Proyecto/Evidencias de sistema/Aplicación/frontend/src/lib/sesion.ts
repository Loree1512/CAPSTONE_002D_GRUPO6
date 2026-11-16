import type { Usuario } from '../tipos/api.ts'

/* POST /autenticacion/iniciar-sesion y /autenticacion/refrescar devuelven
   access_token y refresh_token. Ante un 401, `pedir()` (http.ts) canjea el
   refresh token por una sesión nueva; solo si Supabase lo rechaza se cierra. */

const CLAVE_TOKEN = 'buildcast.token'
const CLAVE_REFRESCO = 'buildcast.refresco'
const CLAVE_USUARIO = 'buildcast.usuario'

export function guardar(respuesta: { access_token?: string; refresh_token?: string }): boolean {
  if (!respuesta.access_token) return false
  localStorage.setItem(CLAVE_TOKEN, respuesta.access_token)
  // Sin refresh token no queda uno viejo de otra sesión.
  if (respuesta.refresh_token) localStorage.setItem(CLAVE_REFRESCO, respuesta.refresh_token)
  else localStorage.removeItem(CLAVE_REFRESCO)
  return true
}

export function token(): string | null {
  return localStorage.getItem(CLAVE_TOKEN)
}

export function refresco(): string | null {
  return localStorage.getItem(CLAVE_REFRESCO)
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

/** Copia local de GET /autenticacion/yo: solo decide qué se muestra; la API autoriza. */
export function guardarUsuario(datos: Usuario): void {
  localStorage.setItem(CLAVE_USUARIO, JSON.stringify(datos))
}

export function haySesion(): boolean {
  return token() !== null
}

export function cerrar(): void {
  localStorage.removeItem(CLAVE_TOKEN)
  localStorage.removeItem(CLAVE_REFRESCO)
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
