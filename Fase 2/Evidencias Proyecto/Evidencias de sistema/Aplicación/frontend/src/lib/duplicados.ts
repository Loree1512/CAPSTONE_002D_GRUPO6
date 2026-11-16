import type { PartidaProyecto } from '../tipos/api.ts'

/* Partidas repetidas en el presupuesto.

   La identidad de una partida de catálogo es su `partida_id`: la misma en el catálogo, en la
   plantilla y en las filas del proyecto, venga de donde venga (`origen` plantilla o catálogo).
   Una partida manual no tiene `partida_id`: es exclusiva del proyecto y nunca cuenta como
   repetida, ni siquiera con el mismo nombre que otra. El texto, la categoría, la unidad o el
   precio tampoco definen un duplicado. */

type FilaPartida = Pick<PartidaProyecto, 'id' | 'partida_id' | 'nombre'>

/** La fila del proyecto que ya corresponde a esa partida de catálogo, si hay una. */
export function partidaDeCatalogoAgregada<T extends FilaPartida>(
  partidas: readonly T[],
  partidaId: string | null | undefined,
): T | undefined {
  if (!partidaId) return undefined
  return partidas.find((p) => p.partida_id === partidaId)
}
