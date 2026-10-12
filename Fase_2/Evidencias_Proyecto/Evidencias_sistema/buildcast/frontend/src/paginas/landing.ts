import '../estilos/base.css'

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

  // Contador de capítulos
  const capitulo = document.querySelector<HTMLElement>('[data-chapter]')
  if (capitulo) {
    const recorrido = document.documentElement.scrollHeight - alto
    const avance = recorrido > 0 ? window.scrollY / recorrido : 0
    capitulo.textContent = `0${limitar(Math.ceil(avance * 6), 1, 6)} / 06`
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

const PERFILES = [
  'Menos tiempo buscando información. Más tiempo tomando decisiones.',
  'Una nueva forma de trabajar con proyectos complejos.',
  'Estandariza y acelera tu proceso de presupuestación a gran escala.',
  'Obtén claridad sobre los costos desde etapas tempranas.',
  'Convierte información dispersa en una visión clara y accionable.',
]

function conectarPerfiles(): void {
  const filas = Array.from(document.querySelectorAll<HTMLElement>('[data-perfil]'))
  const titulo = document.querySelector<HTMLElement>('[data-perfil-titulo]')
  const cita = document.querySelector<HTMLElement>('[data-perfil-cita]')

  const elegir = (i: number) => {
    filas.forEach((fila, j) => {
      const activa = i === j
      fila.style.color = activa ? '#FF5E00' : 'rgba(255,255,255,.5)'
      const flecha = fila.querySelector<HTMLElement>('span:last-child')
      if (flecha) flecha.style.opacity = activa ? '1' : '0'
    })
    const nombre = filas[i]?.querySelector('h3')?.textContent ?? ''
    if (titulo) titulo.textContent = nombre   // oculto: el marco muestra un motivo
    if (cita) cita.textContent = PERFILES[i] ?? ''
  }

  filas.forEach((fila, i) => {
    fila.addEventListener('mouseenter', () => elegir(i))
    fila.addEventListener('click', () => elegir(i))
  })
}

/** Reproduce el style-hover del prototipo: estilos inline al pasar el mouse. */
function conectarHover(): void {
  document.querySelectorAll<HTMLElement>('[data-hover]').forEach((el) => {
    const declaraciones = (el.dataset.hover ?? '').split(';').filter(Boolean)
      .map((d) => d.split(':').map((p) => p.trim()) as [string, string])
    const previos = declaraciones.map(([prop]) => [prop, el.style.getPropertyValue(prop)] as [string, string])

    el.addEventListener('mouseenter', () => declaraciones.forEach(([p, v]) => el.style.setProperty(p, v)))
    el.addEventListener('mouseleave', () => previos.forEach(([p, v]) => el.style.setProperty(p, v)))
  })
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

  const conCapas = !esMovil() && !menosMovimiento
  if (conCapas) document.body.classList.add('bc-animada')

  console.info(
    `BuildCast · landing en modo ${conCapas ? 'capas fijadas' : 'apilado'}` +
    ` (ancho ${window.innerWidth}px, menos movimiento: ${menosMovimiento})`,
  )

  prepararRevelado()
  conectarPerfiles()
  conectarHover()
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
  document.body.classList.remove('bc-animada')
  console.error('No se pudieron iniciar los efectos de la landing:', error)
}
