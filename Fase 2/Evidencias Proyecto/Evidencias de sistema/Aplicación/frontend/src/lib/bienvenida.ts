import type { Usuario } from '../tipos/api.ts'

/* Bienvenida discreta del Panel. Usa al usuario autenticado (GET /autenticacion/yo);
   no hay nombres escritos aquí. El rol no se muestra en esta pantalla. */

export const MENSAJE_BIENVENIDA = 'Revisa el estado de tus proyectos y estimaciones.'

export interface Bienvenida {
  /** "Buenos días, Ángel" o, sin nombre, "Buenos días". */
  saludo: string
  mensaje: string
}

/** Primer nombre del nombre completo; null si no hay nombre. */
export function primerNombre(nombre: string | null | undefined): string | null {
  return nombre?.trim().split(/\s+/)[0] || null
}

/** Hora (0–23) en Chile. Sin base de zonas horarias se usa la hora local del equipo. */
export function horaChile(ahora: Date): number {
  try {
    const hora = new Intl.DateTimeFormat('es-CL', {
      hour: 'numeric', hourCycle: 'h23', timeZone: 'America/Santiago',
    }).formatToParts(ahora).find((p) => p.type === 'hour')?.value
    const n = Number(hora)
    if (hora !== undefined && Number.isInteger(n) && n >= 0 && n <= 23) return n
  } catch { /* cae a la hora local */ }
  return ahora.getHours()
}

/** 06:00–11:59 días, 12:00–19:59 tardes, el resto noches. */
export function saludoSegunHora(ahora: Date): string {
  const hora = horaChile(ahora)
  if (hora >= 6 && hora < 12) return 'Buenos días'
  if (hora >= 12 && hora < 20) return 'Buenas tardes'
  return 'Buenas noches'
}

export function bienvenida(usuario: Usuario | null | undefined, ahora: Date = new Date()): Bienvenida {
  const nombre = primerNombre(usuario?.nombre)
  const saludo = saludoSegunHora(ahora)
  return {
    saludo: nombre ? `${saludo}, ${nombre}` : saludo,
    mensaje: MENSAJE_BIENVENIDA,
  }
}
