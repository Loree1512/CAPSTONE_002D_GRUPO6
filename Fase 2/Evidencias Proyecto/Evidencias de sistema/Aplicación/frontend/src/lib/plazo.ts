import type { OpcionesConfirmacion } from './confirmar.ts'
import { fecha as fechaHora } from './formato.ts'
import type { EstadoPlazo, Estimacion, PlazoEstimacion, PlazoProfesional } from '../tipos/estimacion.ts'

/* Textos del plazo para la interfaz. Hay dos datos distintos, que no se mezclan:
   - el plazo sugerido por el modelo (PlazoEstimacion): lo calcula y guarda el backend con
     el modelo de plazo; es una referencia interna para el profesional;
   - el plazo para la cotización (PlazoProfesional): lo define el profesional y es el único
     que ve el cliente en el documento de entrega.
   Aquí solo se decide cómo contarlos, sin presentar como validado lo que está fuera del
   rango histórico. El plazo real ejecutado es otro dato (cierre de obra). */

/** "v1.0-2026-11-01" → "v1.0". */
export function versionCorta(version: string | null): string | null {
  if (!version) return null
  return version.replace(/-\d{4}-\d{2}-\d{2}$/, '')
}

export function hayPlazo(plazo: PlazoEstimacion | null | undefined): plazo is PlazoEstimacion & { dias: number } {
  return !!plazo && plazo.dias !== null
}

export function textoPlazo(plazo: PlazoEstimacion | null | undefined): string {
  return hayPlazo(plazo) ? `${plazo.dias} días` : 'No disponible'
}

/** El intervalo siempre se presenta como referencial. */
export function textoRango(plazo: PlazoEstimacion | null | undefined): string {
  if (!hayPlazo(plazo) || plazo.minDias === null || plazo.maxDias === null) return ''
  return `Rango referencial: ${plazo.minDias}–${plazo.maxDias} días`
}

export function etiquetaModelo(plazo: PlazoEstimacion | null | undefined): string {
  const version = versionCorta(plazo?.versionModelo ?? null)
  if (!hayPlazo(plazo) || !version) return 'Modelo de plazo'
  if (plazo.estado === 'respaldo') return `Modelo de plazo ${version} · Valor de respaldo`
  // Solo una versión no provisional deja de decir «provisional».
  if (plazo.provisional === false) return `Modelo de plazo ${version}`
  return `Modelo de plazo ${version} · Estimación provisional`
}

const UN_DECIMAL = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const ENTERO = new Intl.NumberFormat('es-CL')

/** "135 días", con el separador de miles de es-CL. */
export function textoDias(dias: number): string {
  return `${ENTERO.format(dias)} días`
}

export const SIN_METRICA_RESPALDO = 'Sin métrica del modelo para esta estimación (valor de respaldo)'
export const SIN_METRICA = 'Sin métrica registrada para esta versión del modelo'

/** "5,6 días": error medio observado del modelo (MAE de su versión), nunca como «±».
 *  Llega del backend desde versiones_modelo; no se escribe a mano. '' sin sugerencia. */
export function textoErrorMedio(plazo: PlazoEstimacion | null | undefined): string {
  if (!hayPlazo(plazo)) return ''
  const mae = plazo.errorMedioDias
  if (typeof mae === 'number' && Number.isFinite(mae)) return `${UN_DECIMAL.format(mae)} días`
  if (plazo.estado === 'respaldo' || plazo.metodo === 'mediana_respaldo') return SIN_METRICA_RESPALDO
  return SIN_METRICA
}

/** "Error medio observado: 5,6 días" o el texto sin métrica. */
export function lineaErrorMedio(plazo: PlazoEstimacion | null | undefined): string {
  const texto = textoErrorMedio(plazo)
  if (!texto) return ''
  return texto.endsWith(' días') ? `Error medio observado: ${texto}` : texto
}

/** «Modelo provisional» o «Modelo validado», según versiones_modelo.estado. Nunca dice
 *  «validado» si la versión no lo está. */
export function textoEstadoModelo(plazo: PlazoEstimacion | null | undefined): string {
  if (!hayPlazo(plazo)) return ''
  switch (plazo.estadoModelo) {
    case 'validado': return 'Modelo validado'
    case 'retirado': return 'Modelo retirado'
    case 'provisional': return 'Modelo provisional'
    default: return plazo.provisional ? 'Modelo provisional' : ''
  }
}

