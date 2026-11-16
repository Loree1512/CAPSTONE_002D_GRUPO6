import { esFragmentoDeAuth } from '../lib/invitacion'
import { destinoTecla, indiceEtapa, PERFILES, textoEtapa } from '../lib/recorrido'

/* Si Supabase no acepta el redirect_to (FRONTEND_URL vacía o /acceso.html fuera de
   Redirect URLs), el enlace de invitación vuelve a la Site URL, es decir, aquí. El
   fragmento lleva la sesión: se pasa tal cual a acceso.html, que lo lee y lo borra. */
if (esFragmentoDeAuth(window.location.hash)) {
  window.location.replace('/acceso.html' + window.location.hash)
}

/* Efectos de scroll de la landing.
   Reimplementación de los que traía el prototipo (revelado, parallax del
   hero, secuencias fijadas, cruce de secciones y barra de progreso), sin
   su runtime propietario. Todo se apaga si el sistema pide menos
   movimiento. */

const menosMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)').matches

/* En teléfonos las secuencias fijadas pasan a flujo normal (ver base.css):
   el JS no debe escribir opacidades ni desplazamientos sobre ellas. */
const esMovil = () => window.matchMedia('(max-width: 760px)').matches

const limitar = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/* --- Revelado al entrar en pantalla -------------------------------------- */

function prepararRevelado(): void {
  const elementos = Array.from(document.querySelectorAll<HTMLElement>('[data-reveal]'))

  if (menosMovimiento) {
    elementos.forEach((el) => { el.style.opacity = '1' })
    return
  }

  const observador = new IntersectionObserver((entradas) => {
    entradas.forEach((entrada) => {
      if (!entrada.isIntersecting) return
      const el = entrada.target as HTMLElement
      const retraso = parseFloat(el.dataset.delay ?? '0')
      el.style.transitionDelay = `${retraso}s`
      el.style.opacity = '1'
      el.style.transform = 'none'
      window.setTimeout(() => { el.style.willChange = 'auto' }, 1000)
      observador.unobserve(el)
    })
  }, { threshold: 0.1, rootMargin: '0px 0px -5% 0px' })

  elementos.forEach((el) => {
    const direccion = el.dataset.reveal
    el.style.willChange = 'opacity, transform'
    el.style.opacity = '0'
    const salto = esMovil() ? 24 : 48
    el.style.transform =
      direccion === 'left'  ? `translateX(-${salto}px)` :
      direccion === 'right' ? `translateX(${salto}px)`  :
      direccion === 'scale' ? 'scale(.96)'              : `translateY(${salto}px)`
    el.style.transition = 'opacity .9s cubic-bezier(.16,1,.3,1), transform .9s cubic-bezier(.16,1,.3,1)'
    observador.observe(el)
  })
}

/* --- Recorrido hacia el presupuesto -------------------------------------- */

/** Índice de la etapa a la vista, o null fuera del recorrido. */
function etapaVisible(alto: number): number | null {
  const seccion = document.querySelector<HTMLElement>('[data-seq="journey"]')
  if (!seccion) return null
  const caja = seccion.getBoundingClientRect()
  if (caja.top > alto * 0.5 || caja.bottom < alto * 0.5) return null

  // Capas fijadas: la etapa sale del avance, igual que los tramos de pintar().
  if (document.body.classList.contains('bc-animada')) {
    const avance = limitar(-caja.top / ((seccion.offsetHeight - alto) || 1), 0, 1)
    return indiceEtapa(avance)
  }
  // Apilado: la lámina que cruza el centro de la ventana.
  const items = Array.from(seccion.querySelectorAll<HTMLElement>('[data-seq-item]'))
  const i = items.findIndex((el) => {
    const r = el.getBoundingClientRect()
    return r.top <= alto * 0.5 && r.bottom >= alto * 0.5
  })
  return i === -1 ? null : i
}

/* En modo apilado (móvil o sin capas) no hay avance de scroll que gobierne las
   láminas: cada una se dibuja una vez, al entrar en pantalla. En modo de capas
   el observador no actúa: pintar() decide. */
