import type {
  CierreObra,
  CategoriaPartida,
  FilaBanco,
  Partida,
  PartidaEditada,
  PartidaNueva,
  PartidaProyecto,
  PartidaProyectoEditada,
  PartidaProyectoNueva,
  PartidasProyecto,
  PlantillaDetalle,
  PlantillaNueva,
  PlantillaResumen,
  PrecioEditado,
  Proyecto,
  ProyectoNuevo,
  RespuestaRegistro,
  RespuestaSesion,
  Usuario,
  VersionPrecios,
} from '../tipos/api'
import type { Estimacion, EstimacionResumen, OpcionesEstimacion } from '../tipos/estimacion'
import type { Configuracion } from './configuracion'
import { cerrar, token } from './sesion'
import { ErrorApi } from './errores'

const BASE = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

/** FastAPI devuelve el detalle en `detail`, como texto o como lista de
 *  errores de validación de Pydantic. Se normaliza a una sola frase. */
function mensajeDeError(cuerpo: unknown, estado: number): string {
  if (cuerpo && typeof cuerpo === 'object' && 'detail' in cuerpo) {
    const detalle = (cuerpo as { detail: unknown }).detail
    if (typeof detalle === 'string') return detalle
    if (Array.isArray(detalle) && detalle.length > 0) {
      const primero = detalle[0] as { msg?: string }
      if (primero?.msg) return primero.msg
    }
  }
  if (estado >= 500) return 'La API no está respondiendo. Revisa que esté levantada.'
  return `La solicitud falló (${estado}).`
}

interface Opciones {
  metodo?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  cuerpo?: unknown
  autenticado?: boolean
}

async function pedir<T>(ruta: string, opciones: Opciones = {}): Promise<T> {
  const { metodo = 'GET', cuerpo, autenticado = true } = opciones
  const cabeceras: Record<string, string> = { Accept: 'application/json' }

  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json'

  if (autenticado) {
    const t = token()
    if (t) cabeceras['Authorization'] = `Bearer ${t}`
  }

  let respuesta: Response
  try {
    respuesta = await fetch(`${BASE}${ruta}`, {
      method: metodo,
      headers: cabeceras,
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    })
  } catch {
    throw new ErrorApi(0, 'No se pudo conectar con la API. Revisa la URL y el CORS.')
  }

  if (respuesta.status === 401 && autenticado) {
    cerrar()
    window.location.replace('/acceso.html')
    throw new ErrorApi(401, 'La sesión expiró.')
  }

  const texto = await respuesta.text()
  const datos: unknown = texto ? JSON.parse(texto) : null

  if (!respuesta.ok) throw new ErrorApi(respuesta.status, mensajeDeError(datos, respuesta.status))

  return datos as T
}

/* ── Mapeos entre el contrato de FastAPI y las formas que ya usa el
   frontend (paginas/*.ts, catalogos.ts). Se traduce sólo acá para no
   tocar la UI existente. ─────────────────────────────────────────── */

interface UsuarioBackend {
  id: string
  email: string
}

function aUsuarioFrontend(u: UsuarioBackend): Usuario {
  return { id: u.id, correo: u.email }
}

interface ProyectoBackend {
  id: string
  nombre: string
  comuna: string
  tipo_obra: string
  materialidad: string
  superficie_m2: number
  numero_pisos: number
  estandar_terminaciones: Proyecto['estandar_terminaciones']
  usuario_id: string | null
  /** Campo propio de la tabla ("borrador"); no dice si hay estimación. */
  estado: string
  fecha_creacion: string
  fecha_actualizacion: string
  // Resumen de la última estimación, derivado en el backend.
  ultima_estimacion_id: string | null
  costo_total: number | null
  costo_m2: number | null
  fecha_estimacion: string | null
  estado_estimacion: 'sin_estimar' | 'vigente' | 'recalcular'
  plazo_dias: number | null
}