const AVISOS: Record<EstadoPlazo, string> = {
  dentro_dominio: 'Estimación basada en datos históricos limitados.',
  fuera_rango_costo: 'Fuera del rango histórico disponible: el valor es solo una referencia.',
  tipo_obra_no_representado:
    'Fuera del rango histórico disponible: no hay obras de este tipo en los datos históricos; el valor es referencial.',
  costo_incompleto: 'Plazo provisional calculado sobre costo parcial: hay partidas sin precio o sin cantidad.',
  respaldo: 'Valor de respaldo: no considera el tamaño de la obra porque no se pudo convertir el costo a UF.',
  no_disponible: 'El plazo no está disponible para esta estimación.',
}

/** Una línea, sin detalles técnicos. Nunca dice "confiable". */
export function avisoPlazo(plazo: PlazoEstimacion | null | undefined): string {
  if (plazo?.estado === 'no_disponible' && plazo.motivo === 'anterior_al_modelo') {
    return 'Esta estimación es anterior al modelo de plazo. Recalcula para obtenerlo.'
  }
  if (plazo?.estado === 'no_disponible' && plazo.motivo === 'simulacion') {
    return 'En modo demostración el plazo no se calcula.'
  }
  return AVISOS[plazo?.estado ?? 'no_disponible']
}

/* --- Jerarquía visual ---------------------------------------------------------
   Solo un plazo dentro del dominio histórico (o dentro del dominio pero con costo
   parcial) se muestra como cifra principal. Una extrapolación o el respaldo bajan a
   texto secundario: el valor queda visible para trazabilidad, no como promesa. */

type DatosEstado = Pick<PlazoEstimacion, 'dias' | 'estado' | 'motivo'>

const MOTIVOS_FUERA = new Set(['costo_bajo_rango', 'costo_sobre_rango', 'tipo_obra_no_representado'])

/** Fuera del rango histórico (tipo de obra o costo), también cuando además está incompleta. */
export function esExtrapolacion(plazo: DatosEstado | null | undefined): boolean {
  if (!plazo || plazo.dias === null) return false
  if (plazo.estado === 'fuera_rango_costo' || plazo.estado === 'tipo_obra_no_representado') return true
  return plazo.estado === 'costo_incompleto' && !!plazo.motivo && MOTIVOS_FUERA.has(plazo.motivo)
}

/** Extrapolación o respaldo: el número no es una estimación dentro del dominio. */
export function esReferencial(plazo: DatosEstado | null | undefined): boolean {
  return esExtrapolacion(plazo) || (!!plazo && plazo.dias !== null && plazo.estado === 'respaldo')
}

function motivosFuera(plazo: PlazoEstimacion): string[] {
  const motivos: string[] = []
  if (plazo.estado === 'tipo_obra_no_representado' || plazo.motivo === 'tipo_obra_no_representado') {
    motivos.push('No hay obras de este tipo en los datos históricos.')
  }
  if (plazo.motivo === 'costo_sobre_rango') motivos.push('El costo de la obra supera el rango de los datos históricos.')
  if (plazo.motivo === 'costo_bajo_rango') motivos.push('El costo de la obra está bajo el rango de los datos históricos.')
  return motivos
}

export const AVISO_EXTRAPOLACION =
  'Este proyecto no cuenta con suficientes obras similares en los datos históricos disponibles.'
export const AVISO_COSTO_PARCIAL = 'Estimación incompleta: el valor se calculó sobre costo parcial.'

export interface PresentacionPlazo {
  /** "Plazo estimado", "Plazo provisional" o "Plazo referencial". */
  rotulo: string
  /** Cifra o leyenda principal. */
  principal: string
  /** true: la cifra principal son días con jerarquía normal. */
  esCifra: boolean
  /** Solo con cifra principal. */
  rango: string
  /** Solo si el valor es referencial: el número del modelo en segundo plano. */
  valorModelo: string
  rangoTecnico: string
  origen: string
  avisos: string[]
  /** Estado breve para tablas internas. */
  estadoCorto: string
  /** Fuera del rango histórico (tipo de obra o costo). */
  extrapolacion: boolean
}

