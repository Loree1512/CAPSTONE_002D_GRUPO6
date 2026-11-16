import type {
  CandidatoMiembro,
  CierreObra,
  CategoriaPartida,
  EventoHistorial,
  FilaBanco,
  MiembroProyecto,
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
  RolAsignable,
  RolProyecto,
  RespuestaRegistro,
  RespuestaSesion,
  Usuario,
  VersionPrecios,
} from '../tipos/api'
import type {
  DefinirPlazoProfesional, Estimacion, EstimacionResumen, OpcionesEstimacion,
} from '../tipos/estimacion'
import type {
  ConfiguracionAdministracion, SolicitudAdministrador, UsuarioAdministrado, UsuarioCreado, UsuarioNuevo,
} from '../tipos/administracion'
import type { Configuracion } from './configuracion'
import type { UfVigente } from './uf'
import { cerrar, guardar, refresco, token } from './sesion'
import { crearCliente } from './http'

const BASE = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

// Clasificación de errores y renovación de sesión: ver http.ts.
const { pedir } = crearCliente({
  base: BASE,
  sesion: { token, refresco, guardar, cerrar },
  alCerrarSesion: () => window.location.replace('/acceso.html'),
  // Invitación sin contraseña: acceso.html muestra «Crea tu contraseña».
  alAccesoPendiente: () => window.location.replace('/acceso.html'),
})

/* ── Mapeos entre el contrato de FastAPI y las formas que ya usa el
   frontend (paginas/*.ts, catalogos.ts). Se traduce sólo acá para no
   tocar la UI existente. ─────────────────────────────────────────── */

interface UsuarioBackend {
  id: string
  email: string
  rol_global?: string
  es_administrador_principal?: boolean
  nombre?: string | null
  acceso_configurado?: boolean
}