function aProyectoFrontend(p: ProyectoBackend): Proyecto {
  return {
    id: p.id,
    nombre: p.nombre,
    comuna: p.comuna,
    tipo_obra: p.tipo_obra,
    material: p.materialidad,
    superficie_m2: p.superficie_m2,
    pisos: p.numero_pisos,
    estandar_terminaciones: p.estandar_terminaciones,
    // El estado visible es el de la estimación, no el "borrador" de la tabla.
    estado: p.estado_estimacion ?? 'sin_estimar',
    ultima_estimacion_id: p.ultima_estimacion_id ?? null,
    costo_total: p.costo_total ?? null,
    costo_m2: p.costo_m2 ?? null,
    fecha_estimacion: p.fecha_estimacion ?? null,
    plazo_dias: p.plazo_dias ?? null,
    creado_en: p.fecha_creacion,
    actualizado_en: p.fecha_actualizacion,
  }
}

function aProyectoBackend(datos: ProyectoNuevo) {
  return {
    nombre: datos.nombre,
    comuna: datos.comuna,
    tipo_obra: datos.tipo_obra,
    materialidad: datos.material,
    superficie_m2: datos.superficie_m2,
    numero_pisos: datos.pisos,
    estandar_terminaciones: datos.estandar_terminaciones,
  }
}