/** Presentación de la sugerencia del modelo. Solo para la interfaz del profesional. */
export function presentarPlazo(plazo: PlazoEstimacion | null | undefined): PresentacionPlazo {
  const origen = etiquetaModelo(plazo)
  const vacio = { rango: '', valorModelo: '', rangoTecnico: '', origen, extrapolacion: false }

  if (!hayPlazo(plazo)) {
    return { ...vacio, rotulo: 'Plazo estimado', principal: 'No disponible', esCifra: false,
      avisos: [avisoPlazo(plazo)], estadoCorto: 'No disponible' }
  }

  const tecnico = plazo.minDias !== null && plazo.maxDias !== null
    ? `Rango referencial: ${plazo.minDias}–${plazo.maxDias} días` : ''

  if (esExtrapolacion(plazo)) {
    const incompleta = plazo.estado === 'costo_incompleto'
    return {
      ...vacio, rotulo: 'Plazo referencial', principal: 'Fuera del rango histórico', esCifra: false, extrapolacion: true,
      valorModelo: `Valor calculado: ${plazo.dias} días`, rangoTecnico: tecnico,
      avisos: [...(incompleta ? [AVISO_COSTO_PARCIAL] : []), AVISO_EXTRAPOLACION, ...motivosFuera(plazo)],
      estadoCorto: incompleta ? 'Referencial · fuera del rango histórico, costo parcial' : 'Referencial · fuera del rango histórico',
    }
  }

  if (plazo.estado === 'respaldo') {
    return {
      ...vacio, rotulo: 'Plazo referencial', principal: 'Valor de respaldo', esCifra: false,
      valorModelo: `Valor de respaldo del modelo: ${plazo.dias} días`, rangoTecnico: tecnico,
      avisos: [AVISOS.respaldo], estadoCorto: 'Referencial · valor de respaldo',
    }
  }

  const incompleta = plazo.estado === 'costo_incompleto'
  return {
    ...vacio, rotulo: incompleta ? 'Plazo provisional' : 'Plazo estimado', principal: textoPlazo(plazo),
    esCifra: true, rango: textoRango(plazo), avisos: [avisoPlazo(plazo)],
    estadoCorto: incompleta ? 'Provisional · costo parcial' : 'Provisional · datos históricos limitados',
  }
}

/* --- Listado de proyectos ------------------------------------------------------ */

/** Celda del listado: el plazo para la cotización, nunca el número del modelo.
 *  definido → "135 días"; por_revisar → "135 días*"; sin definir → "Por definir";
 *  sin estimación → "—". */
export function plazoDelProyecto(p: {
  ultima_estimacion_id?: string | null
  plazo_profesional_dias?: number | null
  plazo_profesional_estado?: string | null
}): { texto: string; nota: string } {
  const dias = p.plazo_profesional_dias
  const estado = p.plazo_profesional_estado
  if (typeof dias === 'number' && estado === 'definido') return { texto: textoDias(dias), nota: '' }
  if (typeof dias === 'number' && estado === 'por_revisar') {
    return { texto: `${textoDias(dias)}*`, nota: 'Por revisar tras recalcular' }
  }
  if (estado || p.ultima_estimacion_id) return { texto: 'Por definir', nota: '' }
  return { texto: '—', nota: '' }
}

/* --- Plazo para la cotización (profesional) --------------------------------- */

/** Estimaciones anteriores a la migración 010, o de la demostración guardadas antes. */
export function profesionalSinDefinir(): PlazoProfesional {
  return { dias: null, estado: 'sin_definir', origen: null, fecha: null, usuarioId: null, usuarioNombre: null }
}

/** Hay un valor decidido por el profesional (definido o por revisar). */
export function hayPlazoProfesional(
  pp: PlazoProfesional | null | undefined,
): pp is PlazoProfesional & { dias: number } {
  return !!pp && pp.dias !== null && (pp.estado === 'definido' || pp.estado === 'por_revisar')
}

const ESTADOS_PROFESIONAL: Record<PlazoProfesional['estado'], string> = {
  sin_definir: 'Sin definir',
  definido: 'Definido',
  por_revisar: 'Por revisar tras recalcular',
}

const ORIGENES: Record<NonNullable<PlazoProfesional['origen']>, string> = {
  sugerencia: 'Sugerencia de BuildCast',
  manual: 'Escrito por el profesional',
}

export interface PresentacionProfesional {
  /** "135 días" o "Sin definir". */
  texto: string
  definido: boolean
  porRevisar: boolean
  estadoTexto: string
  origenTexto: string
  /** Aviso cuando el costo cambió después de definirlo; '' si no corresponde. */
  avisoRevision: string
}

