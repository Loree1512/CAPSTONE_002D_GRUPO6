import { ErrorApi } from './errores.ts'
import { pesos } from './formato.ts'
import { etiquetaRol } from './miembros.ts'
import { ESTANDARES } from './catalogos.ts'
import type { EventoHistorial } from '../tipos/api.ts'

/** Un dato modificado. Sin `anterior` se muestra solo el valor (eventos antiguos sin ese dato). */
export interface CambioHistorial {
  campo: string
  anterior: string | null
  nuevo: string
}

export interface EntradaHistorial {
  id: string
  autor: string
  texto: string
  cambios: CambioHistorial[]
  fecha: string
}

export interface OpcionesHistorial {
  /** usuario_id → nombre de los miembros actuales. */
  nombres?: Record<string, string>
  /** id de categoría → nombre, para partidas que cambian de categoría. */
  categorias?: Record<number, string>
}

export const DESCRIPCION_GENERICA = 'Se actualizó el proyecto.'

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

/** "20 oct 2026 · 15:20", en la hora local. */
export function fechaEvento(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  const dos = (n: number) => String(n).padStart(2, '0')
  return `${d.getDate()} ${MESES[d.getMonth()]} ${d.getFullYear()} · ${dos(d.getHours())}:${dos(d.getMinutes())}`
}

// Solo texto o número: cualquier otra cosa no se muestra.
function texto(valor: unknown): string | undefined {
  if (typeof valor === 'string') return valor.trim() || undefined
  if (typeof valor === 'number' && Number.isFinite(valor)) return String(valor)
  return undefined
}

function campos(valores: Record<string, unknown> | null | undefined): Record<string, unknown> {
  return valores && typeof valores === 'object' && !Array.isArray(valores) ? valores : {}
}

/* --- Datos modificados: nombre entendible y formato de cada valor ---------- */

type Formato = 'texto' | 'pesos' | 'm2' | 'entero' | 'cantidad' | 'porcentaje' | 'estandar' | 'rol' | 'booleano' | 'categoria'

interface Campo {
  etiqueta: string
  formato: Formato
  /** Qué significa que el valor esté vacío; por defecto «Sin definir». */
  vacio?: string
}

const CAMPOS: Record<string, Campo> = {
  // Proyecto
  nombre: { etiqueta: 'Nombre', formato: 'texto' },
  comuna: { etiqueta: 'Comuna', formato: 'texto' },
  tipo_obra: { etiqueta: 'Tipo de obra', formato: 'texto' },
  materialidad: { etiqueta: 'Materialidad', formato: 'texto' },
  superficie_m2: { etiqueta: 'Superficie', formato: 'm2' },
  numero_pisos: { etiqueta: 'Número de pisos', formato: 'entero' },
  estandar_terminaciones: { etiqueta: 'Estándar de terminaciones', formato: 'estandar' },
  estado: { etiqueta: 'Estado', formato: 'texto' },
  // Partida
  unidad: { etiqueta: 'Unidad', formato: 'texto' },
  categoria_id: { etiqueta: 'Categoría', formato: 'categoria' },
  cantidad: { etiqueta: 'Cantidad', formato: 'cantidad' },
  precio_unitario_override: { etiqueta: 'Precio unitario', formato: 'pesos', vacio: 'Precio del banco' },
  observacion: { etiqueta: 'Observación', formato: 'texto', vacio: 'Sin observación' },
  // Estimación
  costo_total: { etiqueta: 'Costo total', formato: 'pesos' },
  costo_m2: { etiqueta: 'Costo por m²', formato: 'pesos' },
  gastos_generales_pct: { etiqueta: 'Gastos generales', formato: 'porcentaje' },
  utilidad_pct: { etiqueta: 'Utilidad', formato: 'porcentaje' },
  completa: { etiqueta: 'Estimación completa', formato: 'booleano' },
  observaciones: { etiqueta: 'Observaciones', formato: 'texto', vacio: 'Sin observaciones' },
  // Miembros
  rol: { etiqueta: 'Rol', formato: 'rol' },
}

const NUMERO = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 2 })