export const apiReal = {
  iniciarSesion: (correo: string, clave: string) =>
    pedir<RespuestaSesion>('/autenticacion/iniciar-sesion', {
      metodo: 'POST',
      cuerpo: { email: correo, password: clave },
      autenticado: false,
    }),

  registrar: (correo: string, clave: string) =>
    pedir<RespuestaRegistro>('/autenticacion/registro', {
      metodo: 'POST',
      cuerpo: { email: correo, password: clave },
      autenticado: false,
    }),

  reenviarConfirmacion: (correo: string) =>
    pedir<{ mensaje?: string }>('/autenticacion/reenviar-confirmacion', {
      metodo: 'POST',
      cuerpo: { email: correo },
      autenticado: false,
    }),

  yo: () => pedir<UsuarioBackend>('/autenticacion/yo').then(aUsuarioFrontend),

  listarProyectos: () =>
    pedir<ProyectoBackend[]>('/proyectos').then((proyectos) => proyectos.map(aProyectoFrontend)),

  crearProyecto: (datos: ProyectoNuevo) =>
    pedir<ProyectoBackend>('/proyectos', { metodo: 'POST', cuerpo: aProyectoBackend(datos) }).then(
      aProyectoFrontend,
    ),

  obtenerProyecto: (id: string) =>
    pedir<ProyectoBackend>(`/proyectos/${id}`).then(aProyectoFrontend),

  actualizarProyecto: (id: string, datos: ProyectoNuevo) =>
    pedir<ProyectoBackend>(`/proyectos/${id}`, {
      metodo: 'PUT',
      cuerpo: aProyectoBackend(datos),
    }).then(aProyectoFrontend),

  /** Cierre real de obra: alimenta el conjunto de entrenamiento (HU-22). */
  registrarCierreObra: (proyectoId: string, datos: CierreObra) =>
    pedir<CierreObra>(`/proyectos/${proyectoId}/obra-ejecutada`, {
      metodo: 'POST',
      cuerpo: datos,
    }),

  // --- Banco de precios ---------------------------------------------

  listarCategorias: () =>
    pedir<CategoriaPartida[]>('/banco/categorias'),

  listarVersiones: () =>
    pedir<VersionPrecios[]>('/banco/versiones'),

  crearVersion: (version: string, copiarDe?: string) =>
    pedir<VersionPrecios>('/banco/versiones', {
      metodo: 'POST',
      cuerpo: { version, copiar_de: copiarDe ?? null },
    }),

  publicarVersion: (id: string) =>
    pedir<VersionPrecios>(`/banco/versiones/${id}/publicar`, {
      metodo: 'POST',
    }),

  /** Partidas con su precio en la versión indicada; sin id, la vigente. */
  listarBanco: (versionId?: string) =>
    pedir<FilaBanco[]>(
      `/banco/partidas${versionId ? `?version=${versionId}` : ''}`,
    ),

  crearPartida: (datos: PartidaNueva) =>
    pedir<Partida>('/banco/partidas', {
      metodo: 'POST',
      cuerpo: datos,
    }),

  /** Edita nombre, unidad o categoría. El código no cambia. */
  editarPartida: (id: string, datos: PartidaEditada) =>
    pedir<Partida>(`/banco/partidas/${id}`, {
      metodo: 'PUT',
      cuerpo: datos,
    }),

  /** Da de baja una partida: nunca se borra, para no romper estimaciones. */
  darDeBajaPartida: (id: string) =>
    pedir<Partida>(`/banco/partidas/${id}/baja`, {
      metodo: 'POST',
    }),

  guardarPrecio: (
    versionId: string,
    partidaId: string,
    datos: PrecioEditado,
  ) =>
    pedir<FilaBanco>(
      `/banco/versiones/${versionId}/precios/${partidaId}`,
      {
        metodo: 'PUT',
        cuerpo: datos,
      },
    ),

  // --- Partidas del proyecto -----------------------------------------

  listarPartidasProyecto: (proyectoId: string) =>
    pedir<PartidasProyecto>(`/proyectos/${proyectoId}/partidas`),

  crearPartidaProyecto: (proyectoId: string, datos: PartidaProyectoNueva) =>
    pedir<PartidaProyecto>(`/proyectos/${proyectoId}/partidas`, {
      metodo: 'POST',
      cuerpo: datos,
    }),

  editarPartidaProyecto: (proyectoId: string, id: string, datos: PartidaProyectoEditada) =>
    pedir<PartidaProyecto>(`/proyectos/${proyectoId}/partidas/${id}`, {
      metodo: 'PUT',
      cuerpo: datos,
    }),

  eliminarPartidaProyecto: (proyectoId: string, id: string) =>
    pedir<null>(`/proyectos/${proyectoId}/partidas/${id}`, { metodo: 'DELETE' }),

  /** ids: todas las partidas del proyecto en el nuevo orden. */
  ordenarPartidasProyecto: (proyectoId: string, ids: string[]) =>
    pedir<PartidaProyecto[]>(`/proyectos/${proyectoId}/partidas/ordenar`, {
      metodo: 'POST',
      cuerpo: { ids },
    }),

  /** Sin plantillaId usa la que corresponde al proyecto. Con partidas
   *  existentes, responde 409 salvo que reemplazar sea true. */
  aplicarPlantilla: (proyectoId: string, plantillaId: string | null, reemplazar: boolean) =>
    pedir<PartidasProyecto>(`/proyectos/${proyectoId}/partidas/aplicar-plantilla`, {
      metodo: 'POST',
      cuerpo: { plantilla_id: plantillaId, reemplazar },
    }),

  // --- Plantillas -------------------------------------------------------

  listarPlantillas: () =>
    pedir<PlantillaResumen[]>('/plantillas'),

  obtenerPlantilla: (id: string) =>
    pedir<PlantillaDetalle>(`/plantillas/${id}`),

  crearPlantilla: (datos: PlantillaNueva) =>
    pedir<PlantillaDetalle>('/plantillas', { metodo: 'POST', cuerpo: datos }),

  editarPlantilla: (id: string, datos: Partial<PlantillaNueva>) =>
    pedir<PlantillaDetalle>(`/plantillas/${id}`, { metodo: 'PUT', cuerpo: datos }),

  /** Lista completa en orden: agrega, quita y reordena de una vez. */
  guardarPartidasPlantilla: (id: string, partidas: { partida_id: string; cantidad_sugerida: number | null }[]) =>
    pedir<PlantillaDetalle>(`/plantillas/${id}/partidas`, { metodo: 'PUT', cuerpo: { partidas } }),

  // --- Estimaciones -------------------------------------------------

  /** Calcula y guarda una estimación nueva. Sin opciones: versión vigente
   *  y porcentajes de la configuración. */
  crearEstimacion: (proyectoId: string, opciones: OpcionesEstimacion = {}) =>
    pedir<Estimacion>(`/proyectos/${proyectoId}/estimaciones`, {
      metodo: 'POST',
      cuerpo: opciones,
    }),

  /** Historial del proyecto, la más reciente primero. */
  listarEstimaciones: (proyectoId: string) =>
    pedir<EstimacionResumen[]>(`/proyectos/${proyectoId}/estimaciones`),

  obtenerEstimacion: (proyectoId: string, estimacionId: string) =>
    pedir<Estimacion>(`/proyectos/${proyectoId}/estimaciones/${estimacionId}`),

  // --- Configuración del cálculo --------------------------------------

  obtenerConfiguracion: () =>
    pedir<Configuracion>('/configuracion'),

  guardarConfiguracion: (configuracion: Configuracion) =>
    pedir<Configuracion>('/configuracion', {
      metodo: 'PUT',
      cuerpo: configuracion,
    }),
}