export function presentarPlazoProfesional(pp: PlazoProfesional | null | undefined): PresentacionProfesional {
  const p = pp ?? profesionalSinDefinir()
  const hay = hayPlazoProfesional(p)
  return {
    texto: hay ? textoDias(p.dias) : 'Sin definir',
    definido: hay && p.estado === 'definido',
    porRevisar: hay && p.estado === 'por_revisar',
    estadoTexto: ESTADOS_PROFESIONAL[p.estado] ?? ESTADOS_PROFESIONAL.sin_definir,
    origenTexto: p.origen ? ORIGENES[p.origen] ?? '' : '',
    avisoRevision: hay && p.estado === 'por_revisar'
      ? `Por revisar: el presupuesto cambió desde que se definió (${textoDias(p.dias)}).`
      : '',
  }
}

/** "+15 días", "−5 días" o "Sin diferencia"; '' si falta alguno de los dos. */
export function diferenciaConSugerencia(
  pp: PlazoProfesional | null | undefined,
  plazo: PlazoEstimacion | null | undefined,
): string {
  if (!hayPlazoProfesional(pp) || !hayPlazo(plazo)) return ''
  const diferencia = pp.dias - plazo.dias
  if (diferencia === 0) return 'Sin diferencia'
  return `${diferencia > 0 ? '+' : '−'}${textoDias(Math.abs(diferencia))}`
}

/** Lo único del plazo que ve el cliente. Solo un plazo «definido» sale como cifra; sin
 *  definir o por revisar, «Plazo pendiente de definición». Nada del modelo. */
export function plazoDocumento(pp: PlazoProfesional | null | undefined): { pendiente: boolean; texto: string } {
  if (pp && pp.estado === 'definido' && pp.dias !== null) return { pendiente: false, texto: textoDias(pp.dias) }
  return { pendiente: true, texto: 'Plazo pendiente de definición' }
}

/** Mismo rango que el backend y el CHECK de la migración 010. */
export const PLAZO_PROFESIONAL_MIN = 1
export const PLAZO_PROFESIONAL_MAX = 3650
export const ERROR_PLAZO_ESCRITO =
  `El plazo debe ser un número entero de días entre ${PLAZO_PROFESIONAL_MIN} y ${PLAZO_PROFESIONAL_MAX}.`

/** Días escritos: null si está vacío; undefined si no es un entero válido. */
export function leerPlazoEscrito(valor: string | number | null | undefined): number | null | undefined {
  const texto = String(valor ?? '').trim()
  if (texto === '') return null
  if (!/^\d+$/.test(texto)) return undefined
  const dias = Number(texto)
  return dias >= PLAZO_PROFESIONAL_MIN && dias <= PLAZO_PROFESIONAL_MAX ? dias : undefined
}

/** Se puede guardar: valor válido y distinto del ya definido (confirmar uno por revisar sí vale). */
export function puedeGuardarPlazoEscrito(
  valor: string | number | null | undefined,
  pp: PlazoProfesional | null | undefined,
): boolean {
  const dias = leerPlazoEscrito(valor)
  if (typeof dias !== 'number') return false
  return !(pp?.estado === 'definido' && pp.dias === dias)
}

/** Advertencia antes de usar una sugerencia que no está dentro del dominio del modelo;
 *  '' si no hace falta. */
export function advertenciaSugerencia(plazo: PlazoEstimacion | null | undefined): string {
  if (!hayPlazo(plazo) || plazo.estado === 'dentro_dominio') return ''
  const pregunta = '¿Usarla como plazo para la cotización?'
  if (esExtrapolacion(plazo)) return `La sugerencia está fuera del rango histórico del modelo. ${pregunta}`
  if (plazo.estado === 'respaldo') {
    return `La sugerencia es un valor de respaldo: no considera el tamaño de la obra. ${pregunta}`
  }
  if (plazo.estado === 'costo_incompleto') {
    return `La sugerencia se calculó sobre un costo parcial (hay partidas sin precio o sin cantidad). ${pregunta}`
  }
  return `La sugerencia es solo referencial. ${pregunta}`
}

/** «Usar sugerencia»: dentro del dominio no pregunta; fuera del dominio o con el respaldo
 *  pide confirmación con el diálogo de lib/confirmar.ts. true: se puede guardar. */
