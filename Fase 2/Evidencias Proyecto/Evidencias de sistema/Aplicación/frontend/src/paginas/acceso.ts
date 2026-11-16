import Alpine from 'alpinejs'
import { api, ErrorApi, SIMULACION } from '../lib/api'
import { guardar, guardarUsuario, haySesion, usuario } from '../lib/sesion'
import { decidirAcceso, errorClaveNueva, leerEnlaceInvitacion } from '../lib/invitacion'

interface Acceso {
  correo: string
  clave: string
  cargando: boolean
  error: string
  aviso: string
  /** Mientras se pregunta al backend si la cuenta ya tiene contraseña. */
  verificando: boolean
  /** La sesión es de un invitado sin contraseña: define la suya. */
  invitacion: boolean
  claveNueva: string
  confirmacion: string
  iniciar(): Promise<void>
  entrar(): Promise<void>
  reenviar(): Promise<void>
  crearClave(): Promise<void>
}

// El fragmento trae tokens: se lee una vez y se borra de la barra de direcciones.
const enlace = leerEnlaceInvitacion(window.location.hash)
if (enlace) window.history.replaceState(null, '', window.location.pathname + window.location.search)
if (enlace?.tipo === 'invitacion') guardar(enlace)

Alpine.data('acceso', (): Acceso => ({
  correo: SIMULACION ? 'demo@ramarquitectura.cl' : '',
  clave: SIMULACION ? 'demostracion' : '',
  cargando: false,
  error: '',
  aviso: SIMULACION ? 'Modo demostración: entra con cualquier credencial, los datos son de ejemplo.' : '',
  verificando: true,
  invitacion: false,
  claveNueva: '',
  confirmacion: '',

  // El estado vive en el backend: recargar la página no pierde el formulario.
  async iniciar() {
    const destino = await decidirAcceso({
      enlace, haySesion: haySesion(), guardado: usuario(), yo: () => api.yo(),
    })
    if (destino.a === 'panel') {
      window.location.replace('/panel.html')
      return
    }
    this.invitacion = destino.a === 'crear_clave'
    if (destino.a === 'login' && destino.error) this.error = destino.error
    this.verificando = false
  },

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

  async crearClave() {
    this.error = errorClaveNueva(this.claveNueva, this.confirmacion)
    if (this.error) return

    this.cargando = true
    try {
      await api.establecerContrasena(this.claveNueva)
      // La contraseña no se guarda en ningún lado del navegador.
      this.claveNueva = ''
      this.confirmacion = ''
      try {
        guardarUsuario(await api.yo())
      } catch {
        // El panel vuelve a preguntar.
      }
      window.location.assign('/panel.html')
    } catch (e) {
      // 409: ya tenía contraseña; entra normalmente.
      if (e instanceof ErrorApi && e.estado === 409) {
        window.location.replace('/panel.html')
        return
      }
      this.error = e instanceof ErrorApi ? e.message : 'No se pudo guardar la contraseña.'
    } finally {
      this.cargando = false
    }
  },
}))

window.Alpine = Alpine
Alpine.start()
