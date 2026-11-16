// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ErrorApi } from '../src/lib/errores.ts'
import {
  crearHistorial, describirEvento, DESCRIPCION_GENERICA, fechaEvento, formatearValor,
  type CambioHistorial, type OpcionesHistorial,
} from '../src/lib/historial.ts'
import type { EventoHistorial } from '../src/tipos/api.ts'

function evento(accion: string, cambios: Partial<EventoHistorial> = {}): EventoHistorial {
  return {
    id: `e-${accion}`, accion, entidad: 'proyecto', entidad_id: null,
    usuario_id: 'u-1', usuario_email: 'angel@x.cl', usuario_nombre: 'Ángel González',
    valores_anteriores: null, valores_nuevos: null, origen: 'api',
    // Sin zona horaria: se lee en la hora local, igual que en el navegador.
    fecha: '2026-10-20T15:20:00',
    ...cambios,
  }
}

const describir = (e: EventoHistorial, opciones: OpcionesHistorial = {}) => describirEvento(e, opciones)
const filas = (cambios: CambioHistorial[]) => cambios.map((c) => [c.campo, c.anterior, c.nuevo])

// pesos() usa el separador de miles de es-CL; algunas versiones de ICU agregan un espacio tras el $.
const sinEspacio = (s: string | null) => s?.replace(/\$\s/g, '$') ?? null

describe('historial: partidas', () => {
  it('una partida cambia la cantidad', () => {
    const e = describir(evento('partida_editada', {
      valores_anteriores: { cantidad: 4 },
      valores_nuevos: { cantidad: 6, nombre: 'Puertas interiores' },
    }))
    assert.equal(e.texto, 'Editó la partida «Puertas interiores»')
    assert.deepEqual(filas(e.cambios), [['Cantidad', '4', '6']])
  })

  it('una partida cambia varios campos: solo los modificados, con nombre legible', () => {
    const e = describir(evento('partida_editada', {
      // La base puede devolver numeric como texto.
      valores_anteriores: { cantidad: '20', precio_unitario_override: 12000, unidad: 'm2' },
      valores_nuevos: { cantidad: '25.5', precio_unitario_override: 15000, unidad: 'm2', nombre: 'Radier' },
    }))
    assert.deepEqual(filas(e.cambios).map(([c, a, n]) => [c, sinEspacio(a), sinEspacio(n)]), [
      ['Cantidad', '20', '25,5'],
      ['Precio unitario', '$12.000', '$15.000'],
    ])
  })

  it('el nombre solo cuenta como cambio si también estaba entre los anteriores', () => {
    const renombrada = describir(evento('partida_editada', {
      valores_anteriores: { nombre: 'Radier' }, valores_nuevos: { nombre: 'Radier armado' },
    }))
    assert.equal(renombrada.texto, 'Editó la partida «Radier armado»')
    assert.deepEqual(filas(renombrada.cambios), [['Nombre', 'Radier', 'Radier armado']])
  })

  it('precio particular quitado y categoría con su nombre', () => {
    const e = describir(evento('partida_editada', {
      valores_anteriores: { precio_unitario_override: 15000, categoria_id: 4 },
      valores_nuevos: { precio_unitario_override: null, categoria_id: 6, nombre: 'Muro' },
    }), { categorias: { 4: 'Obra gruesa y estructura', 6: 'Terminaciones' } })
    assert.deepEqual(filas(e.cambios).map(([c, a, n]) => [c, sinEspacio(a), n]), [
      ['Precio unitario', '$15.000', 'Precio del banco'],
      ['Categoría', 'Obra gruesa y estructura', 'Terminaciones'],
    ])
  })

  it('agregada y eliminada: no existía → partida → eliminada', () => {
    const agregada = describir(evento('partida_agregada', {
      valores_nuevos: { nombre: 'Instalación de faenas', unidad: 'gl', cantidad: 1, origen: 'catalogo' },
    }))
    assert.equal(agregada.texto, 'Agregó la partida «Instalación de faenas»')
    assert.deepEqual(filas(agregada.cambios), [['Partida', 'No existía', 'Instalación de faenas · Cantidad 1 gl']])

    const eliminada = describir(evento('partida_eliminada', {
      valores_anteriores: { nombre: 'Instalación de faenas', unidad: 'gl', cantidad: 1, origen: 'catalogo' },
    }))
    assert.deepEqual(filas(eliminada.cambios), [['Partida', 'Instalación de faenas · Cantidad 1 gl', 'Eliminada']])
  })

  it('partida sin cantidad: se muestra solo el nombre', () => {
    const e = describir(evento('partida_agregada', { valores_nuevos: { nombre: 'Radier', cantidad: null } }))
    assert.deepEqual(filas(e.cambios), [['Partida', 'No existía', 'Radier']])
  })

  it('plantilla: partidas antes y después', () => {
    const aplicada = describir(evento('plantilla_aplicada', { valores_nuevos: { nombre: 'Vivienda', partidas: 12 } }))
    assert.equal(aplicada.texto, 'Aplicó la plantilla «Vivienda»')
    assert.deepEqual(filas(aplicada.cambios), [['Partidas', 'Sin partidas', '12']])

    const reemplazo = describir(evento('plantilla_aplicada', {
      valores_anteriores: { partidas: 3 }, valores_nuevos: { nombre: 'Vivienda', partidas: 12 },
    }))
    assert.equal(reemplazo.texto, 'Reemplazó las partidas con la plantilla «Vivienda»')
    assert.deepEqual(filas(reemplazo.cambios), [['Partidas', '3', '12']])
  })
})