export async function confirmarSugerencia(
  plazo: PlazoEstimacion | null | undefined,
  pedirConfirmacion: (opciones: OpcionesConfirmacion) => Promise<boolean>,
): Promise<boolean> {
  if (!hayPlazo(plazo)) return false
  const advertencia = advertenciaSugerencia(plazo)
  if (!advertencia) return true
  return pedirConfirmacion({
    rotulo: 'Plazo para la cotización',
    titulo: `¿Usar la sugerencia de ${textoDias(plazo.dias)}?`,
    mensaje: advertencia,
    confirmar: 'Usar sugerencia',
  })
}

/* --- Transparencia ------------------------------------------------------------ */

export interface FilaTransparencia { etiqueta: string; valor: string }

const DOMINIO: Record<EstadoPlazo, string> = {
  dentro_dominio: 'Dentro del rango histórico',
  fuera_rango_costo: 'Fuera del rango histórico',
  tipo_obra_no_representado: 'Fuera del rango histórico',
  costo_incompleto: 'Costo parcial',
  respaldo: 'Valor de respaldo',
  no_disponible: 'No disponible',
}

const MOTIVOS: Record<string, string> = {
  costo_bajo_rango: 'el costo está bajo el rango de los datos históricos',
  costo_sobre_rango: 'el costo supera el rango de los datos históricos',
  tipo_obra_no_representado: 'no hay obras de este tipo en los datos históricos',
  uf_no_disponible: 'no había UF para convertir el costo',
  costo_no_valido: 'el costo no es válido',
  tipo_obra_sin_traduccion: 'tipo de obra sin equivalente en el modelo',
  modelo_no_disponible: 'el modelo no estaba disponible',
  error_estimador: 'error al calcular',
  version_no_registrada: 'versión del modelo no registrada',
  anterior_al_modelo: 'estimación anterior al modelo',
  simulacion: 'modo demostración',
}

const METODOS: Record<string, string> = {
  P2: 'Regla paramétrica P2 sobre el costo total en UF y la clase de obra',
  mediana_respaldo: 'Mediana de respaldo (no considera el tamaño de la obra)',
}

const ESTADOS_MODELO: Record<string, string> = {
  provisional: 'Provisional', validado: 'Validado', retirado: 'Retirado',
}

/** Bloque «Modelo» de Transparencia: trazabilidad completa de la sugerencia. Uso interno. */
export function filasTransparenciaModelo(plazo: PlazoEstimacion | null | undefined): FilaTransparencia[] {
  const motivo = plazo?.motivo ? MOTIVOS[plazo.motivo] ?? plazo.motivo : ''
  const dominio = plazo ? DOMINIO[plazo.estado] ?? plazo.estado : DOMINIO.no_disponible
  const estadoModelo = plazo?.estadoModelo
    ? ESTADOS_MODELO[plazo.estadoModelo] ?? plazo.estadoModelo
    : plazo?.provisional ? 'Provisional' : '—'
  const sugerido = hayPlazo(plazo)
    ? textoDias(plazo.dias) + (esReferencial(plazo) ? ' (referencial)' : '')
    : 'No disponible'
  const rango = hayPlazo(plazo) && plazo.minDias !== null && plazo.maxDias !== null
    ? `${plazo.minDias}–${plazo.maxDias} días` : '—'
  return [
    { etiqueta: 'Plazo sugerido', valor: sugerido },
    { etiqueta: 'Rango referencial de esta estimación', valor: rango },
    { etiqueta: 'Error medio observado del modelo', valor: textoErrorMedio(plazo) || '—' },
    { etiqueta: 'Versión del modelo', valor: plazo?.versionModelo ?? '—' },
    { etiqueta: 'Estado del modelo', valor: hayPlazo(plazo) ? estadoModelo : '—' },
    { etiqueta: 'Dominio', valor: motivo ? `${dominio}: ${motivo}` : dominio },
    { etiqueta: 'Método', valor: plazo?.metodo ? METODOS[plazo.metodo] ?? plazo.metodo : '—' },
  ]
}