// La base devuelve numeric como número o como texto ("20.5").
function numero(valor: unknown): number | undefined {
  const n = typeof valor === 'number' ? valor : typeof valor === 'string' && valor.trim() !== '' ? Number(valor) : NaN
  return Number.isFinite(n) ? n : undefined
}

const vacio = (valor: unknown) => valor === null || valor === undefined || valor === ''

/** Valor listo para mostrar; undefined si no se puede mostrar sin inventar. */
export function formatearValor(clave: string, valor: unknown, opciones: OpcionesHistorial = {}): string | undefined {
  const campo = CAMPOS[clave]
  if (!campo) return undefined
  if (vacio(valor)) return campo.vacio ?? 'Sin definir'
  const n = numero(valor)
  switch (campo.formato) {
    case 'pesos': return n === undefined ? undefined : pesos(n)
    case 'm2': return n === undefined ? undefined : `${NUMERO.format(n)} m²`
    case 'entero': return n === undefined ? undefined : NUMERO.format(Math.round(n))
    case 'cantidad': return n === undefined ? undefined : NUMERO.format(n)
    case 'porcentaje': return n === undefined ? undefined : `${NUMERO.format(n)} %`
    case 'booleano': return typeof valor === 'boolean' ? (valor ? 'Sí' : 'No') : undefined
    case 'rol': return etiquetaRol(valor)
    case 'estandar': {
      const v = texto(valor)
      return v === undefined ? undefined : ESTANDARES.find((e) => e.valor === v)?.etiqueta ?? v
    }
    case 'categoria':
      return n === undefined ? undefined : opciones.categorias?.[n] ?? `Categoría ${n}`
    default: return texto(valor)
  }
}

/** Cada dato modificado con su valor anterior y nuevo; solo los que realmente cambiaron. */
function modificados(e: EventoHistorial, opciones: OpcionesHistorial, ignorar: string[] = []): CambioHistorial[] {
  const antes = campos(e.valores_anteriores)
  const despues = campos(e.valores_nuevos)
  const claves = [...new Set([...Object.keys(antes), ...Object.keys(despues)])]
    .filter((k) => k in CAMPOS && !ignorar.includes(k))
  const cambios: CambioHistorial[] = []
  for (const clave of claves) {
    const anterior = formatearValor(clave, antes[clave], opciones)
    const nuevo = formatearValor(clave, despues[clave], opciones)
    if (anterior === undefined || nuevo === undefined || anterior === nuevo) continue
    cambios.push({ campo: CAMPOS[clave].etiqueta, anterior, nuevo })
  }
  return cambios
}

/** "Instalación de faenas · Cantidad 1 gl"; undefined si no hay nombre guardado. */
function resumenPartida(valores: Record<string, unknown>): string | undefined {
  const nombre = texto(valores.nombre)
  if (!nombre) return undefined
  const cantidad = numero(valores.cantidad)
  if (cantidad === undefined) return nombre
  const unidad = texto(valores.unidad)
  return `${nombre} · Cantidad ${NUMERO.format(cantidad)}${unidad ? ' ' + unidad : ''}`
}

/* --- Descripción de cada acción ----------------------------------------------- */

const ORIGENES_PLAZO: Record<string, string> = {
  sugerencia: 'Sugerencia de BuildCast',
  manual: 'Escrito por el profesional',
}

const diasTexto = (dias: number) => `${NUMERO.format(dias)} días`

type Descripcion = { texto?: string; cambios?: CambioHistorial[] }
type Descriptor = (e: EventoHistorial, opciones: OpcionesHistorial) => Descripcion

function persona(e: EventoHistorial, nombres: Record<string, string> = {}): string {
  const valores = { ...campos(e.valores_anteriores), ...campos(e.valores_nuevos) }
  return (e.entidad_id && nombres[e.entidad_id]) || texto(valores.email) || 'un miembro'
}