function observarLaminas(): void {
  if (menosMovimiento || !('IntersectionObserver' in window)) return
  const observador = new IntersectionObserver((entradas) => {
    if (document.body.classList.contains('bc-animada')) return
    entradas.forEach((entrada) => {
      if (!entrada.isIntersecting) return
      entrada.target.setAttribute('data-activo', '')
      observador.unobserve(entrada.target)
    })
  }, { threshold: 0.3 })
  document.querySelectorAll('[data-seq="journey"] [data-anima]').forEach((el) => observador.observe(el))
}

/* --- Efectos ligados a la posición del scroll ---------------------------- */

function pintar(): void {
  const alto = window.innerHeight

  // Cabecera: se opaca al despegar del inicio
  const cabecera = document.querySelector<HTMLElement>('[data-navbar]')
  if (cabecera) {
    const activa = window.scrollY > alto * 0.05
    cabecera.style.background = activa ? 'rgba(249,249,247,.9)' : 'transparent'
    cabecera.style.backdropFilter = activa ? 'blur(12px)' : 'none'
  }

  /* Indicador de etapa. Antes dividía la página completa en seis tramos y no
     correspondía a nada visible; ahora muestra la etapa del recorrido que se
     está viendo, y solo mientras el recorrido está en pantalla. */
  const capitulo = document.querySelector<HTMLElement>('[data-chapter]')
  if (capitulo) {
    const etapa = etapaVisible(alto)
    capitulo.style.opacity = etapa === null ? '0' : '1'
    if (etapa !== null) {
      const texto = textoEtapa(etapa)
      if (capitulo.textContent !== texto) capitulo.textContent = texto
    }
  }

  if (menosMovimiento || esMovil()) return

  // Parallax del hero
  const hero = document.querySelector<HTMLElement>('[data-hero]')
  if (hero) {
    hero.style.transform = `translateY(${window.scrollY * 0.3}px)`
    hero.style.opacity = String(limitar(1 - window.scrollY / 620, 0, 1))
  }

  // Parallax de elementos sueltos
  document.querySelectorAll<HTMLElement>('[data-parallax]').forEach((el) => {
    const caja = el.getBoundingClientRect()
    const avance = limitar((alto - caja.top) / (alto + caja.height), 0, 1)
    el.style.transform = `translateY(${(avance - 0.5) * 2 * parseFloat(el.dataset.parallax ?? '0')}px)`
  })

  // Secuencias fijadas: cada ítem aparece en su tramo del recorrido
  document.querySelectorAll<HTMLElement>('[data-seq]').forEach((seccion) => {
    const caja = seccion.getBoundingClientRect()
    const recorrido = seccion.offsetHeight - alto
    const avance = limitar(-caja.top / (recorrido || 1), 0, 1)

    const barra = seccion.querySelector<HTMLElement>('[data-seq-bar]')
    if (barra) barra.style.transform = `scaleX(${avance})`

    /* Las palabras dispersas del fondo cuelgan de la sección, no de un
       bloque: se encienden con el avance general y se quedan puestas. */
    seccion.querySelectorAll<HTMLElement>('[data-chaos]').forEach((palabra, j) => {
      const entrada = limitar((avance - j * 0.008) / 0.05, 0, 1)
      palabra.style.transition = 'opacity .5s ease, transform .5s ease'
      palabra.style.opacity = String(entrada)
      palabra.style.transform = `translateY(${(1 - entrada) * 20}px)`
    })

    const items = Array.from(seccion.querySelectorAll<HTMLElement>('[data-seq-item]'))
    const total = items.length || 1

    /* Los tramos del prototipo dejaban huecos: antes del primero y después
       del último no se mostraba nada, y entre uno y otro había momentos sin
       contenido. Se encadenan para que la sección nunca quede en blanco:
       cada bloque dura hasta que empieza el siguiente. */
    const inicios = items.map((item, i) =>
      item.dataset.from !== undefined ? parseFloat(item.dataset.from) : i / total)
    const tramos = items.map((_, i) => ({
      desde: i === 0 ? 0 : inicios[i],
      hasta: i === items.length - 1 ? 1 : inicios[i + 1],
    }))

    items.forEach((item, i) => {
      const { desde, hasta } = tramos[i]
      const fundido = Math.min(0.09, Math.max(0.04, (hasta - desde) * 0.22))

      let opacidad: number
      if (avance < desde - fundido) opacidad = 0
      else if (avance < desde) opacidad = (avance - (desde - fundido)) / fundido
      else if (avance < hasta) opacidad = 1
      else opacidad = limitar(1 - (avance - hasta) / fundido, 0, 1)

      item.style.opacity = String(opacidad)
      const desfase = (1 - opacidad) * 44
      item.style.transform = `translateY(${avance < desde ? desfase : -desfase}px)`

      /* La lámina se dibuja al quedar casi visible y se reinicia cuando sale del
         todo: al volver a ella, el plano se traza de nuevo. */
      if (item.hasAttribute('data-anima')) {
        const activa = item.hasAttribute('data-activo')
        if (opacidad > 0.5 && !activa) item.setAttribute('data-activo', '')
        else if (opacidad === 0 && activa) item.removeAttribute('data-activo')
      }
    })
  })

  // Cruce entre dos capas de una misma sección
  document.querySelectorAll<HTMLElement>('[data-cross]').forEach((seccion) => {
    const caja = seccion.getBoundingClientRect()
    const avance = limitar((alto - caja.top) / (alto + caja.height), 0, 1)
    const sale = seccion.querySelector<HTMLElement>('[data-cross-out]')
    const entra = seccion.querySelector<HTMLElement>('[data-cross-in]')
    const escala = seccion.querySelector<HTMLElement>('[data-cross-scale]')
    if (sale)  sale.style.opacity  = String(limitar(1 - (avance - 0.28) / 0.18, 0, 1))
    if (entra) entra.style.opacity = String(limitar((avance - 0.34) / 0.18, 0, 1))
    if (escala) escala.style.transform = `scale(${0.95 + limitar((avance - 0.2) / 0.4, 0, 1) * 0.05})`
  })
}