describe('historial: proyecto', () => {
  it('cambia un campo', () => {
    const e = describir(evento('proyecto_editado', {
      valores_anteriores: { comuna: 'Viña del Mar' }, valores_nuevos: { comuna: 'Concón' },
    }))
    assert.equal(e.texto, 'Editó el proyecto')
    assert.deepEqual(filas(e.cambios), [['Comuna', 'Viña del Mar', 'Concón']])
  })

  it('superficie en m², pisos y estándar con nombres legibles', () => {
    const e = describir(evento('proyecto_editado', {
      valores_anteriores: { superficie_m2: '50', numero_pisos: 1, estandar_terminaciones: 'medio' },
      valores_nuevos: { superficie_m2: 65.5, numero_pisos: 2, estandar_terminaciones: 'alto' },
    }))
    assert.deepEqual(filas(e.cambios), [
      ['Superficie', '50 m²', '65,5 m²'],
      ['Número de pisos', '1', '2'],
      ['Estándar de terminaciones', 'Medio', 'Alto'],
    ])
  })

  it('un campo que quedó igual tras formatear no se muestra', () => {
    const e = describir(evento('proyecto_editado', {
      valores_anteriores: { superficie_m2: '50', comuna: 'Quilpué' },
      valores_nuevos: { superficie_m2: 50, comuna: 'Limache' },
    }))
    assert.deepEqual(filas(e.cambios), [['Comuna', 'Quilpué', 'Limache']])
  })
})

describe('historial: miembros', () => {
  const nombres = { 'u-camila': 'Camila' }

  it('cambio de rol', () => {
    const e = describir(evento('miembro_rol_cambiado', {
      entidad: 'miembro', entidad_id: 'u-camila',
      valores_anteriores: { rol: 'lector' }, valores_nuevos: { rol: 'editor', email: 'camila@x.cl' },
    }), { nombres })
    assert.equal(e.texto, 'Cambió el rol de Camila')
    assert.deepEqual(filas(e.cambios), [['Rol', 'Lector', 'Editor']])
  })

  it('agregado y eliminado', () => {
    const agregado = describir(evento('miembro_agregado', {
      entidad: 'miembro', entidad_id: 'u-camila', valores_nuevos: { email: 'camila@x.cl', rol: 'editor' },
    }), { nombres })
    assert.equal(agregado.texto, 'Agregó a Camila al proyecto')
    assert.deepEqual(filas(agregado.cambios), [['Rol', 'No pertenecía al proyecto', 'Editor']])

    // Quien ya no es miembro se nombra con su correo.
    const eliminado = describir(evento('miembro_eliminado', {
      entidad: 'miembro', entidad_id: 'u-ido', valores_anteriores: { email: 'ido@x.cl', rol: 'lector' },
    }), { nombres })
    assert.equal(eliminado.texto, 'Quitó a ido@x.cl del proyecto')
    assert.deepEqual(filas(eliminado.cambios), [['Rol', 'Lector', 'Ya no pertenece al proyecto']])
  })

  it('sigue aceptando el mapa de nombres directo', () => {
    const e = describirEvento(evento('miembro_eliminado', {
      entidad_id: 'u-camila', valores_anteriores: { rol: 'lector' },
    }), nombres)
    assert.equal(e.texto, 'Quitó a Camila del proyecto')
  })
})

