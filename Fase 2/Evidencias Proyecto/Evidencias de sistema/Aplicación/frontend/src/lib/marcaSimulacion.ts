import { SIMULACION, reiniciarSimulacion } from './api'

/** Deja visible que los datos no son reales, para que nadie muestre
 *  una pantalla de demostración creyendo que viene de la API. */
export function marcarSimulacion(): void {
  if (!SIMULACION) return

  const contenedor = document.querySelector('.bc-barra > div') ?? document.body
  const marca = document.createElement('div')
  marca.className = 'bc-marca-simulacion'
  marca.innerHTML =
    '<span class="bc-estado bc-estado--pendiente">Modo demostración</span>' +
    '<button type="button" class="bc-boton bc-boton--texto bc-boton--menor">Reiniciar datos</button>'

  marca.querySelector('button')?.addEventListener('click', () => {
    reiniciarSimulacion()
    window.location.reload()
  })

  contenedor.appendChild(marca)
}
