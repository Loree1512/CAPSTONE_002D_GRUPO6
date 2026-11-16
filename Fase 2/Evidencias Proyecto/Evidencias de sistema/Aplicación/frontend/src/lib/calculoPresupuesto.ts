import type { EstadoProyecto } from '../tipos/api.ts'

/* Estado de carga del presupuesto: el cálculo del botón Recalcular y las filas que se
   están guardando. Funciones puras: la página solo guarda el resultado. */

// --- Recalcular ------------------------------------------------------------------

export interface CondicionesCalculo {
  /** Hay un cálculo en curso. */
  guardando: boolean
  /** Alguna partida se está guardando: el cálculo leería valores a medio guardar. */
  hayFilasEnProceso: boolean
  errorAjustes: string
  errorTextoObservaciones: string
  hayPartidas: boolean
  hayPresupuesto: boolean
  costoPendiente: boolean
}

/** El botón solo puede disparar un cálculo a la vez y solo si hay algo que calcular. */
export function puedeCalcular(c: CondicionesCalculo): boolean {
  if (c.guardando || c.hayFilasEnProceso || c.errorAjustes || c.errorTextoObservaciones || !c.hayPartidas) return false
  return !c.hayPresupuesto || c.costoPendiente
}

export function textoBotonCalcular(c: { guardando: boolean; hayFilasEnProceso: boolean; hayPresupuesto: boolean; ajustesCambiaron: boolean }): string {
  if (c.guardando) return 'Calculando…'
  if (c.hayFilasEnProceso) return 'Guardando cambios…'
  if (!c.hayPresupuesto) return 'Generar estimación'
  return c.ajustesCambiaron ? 'Aplicar cambios' : 'Recalcular'
}

export interface EstadoDeCalculo {
  guardando: boolean
  errorCalculo: string
}

/** Corre un cálculo con su estado de carga. Si ya hay uno en curso no hace nada (devuelve
 *  undefined): un doble clic no dispara dos estimaciones. El botón se libera siempre, con
 *  éxito o con error; el error queda en `errorCalculo`. */
export async function conCalculo<T>(
  estado: EstadoDeCalculo,
  tarea: () => Promise<T>,
  mensajeError: (error: unknown) => string,
): Promise<T | undefined> {
  if (estado.guardando) return undefined
  estado.guardando = true
  estado.errorCalculo = ''
  try {
    return await tarea()
  } catch (e) {
    estado.errorCalculo = mensajeError(e)
    return undefined
  } finally {
    estado.guardando = false
  }
}

/** Estado del proyecto justo después de generar una estimación: vigente, salvo que ya esté
 *  ejecutado. Es solo para no mostrar «por recalcular» hasta que llegue el estado real. */
export function estadoTrasCalcular(actual: EstadoProyecto | null | undefined): EstadoProyecto {
  return actual === 'ejecutada' ? 'ejecutada' : 'vigente'
}

// --- Filas en proceso --------------------------------------------------------------

/** Cuántas operaciones lleva cada partida en curso. Una fila ocupada no bloquea a las demás. */
export type FilasEnProceso = Readonly<Record<string, number>>

export function iniciarFila(filas: FilasEnProceso, id: string): FilasEnProceso {
  return { ...filas, [id]: (filas[id] ?? 0) + 1 }
}

export function terminarFila(filas: FilasEnProceso, id: string): FilasEnProceso {
  const { [id]: cuenta = 0, ...resto } = filas
  return cuenta > 1 ? { ...resto, [id]: cuenta - 1 } : resto
}

export function filaEnProceso(filas: FilasEnProceso, id: string): boolean {
  return (filas[id] ?? 0) > 0
}

export function hayFilasEnProceso(filas: FilasEnProceso): boolean {
  return Object.keys(filas).length > 0
}

// --- Refresco en segundo plano --------------------------------------------------------

/** Numera los pedidos: solo el último en salir puede aplicar su respuesta, así una respuesta
 *  lenta y vieja no pisa a una más reciente. */
export function crearSecuencia() {
  let ultimo = 0
  return {
    nueva: (): number => ++ultimo,
    vigente: (numero: number): boolean => numero === ultimo,
  }
}
