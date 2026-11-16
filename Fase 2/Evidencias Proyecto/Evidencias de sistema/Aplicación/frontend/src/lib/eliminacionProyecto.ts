import { MENSAJE_PROYECTO_ELIMINADO, mensajeEliminarProyecto, resolverGuardado } from './errores.ts'

export interface EliminacionProyecto {
  abierto: boolean
  eliminando: boolean
  error: string
  abrir(): void
  cancelar(): void
  confirmar(): Promise<void>
}

interface Dependencias {
  eliminar: () => Promise<unknown>
  alExito: () => void
}

/** Estado del diálogo de confirmación; solo llama a `alExito` si el DELETE responde bien. */
export function crearEliminacion({ eliminar, alExito }: Dependencias): EliminacionProyecto {
  return {
    abierto: false,
    eliminando: false,
    error: '',

    abrir() {
      this.error = ''
      this.abierto = true
    },

    cancelar() {
      if (this.eliminando) return
      this.abierto = false
    },

    async confirmar() {
      if (this.eliminando) return
      this.eliminando = true
      this.error = ''
      const resultado = await resolverGuardado(eliminar, MENSAJE_PROYECTO_ELIMINADO, mensajeEliminarProyecto)
      if (resultado.ok) {
        this.abierto = false
        alExito()
        return
      }
      this.error = resultado.error
      this.eliminando = false
    },
  }
}
