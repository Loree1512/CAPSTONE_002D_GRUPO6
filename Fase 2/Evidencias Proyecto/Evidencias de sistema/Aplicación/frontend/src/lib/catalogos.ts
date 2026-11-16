import type { EstandarTerminaciones, EstadoProyecto } from '../tipos/api'

/* Valores de referencia mientras no existan endpoints de catálogo.
   Cuando el backend los exponga, se reemplazan por una llamada. */

export const COMUNAS = [
  'Viña del Mar', 'Valparaíso', 'Quilpué', 'Villa Alemana', 'Concón',
  'Limache', 'Olmué', 'Quillota', 'Casablanca',
]

export const TIPOS_OBRA = [
  'Vivienda unifamiliar', 'Ampliación', 'Edificación habitacional',
]

export const MATERIALES = [
  'Albañilería confinada', 'Hormigón armado', 'Tabiquería de madera', 'Estructura metálica',
]

export const ESTANDARES: { valor: EstandarTerminaciones; etiqueta: string }[] = [
  { valor: 'economico', etiqueta: 'Económico' },
  { valor: 'medio', etiqueta: 'Medio' },
  { valor: 'alto', etiqueta: 'Alto' },
]

export const ESTADOS: Record<EstadoProyecto, { etiqueta: string; clase: string }> = {
  // Naranja = pide acción; tinta = resuelto; gris = cerrado. Ver .bc-insignia en base.css.
  sin_estimar: { etiqueta: 'Sin estimar', clase: 'bc-insignia--pendiente' },
  vigente:     { etiqueta: 'Vigente', clase: 'bc-insignia--ok' },
  recalcular:  { etiqueta: 'Por recalcular', clase: 'bc-insignia--atencion' },
  ejecutada:   { etiqueta: 'Ejecutada', clase: 'bc-insignia--cerrado' },
}