/* --- Interacción --------------------------------------------------------- */

function conectarPerfiles(): void {
  const pestanas = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-perfil]'))
  const vistas = Array.from(document.querySelectorAll<HTMLElement>('[data-perfil-vista]'))
  const panel = document.getElementById('perfil-panel')
  const num = document.querySelector<HTMLElement>('[data-perfil-num]')
  const foco = document.querySelector<HTMLElement>('[data-perfil-foco]')
  const cita = document.querySelector<HTMLElement>('[data-perfil-cita]')
  if (!pestanas.length || !panel) return
  let actual = 0

  // Quitar y volver a poner data-activo reinicia el dibujo de la vista.
  const animar = (vista: HTMLElement) => {
    vista.removeAttribute('data-activo')
    void vista.getBoundingClientRect()
    vista.setAttribute('data-activo', '')
  }

  const elegir = (i: number, enfocar = false) => {
    if (enfocar) pestanas[i].focus()
    if (i === actual) return
    actual = i
    pestanas.forEach((p, j) => {
      p.setAttribute('aria-selected', String(i === j))
      p.tabIndex = i === j ? 0 : -1
    })
    vistas.forEach((v, j) => {
      if (j === i) {
        v.setAttribute('data-actual', '')
        v.removeAttribute('aria-hidden')
        animar(v)
      } else {
        v.removeAttribute('data-actual')
        v.removeAttribute('data-activo')
        v.setAttribute('aria-hidden', 'true')
      }
    })
    panel.setAttribute('aria-labelledby', pestanas[i].id)
    if (num) num.textContent = `0${i + 1}`
    if (foco) foco.textContent = PERFILES[i].foco
    if (cita) {
      cita.textContent = PERFILES[i].frase
      cita.style.animation = 'none'
      void cita.offsetWidth
      cita.style.animation = ''
    }
  }

  const conHover = window.matchMedia('(hover: hover)').matches
  pestanas.forEach((p, i) => {
    p.addEventListener('click', () => elegir(i))
    // El hover solo adelanta lo que hace el clic; nada depende de él.
    if (conHover) p.addEventListener('mouseenter', () => elegir(i))
    p.addEventListener('keydown', (ev) => {
      const destino = destinoTecla(ev.key, i, pestanas.length)
      if (destino === null) return
      ev.preventDefault()
      elegir(destino, true)
    })
  })

  // La primera vista se dibuja cuando el panel entra en pantalla.
  if (menosMovimiento || !('IntersectionObserver' in window)) {
    vistas[0]?.setAttribute('data-activo', '')
    return
  }
  const observador = new IntersectionObserver((entradas) => {
    if (!entradas.some((e) => e.isIntersecting)) return
    const vista = vistas[actual]
    if (vista && !vista.hasAttribute('data-activo')) animar(vista)
    observador.disconnect()
  }, { threshold: 0.35 })
  observador.observe(panel)
}

