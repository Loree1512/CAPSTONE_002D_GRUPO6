import { ErrorApi } from './errores.ts'
import type { Usuario } from '../tipos/api.ts'

/* Enlace de Supabase (invitación o, al renovar una cuenta ya confirmada, recuperación):
   vuelve con la sesión en el fragmento (#access_token=…&type=invite) o con el error
   (#error_code=…). El fragmento solo trae la sesión: si falta crear la contraseña lo
   decide el backend (acceso_configurado), no el tipo del enlace. */

export const CLAVE_MINIMA = 8

/** Tipos de enlace que traen la sesión de alguien que todavía puede estar pendiente. */
const TIPOS_CON_SESION = new Set(['invite', 'recovery', 'magiclink'])

export type EnlaceInvitacion =
  | { tipo: 'invitacion'; access_token: string; refresh_token?: string }
  | { tipo: 'error'; mensaje: string }
  | null

export const MENSAJE_ENLACE_INVALIDO =
  'El enlace de invitación no es válido o ya expiró. Pide uno nuevo a un administrador.'

export const MENSAJE_SIN_VERIFICAR =
  'No pudimos verificar tu acceso. Revisa tu conexión e inténtalo nuevamente.'

export function leerEnlaceInvitacion(hash: string): EnlaceInvitacion {
  const datos = new URLSearchParams(hash.replace(/^#/, ''))
  if (datos.get('error') || datos.get('error_code')) return { tipo: 'error', mensaje: MENSAJE_ENLACE_INVALIDO }

  const token = datos.get('access_token')
  if (!token || !TIPOS_CON_SESION.has(datos.get('type') ?? '')) return null
  return { tipo: 'invitacion', access_token: token, refresh_token: datos.get('refresh_token') ?? undefined }
}

/** El fragmento trae una sesión o un error de Supabase: hay que llevarlo a acceso.html. */
export function esFragmentoDeAuth(hash: string): boolean {
  const datos = new URLSearchParams(hash.replace(/^#/, ''))
  return datos.has('access_token') || datos.has('error_code') || datos.has('error')
}

export function errorClaveNueva(clave: string, confirmacion: string): string {
  if (clave.length < CLAVE_MINIMA) return `La contraseña debe tener al menos ${CLAVE_MINIMA} caracteres.`
  if (clave !== confirmacion) return 'Las contraseñas no coinciden.'
  return ''
}

export type Destino =
  | { a: 'crear_clave' }
  | { a: 'panel' }
  | { a: 'login'; error?: string }

/** Qué mostrar en acceso.html. `yo` es GET /autenticacion/yo, que acepta la sesión del invitado. */
export async function decidirAcceso(entrada: {
  enlace: EnlaceInvitacion
  haySesion: boolean
  guardado: Usuario | null
  yo: () => Promise<Usuario>
}): Promise<Destino> {
  const { enlace, haySesion, guardado, yo } = entrada
  if (enlace?.tipo === 'error') return { a: 'login', error: enlace.mensaje }
  if (!haySesion) return { a: 'login' }
  // Ya activo una vez, siempre activo: no hace falta preguntar.
  if (!enlace && guardado?.accesoConfigurado === true) return { a: 'panel' }

  try {
    const usuario = await yo()
    return usuario.accesoConfigurado === false ? { a: 'crear_clave' } : { a: 'panel' }
  } catch (e) {
    // 401: la sesión ya se borró; toca iniciar sesión.
    if (e instanceof ErrorApi && e.estado === 401) return { a: 'login' }
    // Sin respuesta: con el enlace recién abierto se muestra el formulario (el backend
    // vuelve a comprobarlo al guardar); sin enlace, no se adivina.
    if (enlace?.tipo === 'invitacion') return { a: 'crear_clave' }
    return { a: 'login', error: MENSAJE_SIN_VERIFICAR }
  }
}
