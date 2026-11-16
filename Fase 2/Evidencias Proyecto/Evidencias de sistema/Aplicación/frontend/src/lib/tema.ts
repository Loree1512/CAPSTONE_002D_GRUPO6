// Tema claro/oscuro. La elección se guarda en el navegador; sin elección se
// usa la preferencia del sistema. No depende de `window` al importarse (las
// pruebas corren en Node), solo al llamar a las funciones.

export type Tema = 'claro' | 'oscuro'

export const CLAVE_TEMA = 'buildcast.tema'

export function temaGuardado(): Tema | null {
  try {
    const valor = localStorage.getItem(CLAVE_TEMA)
    return valor === 'claro' || valor === 'oscuro' ? valor : null
  } catch {
    return null
  }
}

export function temaInicial(): Tema {
  const guardado = temaGuardado()
  if (guardado) return guardado
  try {
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'oscuro' : 'claro'
  } catch {
    return 'claro'
  }
}

export function temaActual(): Tema {
  return document.documentElement.dataset.tema === 'oscuro' ? 'oscuro' : 'claro'
}

export function aplicarTema(tema: Tema): void {
  if (tema === 'oscuro') document.documentElement.dataset.tema = 'oscuro'
  else delete document.documentElement.dataset.tema
}

export function alternarTema(): Tema {
  const siguiente: Tema = temaActual() === 'oscuro' ? 'claro' : 'oscuro'
  aplicarTema(siguiente)
  try {
    localStorage.setItem(CLAVE_TEMA, siguiente)
  } catch {
    // Sin almacenamiento (modo privado): el cambio vale solo para esta visita.
  }
  return siguiente
}

/** Conecta los botones `[data-tema-boton]`: alternan el tema y reflejan el estado en aria-pressed. */
export function iniciarBotonTema(): void {
  aplicarTema(temaInicial())
  const botones = document.querySelectorAll<HTMLButtonElement>('[data-tema-boton]')
  const reflejar = () => {
    const oscuro = temaActual() === 'oscuro'
    botones.forEach((boton) => {
      boton.setAttribute('aria-pressed', String(oscuro))
      boton.setAttribute('aria-label', oscuro ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro')
      boton.title = oscuro ? 'Modo claro' : 'Modo oscuro'
    })
  }
  botones.forEach((boton) => boton.addEventListener('click', () => { alternarTema(); reflejar() }))
  reflejar()
}