/** Menú desplegable bajo 1024px: la barra no da para cinco elementos. */
function conectarMenu(): void {
  const boton = document.querySelector<HTMLButtonElement>('[data-menu]')
  const panel = document.querySelector<HTMLElement>('[data-menu-panel]')
  if (!boton || !panel) return

  const cerrar = () => {
    panel.removeAttribute('data-abierto')
    boton.setAttribute('aria-expanded', 'false')
    boton.setAttribute('aria-label', 'Abrir menú')
  }

  boton.addEventListener('click', () => {
    const abierto = panel.hasAttribute('data-abierto')
    if (abierto) return cerrar()
    panel.setAttribute('data-abierto', '')
    boton.setAttribute('aria-expanded', 'true')
    boton.setAttribute('aria-label', 'Cerrar menú')
  })

  panel.querySelectorAll('a, button').forEach((el) => el.addEventListener('click', cerrar))
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') cerrar() })
  window.addEventListener('resize', () => { if (window.innerWidth > 1024) cerrar() })
}

function conectarNavegacion(): void {
  document.querySelectorAll<HTMLElement>('[data-ir]').forEach((el) => {
    el.addEventListener('click', () => { window.location.assign(el.dataset.ir as string) })
  })

  document.querySelectorAll<HTMLAnchorElement>('a[href^="#"]').forEach((enlace) => {
    enlace.addEventListener('click', (ev) => {
      const destino = document.querySelector(enlace.getAttribute('href') as string)
      if (!destino) return
      ev.preventDefault()
      destino.scrollIntoView({ behavior: menosMovimiento ? 'auto' : 'smooth', block: 'start' })
    })
  })
}

/* --- Arranque ------------------------------------------------------------ */

let pendiente = false
function alDesplazar(): void {
  if (pendiente) return
  pendiente = true
  requestAnimationFrame(() => { pintar(); pendiente = false })
}

/* La clase bc-animada activa el modo con capas fijadas. Se pone solo si
   el script llegó hasta aquí: antes de eso el CSS muestra todo en flujo
   normal, de modo que una falla nunca deja secciones en blanco. */
function arrancar(): void {
  document.body.classList.add('bc-js')
  // Sin esta clase los dibujos se muestran completos y quietos.
  if (!menosMovimiento) document.body.classList.add('bc-movimiento')

  const conCapas = !esMovil() && !menosMovimiento
  if (conCapas) document.body.classList.add('bc-animada')

  console.info(
    `BuildCast · landing en modo ${conCapas ? 'capas fijadas' : 'apilado'}` +
    ` (ancho ${window.innerWidth}px, menos movimiento: ${menosMovimiento})`,
  )

  prepararRevelado()
  observarLaminas()
  conectarPerfiles()
  conectarMenu()
  conectarNavegacion()
  pintar()

  window.addEventListener('scroll', alDesplazar, { passive: true })
  window.addEventListener('resize', () => {
    document.body.classList.toggle('bc-animada', !esMovil() && !menosMovimiento)
    alDesplazar()
  })
}

try {
  arrancar()
} catch (error) {
  // Sin animaciones, pero con todo el contenido visible.
  document.body.classList.remove('bc-animada', 'bc-movimiento')
  console.error('No se pudieron iniciar los efectos de la landing:', error)
}
