/** Menú desplegable de la barra superior en celular (bajo 760px, ver base.css).
 *  En pantallas angostas la barra muestra el logo, «Salir» y este botón; al tocarlo se
 *  despliega a la derecha un panel con la cuenta y los enlaces. En escritorio el panel
 *  usa display: contents y sus elementos siguen en la barra como antes. */

const ANCHO_MENU = 760

export function conectarMenuBarra(): void {
  const barra = document.querySelector<HTMLElement>('header.bc-barra')
  const fila = barra?.firstElementChild
  const marca = fila?.querySelector('.bc-marca')
  if (!barra || !fila || !marca || fila.querySelector('.bc-barra__menu')) return

  const boton = document.createElement('button')
  boton.type = 'button'
  boton.className = 'bc-barra__menu'
  boton.setAttribute('aria-expanded', 'false')
  boton.setAttribute('aria-label', 'Abrir menú')
  boton.innerHTML = '<span></span><span></span><span></span>'

  // La cuenta, los enlaces y la marca de demostración van dentro del panel.
  const panel = document.createElement('div')
  panel.className = 'bc-barra__panel'
  panel.id = 'barra-panel'
  boton.setAttribute('aria-controls', panel.id)
  const alPanel = (el: Element | null) => { if (el && el.parentElement !== panel) panel.append(el) }
  alPanel(fila.querySelector(':scope > .bc-cuenta'))
  alPanel(fila.querySelector(':scope > .bc-nav'))
  alPanel(fila.querySelector(':scope > .bc-marca-simulacion'))
  // Si el logo va en un grupo (con el botón de tema), el menú y el panel van después del grupo.
  const ancla = marca.closest('.bc-marca-grupo') ?? marca
  ancla.after(boton, panel)

  // La marca de demostración puede llegar después (marcaSimulacion.ts).
  new MutationObserver(() => alPanel(fila.querySelector(':scope > .bc-marca-simulacion')))
    .observe(fila, { childList: true })

  const fijar = (abierto: boolean) => {
    barra.toggleAttribute('data-abierto', abierto)
    boton.setAttribute('aria-expanded', String(abierto))
    boton.setAttribute('aria-label', abierto ? 'Cerrar menú' : 'Abrir menú')
  }

  boton.addEventListener('click', () => fijar(!barra.hasAttribute('data-abierto')))
  panel.querySelectorAll('.bc-nav a').forEach((enlace) => enlace.addEventListener('click', () => fijar(false)))
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') fijar(false) })
  document.addEventListener('click', (ev) => {
    if (barra.hasAttribute('data-abierto') && !barra.contains(ev.target as Node)) fijar(false)
  })
  window.addEventListener('resize', () => { if (window.innerWidth > ANCHO_MENU) fijar(false) })
}