const DESCRIPTORES: Record<string, Descriptor> = {
  miembro_agregado: (e, o) => {
    const rol = etiquetaRol(campos(e.valores_nuevos).rol)
    return {
      texto: `Agregó a ${persona(e, o.nombres)} al proyecto`,
      cambios: rol ? [{ campo: 'Rol', anterior: 'No pertenecía al proyecto', nuevo: rol }] : [],
    }
  },

  miembro_rol_cambiado: (e, o) => ({
    texto: `Cambió el rol de ${persona(e, o.nombres)}`,
    cambios: modificados(e, o, ['email', 'usuario_id']),
  }),

  miembro_eliminado: (e, o) => {
    const rol = etiquetaRol(campos(e.valores_anteriores).rol)
    return {
      texto: `Quitó a ${persona(e, o.nombres)} del proyecto`,
      cambios: rol ? [{ campo: 'Rol', anterior: rol, nuevo: 'Ya no pertenece al proyecto' }] : [],
    }
  },

  proyecto_editado: (e, o) => ({ texto: 'Editó el proyecto', cambios: modificados(e, o) }),

  // Solo la observación: los montos no cambian.
  cotizacion_actualizada: (e, o) => ({
    texto: 'Actualizó las observaciones de la cotización',
    cambios: modificados(e, o),
  }),

  partida_agregada: (e) => {
    const nombre = texto(campos(e.valores_nuevos).nombre)
    const resumen = resumenPartida(campos(e.valores_nuevos))
    return {
      texto: nombre ? `Agregó la partida «${nombre}»` : 'Agregó una partida al proyecto',
      cambios: resumen ? [{ campo: 'Partida', anterior: 'No existía', nuevo: resumen }] : [],
    }
  },

  partida_editada: (e, o) => {
    const antes = campos(e.valores_anteriores)
    const nombre = texto(campos(e.valores_nuevos).nombre) ?? texto(antes.nombre)
    // El nombre viaja siempre en valores_nuevos para identificar la partida: solo es un
    // cambio si también está entre los anteriores.
    const ignorar = 'nombre' in antes ? [] : ['nombre']
    return {
      texto: nombre ? `Editó la partida «${nombre}»` : 'Editó una partida',
      cambios: modificados(e, o, ignorar),
    }
  },

  partida_eliminada: (e) => {
    const nombre = texto(campos(e.valores_anteriores).nombre)
    const resumen = resumenPartida(campos(e.valores_anteriores))
    return {
      texto: nombre ? `Eliminó la partida «${nombre}»` : 'Eliminó una partida del proyecto',
      cambios: resumen ? [{ campo: 'Partida', anterior: resumen, nuevo: 'Eliminada' }] : [],
    }
  },

  plantilla_aplicada: (e) => {
    const nuevos = campos(e.valores_nuevos)
    const nombre = texto(nuevos.nombre)
    const antes = numero(campos(e.valores_anteriores).partidas)
    const despues = numero(nuevos.partidas)
    const plantilla = nombre ? `la plantilla «${nombre}»` : 'una plantilla'
    return {
      texto: antes ? `Reemplazó las partidas con ${plantilla}` : `Aplicó ${plantilla}`,
      // Sin anteriores guardados el proyecto no tenía partidas: la API exige confirmar el reemplazo.
      cambios: despues === undefined ? [] : [{
        campo: 'Partidas',
        anterior: antes ? NUMERO.format(antes) : 'Sin partidas',
        nuevo: NUMERO.format(despues),
      }],
    }
  },

  // Plazo para la cotización: solo los días y el origen; nada técnico del modelo.
  plazo_profesional_definido: (e) => {
    const antes = campos(e.valores_anteriores)
    const nuevos = campos(e.valores_nuevos)
    const nuevo = numero(nuevos.plazo_profesional_dias)
    if (nuevo === undefined) return { texto: 'Definió el plazo para la cotización' }
    const previo = numero(antes.plazo_profesional_dias)
    const estadoPrevio = texto(antes.plazo_profesional_estado)
    const origen = ORIGENES_PLAZO[texto(nuevos.plazo_profesional_origen) ?? '']
    const cambios: CambioHistorial[] = origen ? [{ campo: 'Origen', anterior: null, nuevo: origen }] : []
    if (previo === undefined || estadoPrevio === 'sin_definir') {
      return { texto: `Plazo para cotización definido: ${diasTexto(nuevo)}`, cambios }
    }
    if (previo === nuevo) {
      // Sale de «por revisar» con el mismo valor.
      return { texto: `Plazo para cotización confirmado: ${diasTexto(nuevo)}`, cambios }
    }
    return {
      texto: `Plazo para cotización actualizado: ${NUMERO.format(previo)} → ${diasTexto(nuevo)}`,
      cambios,
    }
  },

  // Un recálculo cambió el presupuesto después de que el profesional definió el plazo.
  plazo_profesional_por_revisar: (e) => {
    const dias = numero(campos(e.valores_nuevos).plazo_profesional_dias)
      ?? numero(campos(e.valores_anteriores).plazo_profesional_dias)
    if (dias === undefined) return { texto: 'Plazo para cotización por revisar tras recalcular' }
    return {
      texto: `Plazo para cotización por revisar tras recalcular: ${diasTexto(dias)}`,
      cambios: [{ campo: 'Plazo para la cotización', anterior: 'Definido', nuevo: 'Por revisar' }],
    }
  },

  estimacion_generada: (e, o) => {
    const anteriores = e.valores_anteriores
    const nuevo = formatearValor('costo_total', campos(e.valores_nuevos).costo_total, o)
    let cambios: CambioHistorial[] = []
    if (nuevo !== undefined && !vacio(campos(e.valores_nuevos).costo_total)) {
      if (!anteriores || typeof anteriores !== 'object') {
        // Evento anterior a guardar el costo previo: solo el nuevo, sin inventar el anterior.
        cambios = [{ campo: 'Costo total', anterior: null, nuevo }]
      } else {
        const previo = campos(anteriores).costo_total
        cambios = [{
          campo: 'Costo total',
          anterior: vacio(previo) ? 'Sin estimación previa' : formatearValor('costo_total', previo, o) ?? 'Sin definir',
          nuevo,
        }]
      }
    }
    const recalculo = anteriores && !vacio(campos(anteriores).costo_total)
    return { texto: recalculo ? 'Recalculó la estimación' : 'Generó una nueva estimación', cambios }
  },
}

