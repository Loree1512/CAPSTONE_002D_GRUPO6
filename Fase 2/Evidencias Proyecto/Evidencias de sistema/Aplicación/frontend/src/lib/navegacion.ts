import { api } from './api'
import { guardarUsuario, usuario } from './sesion'
import { mostrarSoloAdmin } from './rolGlobal'
import { conectarMenuBarra } from './menuBarra'
import type { Usuario } from '../tipos/api'

/** Muestra «Administración» solo a administradores. Primero con lo guardado, para
 *  no parpadear; luego con lo que responde la API. */
export async function prepararNavegacion(): Promise<Usuario | null> {
  conectarMenuBarra()
  mostrarSoloAdmin(document, usuario())
  try {
    const actual = await api.yo()
    guardarUsuario(actual)
    // Sesión de invitación sin contraseña: primero debe crearla.
    if (actual.accesoConfigurado === false) {
      window.location.replace('/acceso.html')
      return null
    }
    mostrarSoloAdmin(document, actual)
    return actual
  } catch {
    // Sin respuesta se queda como estaba: la API sigue autorizando.
    return null
  }
}
