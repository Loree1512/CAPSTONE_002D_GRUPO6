/* Diálogo de confirmación con el estilo de BuildCast, en lugar de window.confirm.
   Reutiliza .bc-capa y .bc-modal. Devuelve una promesa: true si se confirma;
   false con Cancelar, Escape o un clic fuera del cuadro. */

export interface OpcionesConfirmacion {
  /** Rótulo pequeño sobre el título, p. ej. la sección: "Presupuesto". */
  rotulo?: string
  titulo: string
  mensaje: string
  /** Texto del botón de acción. Por defecto "Aceptar". */
  confirmar?: string
  /** Texto del botón para no continuar. Por defecto "Cancelar". */
  cancelar?: string
}

let contador = 0

function boton(texto: string, linea: boolean): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = linea ? 'bc-boton bc-boton--linea' : 'bc-boton'
  b.textContent = texto
  return b
}

export function confirmar(opciones: OpcionesConfirmacion): Promise<boolean> {
  return new Promise((resolver) => {
    const id = `bc-confirmar-${++contador}`
    const anterior = document.activeElement instanceof HTMLElement ? document.activeElement : null

    const capa = document.createElement('div')
    capa.className = 'bc-capa'

    const modal = document.createElement('div')
    modal.className = 'bc-modal'
    modal.setAttribute('role', 'alertdialog')
    modal.setAttribute('aria-modal', 'true')
    modal.setAttribute('aria-labelledby', `${id}-titulo`)
    modal.setAttribute('aria-describedby', `${id}-texto`)

    if (opciones.rotulo) {
      const rotulo = document.createElement('span')
      rotulo.className = 'bc-rotulo'
      rotulo.textContent = opciones.rotulo
      modal.append(rotulo)
    }
    const titulo = document.createElement('h2')
    titulo.className = 'bc-h2'
    titulo.id = `${id}-titulo`
    titulo.style.marginBottom = '12px'
    titulo.textContent = opciones.titulo
    const texto = document.createElement('p')
    texto.className = 'bc-apoyo'
    texto.id = `${id}-texto`
    texto.textContent = opciones.mensaje

    const acciones = document.createElement('div')
    acciones.className = 'bc-acciones'
    acciones.style.marginTop = '20px'
    const cancelar = boton(opciones.cancelar ?? 'Cancelar', true)
    const aceptar = boton(opciones.confirmar ?? 'Aceptar', false)
    acciones.append(cancelar, aceptar)
    modal.append(titulo, texto, acciones)
    capa.append(modal)

    function cerrar(resultado: boolean): void {
      document.removeEventListener('keydown', alTeclear, true)
      capa.remove()
      anterior?.focus()
      resolver(resultado)
    }

    function alTeclear(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        cerrar(false)
      } else if (e.key === 'Tab') {
        // El foco no sale del cuadro: solo hay dos botones.
        e.preventDefault()
        ;(document.activeElement === cancelar ? aceptar : cancelar).focus()
      }
    }

    cancelar.addEventListener('click', () => cerrar(false))
    aceptar.addEventListener('click', () => cerrar(true))
    capa.addEventListener('click', (e) => { if (e.target === capa) cerrar(false) })
    document.addEventListener('keydown', alTeclear, true)

    document.body.append(capa)
    // El foco empieza en Cancelar: Enter no confirma una acción sin querer.
    cancelar.focus()
  })
}