function aUsuarioFrontend(u: UsuarioBackend): Usuario {
  return {
    id: u.id,
    correo: u.email,
    nombre: u.nombre ?? undefined,
    rol: u.rol_global,
    esAdministradorPrincipal: u.es_administrador_principal ?? false,
    // Un backend anterior a la migración 008 no lo informa: no bloquea a nadie.
    accesoConfigurado: u.acceso_configurado ?? true,
  }
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
  plazo_estado?: string | null
  plazo_motivo?: string | null
  plazo_profesional_dias?: number | null
  plazo_profesional_estado?: string | null
  mi_rol: RolProyecto
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
    plazo_estado: p.plazo_estado ?? null,
    plazo_motivo: p.plazo_motivo ?? null,
    plazo_profesional_dias: p.plazo_profesional_dias ?? null,
    plazo_profesional_estado: p.plazo_profesional_estado ?? null,
    creado_en: p.fecha_creacion,
    actualizado_en: p.fecha_actualizacion,
    mi_rol: p.mi_rol ?? null,
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

  /** Primera contraseña de un usuario invitado; usa la sesión que trae el enlace. */
  establecerContrasena: (clave: string) =>
    pedir<{ mensaje: string }>('/autenticacion/establecer-contrasena', {
      metodo: 'POST',
      cuerpo: { password: clave },
    }),

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

  /** Solo el propietario; responde 204. */
  eliminarProyecto: (id: string) =>
    pedir<null>(`/proyectos/${id}`, { metodo: 'DELETE' }).then(() => undefined),

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

  /** Solo cambia la observación: nueva estimación con los mismos montos. */
  actualizarCotizacion: (proyectoId: string, estimacionId: string, observaciones: string | null) =>
    pedir<Estimacion>(`/proyectos/${proyectoId}/estimaciones/${estimacionId}/actualizar-cotizacion`, {
      metodo: 'POST',
      cuerpo: { observaciones },
    }),

  /** Plazo para la cotización: un valor escrito o la sugerencia del modelo. Nueva
   *  estimación con los mismos montos y la misma sugerencia (no recalcula). */
  definirPlazoProfesional: (proyectoId: string, estimacionId: string, cuerpo: DefinirPlazoProfesional) =>
    pedir<Estimacion>(`/proyectos/${proyectoId}/estimaciones/${estimacionId}/plazo-profesional`, {
      metodo: 'POST',
      cuerpo,
    }),

  // --- Miembros e historial --------------------------------------------

  /** Cualquier miembro consulta; agregar, cambiar y quitar son del propietario. */
  listarMiembros: (proyectoId: string) =>
    pedir<MiembroProyecto[]>(`/proyectos/${proyectoId}/miembros`),

  /** Solo el propietario. Hasta 20, filtrados por nombre o correo. */
  listarCandidatosMiembro: (proyectoId: string, buscar = '') =>
    pedir<CandidatoMiembro[]>(
      `/proyectos/${proyectoId}/miembros/candidatos${buscar ? `?buscar=${encodeURIComponent(buscar)}` : ''}`,
    ),

  /** Correo exacto de un usuario ya registrado. */
  agregarMiembro: (proyectoId: string, email: string, rol: RolAsignable) =>
    pedir<MiembroProyecto>(`/proyectos/${proyectoId}/miembros`, {
      metodo: 'POST',
      cuerpo: { email, rol },
    }),

  cambiarRolMiembro: (proyectoId: string, usuarioId: string, rol: RolAsignable) =>
    pedir<MiembroProyecto>(`/proyectos/${proyectoId}/miembros/${usuarioId}`, {
      metodo: 'PUT',
      cuerpo: { rol },
    }),

  /** Responde 204. */
  quitarMiembro: (proyectoId: string, usuarioId: string) =>
    pedir<null>(`/proyectos/${proyectoId}/miembros/${usuarioId}`, { metodo: 'DELETE' }).then(() => undefined),

  /** Solo lectura, el más reciente primero. */
  listarHistorial: (proyectoId: string, limite = 50) =>
    pedir<EventoHistorial[]>(`/proyectos/${proyectoId}/historial?limite=${limite}`),

  // --- Configuración del cálculo --------------------------------------

  obtenerConfiguracion: () =>
    pedir<Configuracion>('/configuracion'),

  /** UF del día desde valores_uf; el backend no consulta la CMF en cada petición. */
  obtenerUfVigente: () =>
    pedir<UfVigente>('/configuracion/uf-vigente'),

  guardarConfiguracion: (configuracion: Configuracion) =>
    pedir<Configuracion>('/configuracion', {
      metodo: 'PUT',
      cuerpo: configuracion,
    }),

  // --- Administración (solo administradores) ---------------------------

  listarUsuarios: () =>
    pedir<UsuarioAdministrado[]>('/administracion/usuarios'),

  /** Crea un profesional; en modo enlace responde el enlace una sola vez. */
  crearUsuario: (datos: UsuarioNuevo) =>
    pedir<UsuarioCreado>('/administracion/usuarios', { metodo: 'POST', cuerpo: datos }),

  /** Enlace nuevo para una invitación pendiente; en modo correo, Supabase la reenvía. */
  renovarInvitacion: (usuarioId: string) =>
    pedir<UsuarioCreado>(`/administracion/usuarios/${usuarioId}/renovar-invitacion`, { metodo: 'POST' }),

  configuracionAdministracion: () =>
    pedir<ConfiguracionAdministracion>('/administracion/configuracion'),

  /** Crea la solicitud; el rol cambia solo con 3 de 3 aprobaciones. */
  solicitarAdministrador: (usuarioId: string) =>
    pedir<SolicitudAdministrador>(`/administracion/usuarios/${usuarioId}/solicitar-administrador`, {
      metodo: 'POST',
    }),

  aprobarSolicitudAdministrador: (solicitudId: string) =>
    pedir<SolicitudAdministrador>(`/administracion/solicitudes-administrador/${solicitudId}/aprobar`, {
      metodo: 'POST',
    }),
}