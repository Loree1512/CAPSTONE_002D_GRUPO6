import Alpine from 'alpinejs'
import { api } from '../lib/api'
import { marcarSimulacion } from '../lib/marcaSimulacion'
import { prepararNavegacion } from '../lib/navegacion'
import { iniciarBotonTema } from '../lib/tema'
import { exigirSesion, salir } from '../lib/sesion'
import { fecha } from '../lib/formato'
import { esAdministrador } from '../lib/rolGlobal'
import {
  crearPanelAdministracion, etiquetaEstado, etiquetaRolGlobal, nombreVisible, progreso,
} from '../lib/administracion'
import type { PanelAdministracion } from '../lib/administracion'
import type { Usuario } from '../tipos/api'

interface PantallaAdministracion {
  panel: PanelAdministracion
  yo: Usuario | null
  /** El usuario actual no es administrador: no se muestra nada del panel. */
  sinAcceso: boolean
  fecha: typeof fecha
  etiquetaEstado: typeof etiquetaEstado
  etiquetaRolGlobal: typeof etiquetaRolGlobal
  nombreVisible: typeof nombreVisible
  progreso: typeof progreso
  iniciar(): Promise<void>
  salir(): void
}

Alpine.data('administracion', (): PantallaAdministracion => ({
  panel: crearPanelAdministracion({
    listar: () => api.listarUsuarios(),
    crear: (datos) => api.crearUsuario(datos),
    solicitar: (id) => api.solicitarAdministrador(id),
    aprobar: (id) => api.aprobarSolicitudAdministrador(id),
    renovar: (id) => api.renovarInvitacion(id),
    configuracion: () => api.configuracionAdministracion(),
  }),
  yo: null,
  sinAcceso: false,
  fecha,
  etiquetaEstado,
  etiquetaRolGlobal,
  nombreVisible,
  progreso,

  async iniciar() {
    this.yo = await prepararNavegacion()
    // Si /yo no respondió, decide la API: un profesional recibe 403.
    if (this.yo && !esAdministrador(this.yo)) {
      this.sinAcceso = true
      return
    }
    await this.panel.cargar()
    this.sinAcceso = this.panel.sinPermiso
  },

  salir,
}))

if (exigirSesion()) {
  window.Alpine = Alpine
  Alpine.start()
  marcarSimulacion()
  iniciarBotonTema()
}
