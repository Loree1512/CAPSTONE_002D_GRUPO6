import type { Usuario } from '../tipos/api.ts'

/* Rol global del usuario: decide qué navegación se muestra. La API vuelve a
   autorizar cada operación; esto solo evita mostrar lo que no se puede usar. */

export function esAdministrador(usuario: Usuario | null | undefined): boolean {
  return usuario?.rol === 'administrador'
}

interface ConElementos {
  querySelectorAll(selector: string): ArrayLike<{ hidden: boolean }>
}

/** Muestra u oculta los enlaces marcados con data-solo-admin. */
export function mostrarSoloAdmin(raiz: ConElementos, usuario: Usuario | null | undefined): void {
  const visible = esAdministrador(usuario)
  for (const elemento of Array.from(raiz.querySelectorAll('[data-solo-admin]'))) {
    elemento.hidden = !visible
  }
}
