import { apiReal } from './apiReal'
import { apiSimulada } from './apiSimulada'

export { ErrorApi } from './errores'
export { reiniciarSimulacion } from './apiSimulada'

/** Modo demostración: recorre la plataforma sin API ni usuario real.
 *  Se activa con VITE_SIMULACION=true en el .env. */
export const SIMULACION = import.meta.env.VITE_SIMULACION === 'true'

export const api = SIMULACION ? apiSimulada : apiReal
