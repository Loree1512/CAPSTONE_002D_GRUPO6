/* Panel global de usuarios (/administracion). Los roles globales no tienen relación
   con los permisos por proyecto (propietario, editor, lector). */

export type RolGlobal = 'administrador' | 'profesional'

/** pendiente: invitado o sin confirmar el correo; todavía no entra. */
export type EstadoCuenta = 'activo' | 'pendiente'

export interface AprobacionPrincipal {
  administrador_id: string
  nombre: string | null
  email: string | null
  aprobada: boolean
  fecha: string | null
}

export interface SolicitudAdministrador {
  id: string
  usuario_id: string
  usuario_nombre: string | null
  usuario_email: string | null
  solicitado_por: string | null
  estado: 'pendiente' | 'aprobada'
  fecha_creacion: string
  fecha_resolucion: string | null
  aprobaciones_recibidas: number
  aprobaciones_requeridas: number
  /** Un renglón por administrador principal, en orden fijo. */
  aprobaciones: AprobacionPrincipal[]
  /** Quien consulta es principal y todavía no aprobó. */
  puedo_aprobar: boolean
}

export interface UsuarioAdministrado {
  id: string
  email: string | null
  nombre: string | null
  rol_global: RolGlobal
  es_administrador_principal: boolean
  fecha_creacion: string | null
  /** null si Supabase Auth no respondió. */
  estado: EstadoCuenta | null
  solicitud_pendiente: SolicitudAdministrador | null
  puede_solicitar_administrador: boolean
}

export interface UsuarioNuevo {
  nombre: string
  email: string
}

export type ModoInvitacion = 'enlace' | 'correo'

/** Respuesta al crear un usuario o renovar su invitación. */
export interface UsuarioCreado {
  usuario: UsuarioAdministrado
  modo: ModoInvitacion
  /** Solo en modo enlace y solo en esta respuesta. */
  enlace: string | null
}

export interface ConfiguracionAdministracion {
  modo_invitacion: ModoInvitacion
}