/** Texto para el usuario. Acepta el mapa de nombres directamente, como antes. */
export function describirEvento(
  e: EventoHistorial,
  opciones: OpcionesHistorial | Record<string, string> = {},
): EntradaHistorial {
  const o: OpcionesHistorial = 'nombres' in opciones || 'categorias' in opciones
    ? opciones as OpcionesHistorial
    : { nombres: opciones as Record<string, string> }
  let descripcion: Descripcion = {}
  try {
    descripcion = DESCRIPTORES[e.accion]?.(e, o) ?? {}
  } catch {
    descripcion = {}
  }
  return {
    id: e.id,
    autor: texto(e.usuario_nombre) ?? texto(e.usuario_email) ?? 'Usuario sin cuenta',
    texto: descripcion.texto ?? DESCRIPCION_GENERICA,
    cambios: descripcion.cambios ?? [],
    fecha: fechaEvento(e.fecha),
  }
}

export function mensajeHistorial(e: unknown): string {
  if (e instanceof ErrorApi) {
    if (e.estado === 0) return 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo nuevamente.'
    if (e.estado === 401) return 'Tu sesión expiró. Vuelve a iniciar sesión.'
    if (e.estado === 403 || e.estado === 404) return 'No tienes acceso al historial de este proyecto.'
  }
  return 'No se pudo cargar el historial. Inténtalo nuevamente.'
}

export interface Historial {
  eventos: EventoHistorial[]
  cargando: boolean
  cargado: boolean
  error: string
  cargar(): Promise<void>
}

export function crearHistorial(listar: () => Promise<EventoHistorial[]>): Historial {
  return {
    eventos: [],
    cargando: false,
    cargado: false,
    error: '',

    async cargar() {
      if (this.cargando) return
      this.cargando = true
      this.error = ''
      try {
        this.eventos = await listar()
        this.cargado = true
      } catch (e) {
        this.error = mensajeHistorial(e)
      } finally {
        this.cargando = false
      }
    },
  }
}