describe('historial: estimación', () => {
  it('recálculo: costo anterior → nuevo', () => {
    const e = describir(evento('estimacion_generada', {
      valores_anteriores: { costo_total: 1500000, costo_m2: 10000 },
      valores_nuevos: { costo_total: 1800000, costo_m2: 12000, completa: true },
    }))
    assert.equal(e.texto, 'Recalculó la estimación')
    assert.deepEqual(filas(e.cambios).map(([c, a, n]) => [c, sinEspacio(a), sinEspacio(n)]),
      [['Costo total', '$1.500.000', '$1.800.000']])
  })

  it('primera estimación: no había costo previo', () => {
    const e = describir(evento('estimacion_generada', {
      valores_anteriores: { costo_total: null, costo_m2: null }, valores_nuevos: { costo_total: 1800000 },
    }))
    assert.equal(e.texto, 'Generó una nueva estimación')
    assert.deepEqual(filas(e.cambios).map(([c, a, n]) => [c, a, sinEspacio(n)]),
      [['Costo total', 'Sin estimación previa', '$1.800.000']])
  })

  it('evento antiguo sin valores anteriores: solo el nuevo, sin inventar el previo', () => {
    const e = describir(evento('estimacion_generada', { valores_nuevos: { costo_total: 1800000 } }))
    assert.equal(e.texto, 'Generó una nueva estimación')
    assert.deepEqual(filas(e.cambios).map(([c, a, n]) => [c, a, sinEspacio(n)]), [['Costo total', null, '$1.800.000']])
  })
})

describe('historial: formatos', () => {
  it('dinero, m², porcentaje, booleanos y roles', () => {
    assert.equal(sinEspacio(formatearValor('costo_total', 1800000)!), '$1.800.000')
    assert.equal(formatearValor('superficie_m2', 50), '50 m²')
    assert.equal(formatearValor('utilidad_pct', 12), '12 %')
    assert.equal(formatearValor('gastos_generales_pct', '12.5'), '12,5 %')
    assert.equal(formatearValor('completa', true), 'Sí')
    assert.equal(formatearValor('completa', false), 'No')
    assert.equal(formatearValor('rol', 'propietario'), 'Propietario')
  })

  it('valores nulos con el significado de cada campo', () => {
    assert.equal(formatearValor('cantidad', null), 'Sin definir')
    assert.equal(formatearValor('precio_unitario_override', null), 'Precio del banco')
    assert.equal(formatearValor('observacion', ''), 'Sin observación')
  })

  it('un campo técnico desconocido o un valor ilegible no se muestran', () => {
    assert.equal(formatearValor('campo_interno', 5), undefined)
    assert.equal(formatearValor('superficie_m2', 'mucho'), undefined)
    const e = describir(evento('proyecto_editado', {
      valores_anteriores: { campo_interno: 1, superficie_m2: 'mucho' }, valores_nuevos: { campo_interno: 2, superficie_m2: 60 },
    }))
    assert.deepEqual(e.cambios, [])
    assert.equal(e.texto, 'Editó el proyecto')
  })
})