/** Bloque «Profesional» de Transparencia. La diferencia, solo si existen ambos. */
export function filasTransparenciaProfesional(
  pp: PlazoProfesional | null | undefined,
  plazo: PlazoEstimacion | null | undefined,
): FilaTransparencia[] {
  const p = pp ?? profesionalSinDefinir()
  const presentacion = presentarPlazoProfesional(p)
  const autor = p.usuarioNombre ?? (p.usuarioId ? 'Usuario sin cuenta' : '—')
  const filas: FilaTransparencia[] = [
    { etiqueta: 'Plazo para la cotización', valor: presentacion.texto },
    { etiqueta: 'Estado', valor: presentacion.estadoTexto },
    { etiqueta: 'Origen', valor: presentacion.origenTexto || '—' },
    { etiqueta: 'Fecha de definición', valor: p.fecha ? fechaHora(p.fecha) : '—' },
    { etiqueta: 'Definido por', valor: hayPlazoProfesional(p) ? autor : '—' },
  ]
  const diferencia = diferenciaConSugerencia(p, plazo)
  if (diferencia) filas.push({ etiqueta: 'Diferencia respecto de la sugerencia', valor: diferencia })
  return filas
}

/* --- Cronograma ------------------------------------------------------------- */

/** profesional: plazo para la cotización definido; por_revisar: el mismo, pendiente de
 *  revisar tras recalcular; sugerencia: el del modelo, como distribución interna. */
export type FuenteCronograma = 'profesional' | 'por_revisar' | 'sugerencia' | null

/** Qué plazo reparte el cronograma: el del profesional si existe; si no, la sugerencia. */
export function fuenteCronograma(
  plazo: PlazoEstimacion | null | undefined,
  profesional?: PlazoProfesional | null,
): { fuente: FuenteCronograma; dias: number } {
  if (hayPlazoProfesional(profesional)) {
    return { fuente: profesional.estado === 'por_revisar' ? 'por_revisar' : 'profesional', dias: profesional.dias }
  }
  if (hayPlazo(plazo)) return { fuente: 'sugerencia', dias: plazo.dias }
  return { fuente: null, dias: 0 }
}

/** Rótulo que dice siempre qué plazo se reparte. */
export function rotuloCronograma(
  plazo: PlazoEstimacion | null | undefined,
  profesional?: PlazoProfesional | null,
): string {
  const { fuente, dias } = fuenteCronograma(plazo, profesional)
  if (fuente === 'profesional') return `Basado en el plazo para la cotización: ${textoDias(dias)}`
  if (fuente === 'por_revisar') {
    return `Basado en el plazo para la cotización (${textoDias(dias)}), por revisar tras recalcular`
  }
  if (fuente === 'sugerencia') return 'Distribución referencial interna con el plazo sugerido por el modelo'
  return ''
}

/** Por qué no se reparte el plazo en etapas; '' si se puede. */
export function bloqueoCronograma(
  completa: boolean,
  plazo: PlazoEstimacion | null | undefined,
  profesional?: PlazoProfesional | null,
): string {
  if (!completa) return 'incompleta'
  if (fuenteCronograma(plazo, profesional).fuente === null) return 'sin_plazo'
  return ''
}

/** El cronograma reparte el plazo: solo con estimación completa y con algún plazo. */
export function diasParaCronograma(
  plazo: PlazoEstimacion | null | undefined,
  completa = true,
  profesional?: PlazoProfesional | null,
): number {
  return bloqueoCronograma(completa, plazo, profesional) === '' ? fuenteCronograma(plazo, profesional).dias : 0
}

/** El plazo lo guarda el backend con cada estimación; el navegador no lo calcula. Una
 *  estimación sin plazo profesional (anterior a la 010) queda sin definir. */
export function conPlazo(estimacion: Estimacion): Estimacion {
  if (estimacion.plazo && estimacion.plazoProfesional) return estimacion
  return {
    ...estimacion,
    plazo: estimacion.plazo ?? plazoNoDisponible('anterior_al_modelo'),
    plazoProfesional: estimacion.plazoProfesional ?? profesionalSinDefinir(),
  }
}

/** Plazo no calculado (estimaciones de demostración o anteriores al modelo). */
export function plazoNoDisponible(motivo: string): PlazoEstimacion {
  return {
    dias: null, minDias: null, maxDias: null, metodo: null, estado: 'no_disponible', fueraDominio: true,
    provisional: null, motivo, versionModelo: null, tipoObraModelo: null, ufValor: null, ufFecha: null,
    errorMedioDias: null, estadoModelo: null,
  }
}
