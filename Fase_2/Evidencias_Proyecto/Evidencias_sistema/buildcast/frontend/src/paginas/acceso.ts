import Alpine from 'alpinejs'
import '../estilos/base.css'
import { api, ErrorApi, SIMULACION } from '../lib/api'
import { guardar, haySesion } from '../lib/sesion'

interface Acceso {
  correo: string
  clave: string
  cargando: boolean
  error: string
  aviso: string
  entrar(): Promise<void>
  reenviar(): Promise<void>
}

Alpine.data('acceso', (): Acceso => ({
  correo: SIMULACION ? 'demo@ramarquitectura.cl' : '',
  clave: SIMULACION ? 'demostracion' : '',
  cargando: false,
  error: '',
  aviso: SIMULACION ? 'Modo demostración: entra con cualquier credencial, los datos son de ejemplo.' : '',

  async entrar() {
    this.error = ''
    this.aviso = ''

    if (!this.correo || !this.clave) {
      this.error = 'Ingresa tu correo y tu contraseña.'
      return
    }

    this.cargando = true
    try {
      const respuesta = await api.iniciarSesion(this.correo.trim(), this.clave)
      if (!guardar(respuesta)) {
        this.error = 'La API respondió sin token de sesión. Revisa el contrato con el backend.'
        return
      }
      window.location.assign('/panel.html')
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo iniciar sesión.'
    } finally {
      this.cargando = false
    }
  },

  async reenviar() {
    this.error = ''
    if (!this.correo) {
      this.error = 'Escribe tu correo para reenviar la confirmación.'
      return
    }
    try {
      await api.reenviarConfirmacion(this.correo.trim())
      this.aviso = 'Listo, revisa tu correo.'
    } catch (e) {
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo reenviar la confirmación.'
    }
  },
}))

if (haySesion()) window.location.replace('/panel.html')

window.Alpine = Alpine
Alpine.start()