describe('historial: datos inesperados', () => {
  it('una acción desconocida cae en el texto genérico, sin cambios', () => {
    const e = describir(evento('proyecto_archivado', { valores_anteriores: { estado: 'a' }, valores_nuevos: { estado: 'b' } }))
    assert.equal(e.texto, DESCRIPCION_GENERICA)
    assert.deepEqual(e.cambios, [])
    assert.equal(DESCRIPCION_GENERICA, 'Se actualizó el proyecto.')
  })

  it('sin datos específicos usa una descripción genérica de la misma acción', () => {
    assert.equal(describir(evento('partida_agregada')).texto, 'Agregó una partida al proyecto')
    assert.equal(describir(evento('partida_eliminada')).texto, 'Eliminó una partida del proyecto')
    assert.deepEqual(describir(evento('partida_agregada')).cambios, [])
    assert.deepEqual(describir(evento('miembro_rol_cambiado')).cambios, [])
  })

  it('nunca muestra JSON crudo ni [object Object]', () => {
    const raros = {
      nombre: { anidado: true }, rol: ['editor'], email: { a: 1 }, costo_total: { v: 1 }, partidas: {},
      cantidad: [1, 2], superficie_m2: { m: 2 }, comuna: null, precio_unitario_override: { x: 1 },
    }
    for (const accion of ['miembro_agregado', 'miembro_rol_cambiado', 'miembro_eliminado', 'proyecto_editado',
      'partida_agregada', 'partida_editada', 'partida_eliminada', 'plantilla_aplicada', 'estimacion_generada', 'otra']) {
      const entrada = describir(evento(accion, {
        valores_anteriores: raros, valores_nuevos: { ...raros, comuna: 'Concón' }, usuario_nombre: null,
        usuario_email: { x: 1 } as unknown as string,
      }))
      const textos = [entrada.texto, entrada.autor, ...entrada.cambios.flatMap((c) => [c.campo, c.anterior ?? '', c.nuevo])]
      for (const parte of textos) {
        assert.doesNotMatch(parte, /\[object|[{}[\]]|"/, `${accion}: ${parte}`)
      }
    }
  })

  it('valores que no son objetos no rompen la descripción', () => {
    const e = describir(evento('partida_agregada', { valores_nuevos: 'texto' as unknown as Record<string, unknown> }))
    assert.equal(e.texto, 'Agregó una partida al proyecto')
    assert.deepEqual(e.cambios, [])
  })
})

describe('historial: autor y fecha', () => {
  it('usa el nombre, luego el correo', () => {
    assert.equal(describir(evento('x')).autor, 'Ángel González')
    assert.equal(describir(evento('x', { usuario_nombre: null })).autor, 'angel@x.cl')
    assert.equal(describir(evento('x', { usuario_nombre: null, usuario_email: null })).autor, 'Usuario sin cuenta')
  })

  it('formatea la fecha y la hora', () => {
    assert.equal(describir(evento('x')).fecha, '20 oct 2026 · 15:20')
    assert.equal(fechaEvento('2026-01-05T09:07:00'), '5 ene 2026 · 09:07')
    assert.equal(fechaEvento('no es fecha'), '')
    assert.equal(fechaEvento(null), '')
  })
})

describe('historial: carga', () => {
  it('eventos cargados', async () => {
    const h = crearHistorial(async () => [evento('proyecto_editado')])
    assert.equal(h.cargado, false)
    const carga = h.cargar()
    assert.equal(h.cargando, true)
    await carga
    assert.deepEqual([h.cargando, h.cargado, h.error, h.eventos.length], [false, true, '', 1])
  })

  it('historial vacío', async () => {
    const h = crearHistorial(async () => [])
    await h.cargar()
    assert.deepEqual([h.cargado, h.eventos], [true, []])
  })

  it('error de carga', async () => {
    for (const [error, mensaje] of [
      [new ErrorApi(404, 'Proyecto no encontrado'), /No tienes acceso/],
      [new ErrorApi(0, 'x'), /No se pudo conectar/],
      [new ErrorApi(401, 'x'), /sesión expiró/],
      [new TypeError('red'), /No se pudo cargar el historial/],
    ] as const) {
      const h = crearHistorial(async () => { throw error })
      await h.cargar()
      assert.equal(h.cargado, false)
      assert.match(h.error, mensaje)
    }
  })

  it('no lanza dos cargas a la vez', async () => {
    let veces = 0
    const h = crearHistorial(async () => { veces++; return [] })
    await Promise.all([h.cargar(), h.cargar()])
    assert.equal(veces, 1)
  })
})

describe('historial: plazo para la cotización', () => {
  const plazo = (anteriores: Record<string, unknown>, nuevos: Record<string, unknown>) =>
    describir(evento('plazo_profesional_definido', { entidad: 'estimacion', valores_anteriores: anteriores,
      valores_nuevos: nuevos }))

  it('definido por primera vez', () => {
    const e = plazo({ plazo_profesional_dias: null, plazo_profesional_estado: 'sin_definir' },
      { plazo_profesional_dias: 135, plazo_profesional_origen: 'manual' })
    assert.equal(e.texto, 'Plazo para cotización definido: 135 días')
    assert.deepEqual(filas(e.cambios), [['Origen', null, 'Escrito por el profesional']])
  })

  it('actualizado: anterior → nuevo', () => {
    const e = plazo({ plazo_profesional_dias: 135, plazo_profesional_estado: 'definido' },
      { plazo_profesional_dias: 150, plazo_profesional_origen: 'manual' })
    assert.equal(e.texto, 'Plazo para cotización actualizado: 135 → 150 días')
  })

  it('usar la sugerencia queda como origen', () => {
    const e = plazo({ plazo_profesional_dias: 135, plazo_profesional_estado: 'definido' },
      { plazo_profesional_dias: 120, plazo_profesional_origen: 'sugerencia' })
    assert.equal(e.texto, 'Plazo para cotización actualizado: 135 → 120 días')
    assert.deepEqual(filas(e.cambios), [['Origen', null, 'Sugerencia de BuildCast']])
  })

  it('confirmado al salir de por revisar con el mismo valor', () => {
    const e = plazo({ plazo_profesional_dias: 135, plazo_profesional_estado: 'por_revisar' },
      { plazo_profesional_dias: 135, plazo_profesional_origen: 'manual' })
    assert.equal(e.texto, 'Plazo para cotización confirmado: 135 días')
  })

  it('cambiar un valor por revisar también es una actualización', () => {
    const e = plazo({ plazo_profesional_dias: 135, plazo_profesional_estado: 'por_revisar' },
      { plazo_profesional_dias: 160, plazo_profesional_origen: 'manual' })
    assert.equal(e.texto, 'Plazo para cotización actualizado: 135 → 160 días')
  })

  it('un recálculo deja el plazo por revisar', () => {
    const e = describir(evento('plazo_profesional_por_revisar', { entidad: 'estimacion',
      valores_anteriores: { plazo_profesional_dias: 135, plazo_profesional_estado: 'definido' },
      valores_nuevos: { plazo_profesional_dias: 135, plazo_profesional_estado: 'por_revisar' } }))
    assert.equal(e.texto, 'Plazo para cotización por revisar tras recalcular: 135 días')
    assert.deepEqual(filas(e.cambios), [['Plazo para la cotización', 'Definido', 'Por revisar']])
  })

  it('por revisar sin días legibles: texto genérico, sin JSON', () => {
    const e = describir(evento('plazo_profesional_por_revisar', { entidad: 'estimacion',
      valores_anteriores: {}, valores_nuevos: { version_modelo: 'v1.0-2026-11-01' } }))
    assert.equal(e.texto, 'Plazo para cotización por revisar tras recalcular')
    assert.deepEqual(e.cambios, [])
  })

  it('sin datos legibles: texto genérico de la acción, sin JSON ni datos del modelo', () => {
    const e = plazo({}, { version_modelo: 'v1.0-2026-11-01' })
    assert.equal(e.texto, 'Definió el plazo para la cotización')
    assert.deepEqual(e.cambios, [])
  })
})
