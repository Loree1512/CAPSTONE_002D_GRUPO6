// Ejecutar desde frontend/:  npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import {
  advertenciaSugerencia, AVISO_COSTO_PARCIAL, AVISO_EXTRAPOLACION, avisoPlazo, bloqueoCronograma, confirmarSugerencia,
  conPlazo, diasParaCronograma, diferenciaConSugerencia, esExtrapolacion, etiquetaModelo, filasTransparenciaModelo,
  filasTransparenciaProfesional, fuenteCronograma, hayPlazo, leerPlazoEscrito, lineaErrorMedio, plazoDelProyecto,
  plazoNoDisponible, presentarPlazo, presentarPlazoProfesional, profesionalSinDefinir, puedeGuardarPlazoEscrito,
  rotuloCronograma, SIN_METRICA_RESPALDO, textoErrorMedio, textoEstadoModelo, textoPlazo, textoRango, versionCorta,
} from '../src/lib/plazo.ts'
import { puedeEditarPlazo } from '../src/lib/observaciones.ts'
import type { OpcionesConfirmacion } from '../src/lib/confirmar.ts'
import type { Estimacion, EstadoPlazo, PlazoEstimacion, PlazoProfesional } from '../src/tipos/estimacion.ts'

const leer = (archivo: string) => readFileSync(new URL(`../${archivo}`, import.meta.url), 'utf8')

// Lo que devuelve el backend para una Ampliación de $12.000.000 (290,8 UF) el 2026-11-03.
const DENTRO: PlazoEstimacion = {
  dias: 41, minDias: 19, maxDias: 209, metodo: 'P2', estado: 'dentro_dominio', fueraDominio: false,
  provisional: true, motivo: null, versionModelo: 'v1.0-2026-11-01', tipoObraModelo: 'ampliacion',
  ufValor: 41263.57, ufFecha: '2026-11-03',
}
const con = (cambios: Partial<PlazoEstimacion>): PlazoEstimacion => ({ ...DENTRO, ...cambios })

describe('plazo: textos', () => {
  it('muestra días, rango referencial y versión corta', () => {
    assert.equal(textoPlazo(DENTRO), '41 días')
    assert.equal(textoRango(DENTRO), 'Rango referencial: 19–209 días')
    assert.equal(etiquetaModelo(DENTRO), 'Modelo de plazo v1.0 · Estimación provisional')
    assert.equal(versionCorta('v1.0-2026-11-01'), 'v1.0')
    assert.equal(avisoPlazo(DENTRO), 'Estimación basada en datos históricos limitados.')
  })

  it('fuera del rango histórico lo dice siempre', () => {
    for (const estado of ['fuera_rango_costo', 'tipo_obra_no_representado'] as EstadoPlazo[]) {
      const plazo = con({ estado, fueraDominio: true })
      assert.match(avisoPlazo(plazo), /Fuera del rango histórico disponible/, estado)
      // El valor se muestra igual, como referencial.
      assert.equal(textoPlazo(plazo), '41 días')
    }
  })

  it('estimación incompleta: plazo sobre costo parcial', () => {
    assert.match(avisoPlazo(con({ estado: 'costo_incompleto', fueraDominio: true })),
      /^Plazo provisional calculado sobre costo parcial/)
  })

  it('respaldo: se identifica como valor de respaldo', () => {
    const plazo = con({ estado: 'respaldo', metodo: 'mediana_respaldo', dias: 14, minDias: 2, maxDias: 35,
      ufValor: null, ufFecha: null, fueraDominio: true })
    assert.equal(etiquetaModelo(plazo), 'Modelo de plazo v1.0 · Valor de respaldo')
    assert.match(avisoPlazo(plazo), /no considera el tamaño de la obra/)
  })

  it('sin plazo: no inventa días', () => {
    const plazo = plazoNoDisponible('error_estimador')
    assert.equal(hayPlazo(plazo), false)
    assert.equal(textoPlazo(plazo), 'No disponible')
    assert.equal(textoRango(plazo), '')
    assert.equal(diasParaCronograma(plazo), 0)
    assert.equal(etiquetaModelo(plazo), 'Modelo de plazo')
    assert.equal(avisoPlazo(plazo), 'El plazo no está disponible para esta estimación.')
    assert.match(avisoPlazo(plazoNoDisponible('anterior_al_modelo')), /anterior al modelo de plazo/)
    assert.match(avisoPlazo(plazoNoDisponible('simulacion')), /demostración/)
    assert.equal(textoPlazo(undefined), 'No disponible')
  })

  it('nunca usa la palabra confiable', () => {
    const estados: EstadoPlazo[] = ['dentro_dominio', 'fuera_rango_costo', 'tipo_obra_no_representado',
      'costo_incompleto', 'respaldo', 'no_disponible']
    for (const estado of estados) {
      const texto = [avisoPlazo(con({ estado })), etiquetaModelo(con({ estado }))].join(' ')
      assert.doesNotMatch(texto, /confiab/i, estado)
    }
  })
})

describe('plazo: el navegador no lo calcula', () => {
  it('usa el plazo guardado y, sin él, lo marca no disponible', () => {
    const estimacion = { id: 'e1', plazo: DENTRO } as unknown as Estimacion
    assert.equal(conPlazo(estimacion).plazo, DENTRO)
    const antigua = { id: 'e0' } as unknown as Estimacion
    assert.equal(conPlazo(antigua).plazo.estado, 'no_disponible')
    assert.equal(conPlazo(antigua).plazo.dias, null)
  })

  it('ya no existe la fórmula local de plazo', () => {
    for (const archivo of ['src/lib/motorCosto.ts', 'src/lib/estimaciones.ts', 'src/paginas/estimacion.ts']) {
      assert.doesNotMatch(leer(archivo), /estimarPlazo|0\.52|plazoDias/, archivo)
    }
  })

  it('la pantalla del profesional usa la presentación de la sugerencia; el documento no', () => {
    for (const pagina of ['estimacion.html']) {
      const html = leer(pagina)
      for (const campo of ['rotulo', 'principal', 'rango', 'valorModelo', 'rangoTecnico', 'origen', 'avisos']) {
        assert.match(html, new RegExp(`presentacion\\.${campo}`), `${pagina}: ${campo}`)
      }
      // La cifra grande solo cuando esCifra.
      assert.match(html, /presentacion\.esCifra \?/, pagina)
      assert.doesNotMatch(html, /tolerancia|plazoDias|x-html/, pagina)
    }
    assert.match(leer('estimacion.html'), /x-text="presentacion\.estadoCorto"/)
    // El documento del cliente no usa la sugerencia del modelo.
    assert.doesNotMatch(leer('documento.html'), /presentacion\./)
  })
})

// Ejemplos con los valores que devuelve el backend (UF del 2026-11-03).
const VIVIENDA = con({ dias: 170, minDias: 81, maxDias: 876, estado: 'tipo_obra_no_representado',
  motivo: 'costo_sobre_rango', fueraDominio: true, tipoObraModelo: 'obra_nueva' })
const CARA = con({ dias: 324, minDias: 154, maxDias: 1668, estado: 'fuera_rango_costo', motivo: 'costo_sobre_rango',
  fueraDominio: true })
const INCOMPLETA = con({ dias: 19, minDias: 8, maxDias: 96, estado: 'costo_incompleto', motivo: null, fueraDominio: true })
const INCOMPLETA_FUERA = con({ dias: 170, minDias: 81, maxDias: 876, estado: 'costo_incompleto',
  motivo: 'tipo_obra_no_representado', fueraDominio: true, tipoObraModelo: 'obra_nueva' })

describe('plazo: jerarquía visual', () => {
  it('dentro del dominio: Plazo estimado con cifra principal', () => {
    const p = presentarPlazo(DENTRO)
    assert.deepEqual([p.rotulo, p.principal, p.esCifra, p.rango, p.origen],
      ['Plazo estimado', '41 días', true, 'Rango referencial: 19–209 días', 'Modelo de plazo v1.0 · Estimación provisional'])
    assert.deepEqual([p.valorModelo, p.rangoTecnico, p.extrapolacion], ['', '', false])
    assert.deepEqual(p.avisos, ['Estimación basada en datos históricos limitados.'])
  })

  it('tipo de obra no representado: leyenda principal y el valor en segundo plano', () => {
    const p = presentarPlazo(VIVIENDA)
    assert.deepEqual([p.rotulo, p.principal, p.esCifra, p.rango],
      ['Plazo referencial', 'Fuera del rango histórico', false, ''])
    assert.equal(p.valorModelo, 'Valor calculado: 170 días')
    assert.equal(p.rangoTecnico, 'Rango referencial: 81–876 días')
    assert.equal(p.avisos[0], AVISO_EXTRAPOLACION)
    assert.ok(p.avisos.includes('No hay obras de este tipo en los datos históricos.'))
    assert.equal(p.extrapolacion, true)
    // El número no aparece como cifra principal.
    assert.doesNotMatch(p.principal, /\d/)
  })

  it('costo fuera del rango histórico', () => {
    const p = presentarPlazo(CARA)
    assert.equal(p.principal, 'Fuera del rango histórico')
    assert.ok(p.avisos.includes('El costo de la obra supera el rango de los datos históricos.'))
    assert.ok(!p.avisos.includes('No hay obras de este tipo en los datos históricos.'))
    assert.equal(presentarPlazo(con({ estado: 'fuera_rango_costo', motivo: 'costo_bajo_rango' })).avisos.at(-1),
      'El costo de la obra está bajo el rango de los datos históricos.')
  })

  it('incompleta dentro del dominio: sigue siendo plazo provisional sobre costo parcial', () => {
    const p = presentarPlazo(INCOMPLETA)
    assert.deepEqual([p.rotulo, p.principal, p.esCifra, p.extrapolacion], ['Plazo provisional', '19 días', true, false])
    assert.match(p.avisos[0], /^Plazo provisional calculado sobre costo parcial/)
    assert.equal(p.estadoCorto, 'Provisional · costo parcial')
  })

  it('incompleta y fuera del dominio: ambas condiciones, sin contradicción', () => {
    const p = presentarPlazo(INCOMPLETA_FUERA)
    assert.deepEqual([p.rotulo, p.principal, p.esCifra], ['Plazo referencial', 'Fuera del rango histórico', false])
    assert.deepEqual(p.avisos.slice(0, 2), [AVISO_COSTO_PARCIAL, AVISO_EXTRAPOLACION])
    assert.ok(p.avisos.includes('No hay obras de este tipo en los datos históricos.'))
    assert.equal(p.estadoCorto, 'Referencial · fuera del rango histórico, costo parcial')
    // No dice a la vez "datos históricos limitados" (eso es dentro del dominio).
    assert.ok(!p.avisos.some((a) => a.includes('datos históricos limitados')))
    assert.equal(esExtrapolacion(INCOMPLETA_FUERA), true)
    assert.equal(esExtrapolacion(INCOMPLETA), false)
  })

  it('respaldo: también baja de jerarquía', () => {
    const p = presentarPlazo(con({ estado: 'respaldo', metodo: 'mediana_respaldo', dias: 14, minDias: 2, maxDias: 35,
      fueraDominio: true, ufValor: null, ufFecha: null }))
    assert.deepEqual([p.rotulo, p.principal, p.esCifra], ['Plazo referencial', 'Valor de respaldo', false])
    assert.equal(p.valorModelo, 'Valor de respaldo del modelo: 14 días')
  })

  it('sin plazo: No disponible', () => {
    const p = presentarPlazo(plazoNoDisponible('anterior_al_modelo'))
    assert.deepEqual([p.principal, p.esCifra, p.valorModelo], ['No disponible', false, ''])
  })

  it('ningún texto usa "confiable"', () => {
    for (const plazo of [DENTRO, VIVIENDA, CARA, INCOMPLETA, INCOMPLETA_FUERA]) {
      const p = presentarPlazo(plazo)
      assert.doesNotMatch([p.rotulo, p.principal, p.valorModelo, p.rangoTecnico, p.estadoCorto, ...p.avisos].join(' '),
        /confiab/i)
    }
  })
})

describe('plazo: cronograma', () => {
  it('incompleta: bloqueado, sin repartir el plazo', () => {
    assert.equal(bloqueoCronograma(false, DENTRO), 'incompleta')
    assert.equal(diasParaCronograma(DENTRO, false), 0)
    // Aunque haya plazo provisional, sigue bloqueado.
    assert.equal(bloqueoCronograma(false, INCOMPLETA), 'incompleta')
  })

  it('completa: cronograma normal', () => {
    assert.equal(bloqueoCronograma(true, DENTRO), '')
    assert.equal(diasParaCronograma(DENTRO, true), 41)
    assert.equal(bloqueoCronograma(true, plazoNoDisponible('error_estimador')), 'sin_plazo')
  })

  it('la página muestra el estado informativo y no reparte con la estimación incompleta', () => {
    const html = leer('estimacion.html')
    const bloqueo = 'bloqueoCronograma\\(presupuesto\\.completa, presupuesto\\.plazo, presupuesto\\.plazoProfesional\\)'
    assert.match(html, new RegExp(`${bloqueo} === 'incompleta'`))
    assert.match(html, /Cronograma no disponible mientras la estimación esté incompleta\./)
    assert.match(html, /Completa las partidas con cantidad y precio para obtener una distribución referencial del plazo\./)
    assert.match(html, new RegExp(`x-if="presupuesto && ${bloqueo} === ''"`))
    assert.match(leer('src/paginas/estimacion.ts'),
      /diasParaCronograma\(this\.presupuesto\.plazo, this\.presupuesto\.completa, this\.presupuesto\.plazoProfesional\)/)
  })
})

describe('plazo: documento y listado', () => {
  it('el documento usa solo el plazo para la cotización', () => {
    const html = leer('documento.html')
    assert.match(html, /x-text="plazoCliente\.texto"/)
    assert.doesNotMatch(html, /presentacion\.|aviso in/)
    assert.match(leer('src/paginas/documento.ts'), /plazoDocumento\(this\.presupuesto\?\.plazoProfesional\)/)
    assert.doesNotMatch(leer('src/paginas/documento.ts'), /presentarPlazo|etiquetaModelo|avisoPlazo|textoRango/)
  })

  it('listado: el plazo para la cotización, nunca el número del modelo', () => {
    const conEstimacion = { ultima_estimacion_id: 'e1' }
    assert.deepEqual(plazoDelProyecto({ ...conEstimacion, plazo_profesional_dias: 135, plazo_profesional_estado: 'definido' }),
      { texto: '135 días', nota: '' })
    assert.deepEqual(plazoDelProyecto({ ...conEstimacion, plazo_profesional_dias: 1668, plazo_profesional_estado: 'definido' }),
      { texto: '1.668 días', nota: '' })
    assert.deepEqual(plazoDelProyecto({ ...conEstimacion, plazo_profesional_dias: 135, plazo_profesional_estado: 'por_revisar' }),
      { texto: '135 días*', nota: 'Por revisar tras recalcular' })
    // Con sugerencia del modelo pero sin decisión del profesional: «Por definir», sin el número.
    const sinDefinir = { ...conEstimacion, plazo_dias: 120, plazo_estado: 'dentro_dominio',
      plazo_profesional_dias: null, plazo_profesional_estado: 'sin_definir' }
    assert.deepEqual(plazoDelProyecto(sinDefinir), { texto: 'Por definir', nota: '' })
    // Estimación anterior a la 010 (backend sin el estado): también por definir.
    assert.deepEqual(plazoDelProyecto(conEstimacion), { texto: 'Por definir', nota: '' })
    // Sin estimación.
    assert.deepEqual(plazoDelProyecto({ ultima_estimacion_id: null, plazo_profesional_estado: null }), { texto: '—', nota: '' })
    assert.deepEqual(plazoDelProyecto({}), { texto: '—', nota: '' })
  })

  it('la tabla no comunica el estado solo con color ni muestra métricas', () => {
    const html = leer('proyectos.html')
    assert.match(html, /x-text="plazoDelProyecto\(p\)\.texto"/)
    assert.match(html, /:title="plazoDelProyecto\(p\)\.nota \|\| null"/)
    assert.match(html, /class="bc-oculto" x-show="plazoDelProyecto\(p\)\.nota"/)
    assert.match(html, /\* Por revisar tras recalcular/)
    assert.doesNotMatch(html.replace(/<!--[\s\S]*?-->/g, ''), /error medio|MAE|p\.plazo_dias/i)
  })
})


/* --- Sugerencia del modelo y plazo para la cotización (migración 010) ----------- */

const SUGERENCIA: PlazoEstimacion = { ...DENTRO, dias: 120, minDias: 85, maxDias: 170, errorMedioDias: 5.597655503039676,
  estadoModelo: 'provisional' }
const DEFINIDO: PlazoProfesional = { dias: 135, estado: 'definido', origen: 'manual', fecha: '2026-11-05T14:00:00Z',
  usuarioId: 'u-1', usuarioNombre: 'Elena Editora' }
const POR_REVISAR: PlazoProfesional = { ...DEFINIDO, estado: 'por_revisar' }

describe('plazo sugerido: error medio y estado del modelo', () => {
  it('el error medio sale del dato de la versión, con un decimal y sin «±»', () => {
    assert.equal(textoErrorMedio(SUGERENCIA), '5,6 días')
    assert.equal(lineaErrorMedio(SUGERENCIA), 'Error medio observado: 5,6 días')
    assert.equal(textoErrorMedio({ ...SUGERENCIA, errorMedioDias: 4.24 }), '4,2 días')
    assert.doesNotMatch(lineaErrorMedio(SUGERENCIA), /±/)
  })

  it('no está escrito a mano en el frontend', () => {
    const sinComentarios = (texto: string) =>
      texto.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/[^\n]*/gm, '')
    for (const archivo of ['src/lib/plazo.ts', 'src/paginas/estimacion.ts', 'estimacion.html']) {
      assert.doesNotMatch(sinComentarios(leer(archivo)), /5[,.]6|5[,.]59/, archivo)
    }
  })

  it('con la mediana de respaldo no hay métrica', () => {
    const respaldo = { ...SUGERENCIA, estado: 'respaldo' as const, metodo: 'mediana_respaldo', errorMedioDias: null }
    assert.equal(textoErrorMedio(respaldo), SIN_METRICA_RESPALDO)
    assert.equal(lineaErrorMedio(respaldo), 'Sin métrica del modelo para esta estimación (valor de respaldo)')
    assert.equal(textoErrorMedio(plazoNoDisponible('simulacion')), '')
  })

  it('«Modelo provisional» o «Modelo validado» según la versión; nunca validado si no lo está', () => {
    assert.equal(textoEstadoModelo(SUGERENCIA), 'Modelo provisional')
    assert.equal(textoEstadoModelo({ ...SUGERENCIA, estadoModelo: 'validado', provisional: false }), 'Modelo validado')
    assert.equal(textoEstadoModelo({ ...SUGERENCIA, estadoModelo: null }), 'Modelo provisional')
    assert.doesNotMatch(textoEstadoModelo({ ...SUGERENCIA, estadoModelo: null, provisional: true }), /validado/)
  })
})

describe('plazo para la cotización', () => {
  it('estimación nueva: sugerencia del modelo, pero sin plazo profesional', () => {
    const p = presentarPlazoProfesional(profesionalSinDefinir())
    assert.deepEqual([p.texto, p.definido, p.porRevisar, p.estadoTexto], ['Sin definir', false, false, 'Sin definir'])
  })

  it('definido y por revisar', () => {
    const d = presentarPlazoProfesional(DEFINIDO)
    assert.deepEqual([d.texto, d.definido, d.origenTexto, d.avisoRevision], ['135 días', true, 'Escrito por el profesional', ''])
    const r = presentarPlazoProfesional(POR_REVISAR)
    assert.equal(r.porRevisar, true)
    assert.equal(r.avisoRevision, 'Por revisar: el presupuesto cambió desde que se definió (135 días).')
  })

  it('valor escrito: entero entre 1 y 3650', () => {
    assert.equal(leerPlazoEscrito('135'), 135)
    assert.equal(leerPlazoEscrito(' 7 '), 7)
    assert.equal(leerPlazoEscrito(''), null)
    for (const malo of ['0', '3651', '12.5', '-3', 'abc']) assert.equal(leerPlazoEscrito(malo), undefined, malo)
  })

  it('guardar: solo si cambia; confirmar uno por revisar sí se permite', () => {
    assert.equal(puedeGuardarPlazoEscrito('135', DEFINIDO), false)
    assert.equal(puedeGuardarPlazoEscrito('150', DEFINIDO), true)
    assert.equal(puedeGuardarPlazoEscrito('135', POR_REVISAR), true)
    assert.equal(puedeGuardarPlazoEscrito('', profesionalSinDefinir()), false)
  })

  it('permisos: propietario y editor lo definen; el lector solo lo ve', () => {
    assert.equal(puedeEditarPlazo('propietario'), true)
    assert.equal(puedeEditarPlazo('editor'), true)
    assert.equal(puedeEditarPlazo('lector'), false)
    assert.equal(puedeEditarPlazo(null), false)
    const html = leer('estimacion.html')
    assert.match(html, /<template x-if="puedeEditarPlazo">/)
  })

  it('una estimación anterior a la 010 queda sin definir (no toma el plazo del modelo)', () => {
    const antigua = { id: 'e0', plazo: DENTRO } as unknown as Estimacion
    assert.deepEqual(conPlazo(antigua).plazoProfesional, profesionalSinDefinir())
    assert.equal(conPlazo(antigua).plazo, DENTRO)
  })
})

describe('«Usar sugerencia»: advertencia fuera del dominio o con el respaldo', () => {
  const pedir = () => {
    const pedidas: OpcionesConfirmacion[] = []
    return { pedidas, fn: async (o: OpcionesConfirmacion) => { pedidas.push(o); return false } }
  }

  it('dentro del dominio no pregunta', async () => {
    const c = pedir()
    assert.equal(await confirmarSugerencia(SUGERENCIA, c.fn), true)
    assert.equal(c.pedidas.length, 0)
    assert.equal(advertenciaSugerencia(SUGERENCIA), '')
  })

  it('fuera del rango histórico: pide confirmación con advertencia visible y respeta el «no»', async () => {
    const c = pedir()
    assert.equal(await confirmarSugerencia(VIVIENDA, c.fn), false)
    assert.equal(c.pedidas.length, 1)
    assert.match(c.pedidas[0].mensaje, /fuera del rango histórico del modelo\. ¿Usarla como plazo para la cotización\?/)
    assert.equal(c.pedidas[0].confirmar, 'Usar sugerencia')
    assert.equal(c.pedidas[0].titulo, '¿Usar la sugerencia de 170 días?')
  })

  it('valor de respaldo: también pregunta; si confirma, se guarda', async () => {
    const respaldo = con({ estado: 'respaldo', metodo: 'mediana_respaldo', dias: 14, fueraDominio: true })
    assert.match(advertenciaSugerencia(respaldo), /valor de respaldo/)
    assert.equal(await confirmarSugerencia(respaldo, async () => true), true)
  })

  it('sin sugerencia (modo demostración) no hay nada que usar', async () => {
    const c = pedir()
    assert.equal(await confirmarSugerencia(plazoNoDisponible('simulacion'), c.fn), false)
    assert.equal(c.pedidas.length, 0)
  })

  it('la página usa el diálogo de lib/confirmar.ts antes de guardar', () => {
    const ts = leer('src/paginas/estimacion.ts')
    assert.match(ts, /confirmarSugerencia\(this\.presupuesto\.plazo, confirmar\)/)
    const usar = /async usarSugerencia\(\) \{[\s\S]*?\n  \},/.exec(ts)?.[0] ?? ''
    assert.ok(usar.indexOf('confirmarSugerencia') < usar.indexOf('definirPlazo'), 'confirma antes de guardar')
    assert.match(leer('estimacion.html'), /x-show="sugerenciaDisponible && advertenciaSugerencia"/)
  })
})

describe('cronograma: qué plazo reparte', () => {
  it('con el plazo profesional definido usa ese y lo dice', () => {
    assert.deepEqual(fuenteCronograma(SUGERENCIA, DEFINIDO), { fuente: 'profesional', dias: 135 })
    assert.equal(diasParaCronograma(SUGERENCIA, true, DEFINIDO), 135)
    assert.equal(rotuloCronograma(SUGERENCIA, DEFINIDO), 'Basado en el plazo para la cotización: 135 días')
  })

  it('por revisar: usa el plazo profesional y lo rotula explícitamente', () => {
    assert.equal(diasParaCronograma(SUGERENCIA, true, POR_REVISAR), 135)
    assert.equal(rotuloCronograma(SUGERENCIA, POR_REVISAR),
      'Basado en el plazo para la cotización (135 días), por revisar tras recalcular')
  })

  it('sin definir: la sugerencia, como distribución referencial interna', () => {
    assert.deepEqual(fuenteCronograma(SUGERENCIA, profesionalSinDefinir()), { fuente: 'sugerencia', dias: 120 })
    assert.equal(rotuloCronograma(SUGERENCIA, profesionalSinDefinir()),
      'Distribución referencial interna con el plazo sugerido por el modelo')
  })

  it('se mantienen los bloqueos: incompleta y sin ningún plazo', () => {
    assert.equal(bloqueoCronograma(false, SUGERENCIA, DEFINIDO), 'incompleta')
    assert.equal(bloqueoCronograma(true, plazoNoDisponible('simulacion'), profesionalSinDefinir()), 'sin_plazo')
    // En la demostración, con plazo escrito por el profesional sí hay cronograma.
    assert.equal(diasParaCronograma(plazoNoDisponible('simulacion'), true, DEFINIDO), 135)
  })

  it('la página rotula el cronograma y escala las barras con los días usados', () => {
    const html = leer('estimacion.html')
    assert.match(html, /<span class="bc-rotulo" x-text="rotuloCronograma"><\/span>/)
    assert.match(html, /e\.desde \/ diasCronograma \* 100/)
    assert.doesNotMatch(html, /presupuesto\.plazo\.dias \* 100|\/ presupuesto\.plazo\.dias/)
  })
})

describe('Transparencia: modelo y profesional', () => {
  it('bloque del modelo: sugerencia, rango, error medio, versión, estado, dominio y método', () => {
    const filas = Object.fromEntries(filasTransparenciaModelo(VIVIENDA).map((f) => [f.etiqueta, f.valor]))
    assert.equal(filas['Plazo sugerido'], '170 días (referencial)')
    assert.equal(filas['Rango referencial de esta estimación'], '81–876 días')
    assert.equal(filas['Versión del modelo'], 'v1.0-2026-11-01')
    assert.equal(filas['Estado del modelo'], 'Provisional')
    assert.equal(filas['Dominio'], 'Fuera del rango histórico: el costo supera el rango de los datos históricos')
    assert.match(filas['Método'], /P2/)
    const conMae = Object.fromEntries(filasTransparenciaModelo(SUGERENCIA).map((f) => [f.etiqueta, f.valor]))
    assert.equal(conMae['Error medio observado del modelo'], '5,6 días')
    assert.equal(conMae['Dominio'], 'Dentro del rango histórico')
  })

  it('bloque del profesional: valor, estado, origen, fecha, autor y diferencia', () => {
    const filas = Object.fromEntries(filasTransparenciaProfesional(DEFINIDO, SUGERENCIA).map((f) => [f.etiqueta, f.valor]))
    assert.equal(filas['Plazo para la cotización'], '135 días')
    assert.equal(filas['Estado'], 'Definido')
    assert.equal(filas['Origen'], 'Escrito por el profesional')
    assert.notEqual(filas['Fecha de definición'], '—')
    assert.equal(filas['Definido por'], 'Elena Editora')
    assert.equal(filas['Diferencia respecto de la sugerencia'], '+15 días')
  })

  it('la diferencia solo aparece si existen ambos', () => {
    assert.equal(diferenciaConSugerencia(DEFINIDO, plazoNoDisponible('simulacion')), '')
    assert.equal(diferenciaConSugerencia(profesionalSinDefinir(), SUGERENCIA), '')
    assert.equal(diferenciaConSugerencia({ ...DEFINIDO, dias: 100 }, SUGERENCIA), '−20 días')
    assert.equal(diferenciaConSugerencia({ ...DEFINIDO, dias: 120 }, SUGERENCIA), 'Sin diferencia')
    const sinDefinir = filasTransparenciaProfesional(profesionalSinDefinir(), SUGERENCIA).map((f) => f.etiqueta)
    assert.ok(!sinDefinir.includes('Diferencia respecto de la sugerencia'))
  })

  it('cuenta sin autor: no inventa un nombre', () => {
    const filas = Object.fromEntries(filasTransparenciaProfesional({ ...DEFINIDO, usuarioId: null, usuarioNombre: null },
      SUGERENCIA).map((f) => [f.etiqueta, f.valor]))
    assert.equal(filas['Definido por'], '—')
  })

  it('la página muestra ambos bloques', () => {
    const html = leer('estimacion.html')
    assert.match(html, /x-for="f in transparenciaModelo"/)
    assert.match(html, /x-for="f in transparenciaProfesional"/)
  })
})

describe('modo demostración', () => {
  const simulada = leer('src/lib/apiSimulada.ts')

  it('no hay sugerencia del modelo: «Usar sugerencia» queda deshabilitado', () => {
    assert.match(simulada, /plazo: plazoNoDisponible\('simulacion'\)/)
    assert.equal(hayPlazo(plazoNoDisponible('simulacion')), false)
    assert.match(leer('estimacion.html'), /:disabled="!sugerenciaDisponible \|\| guardandoPlazo \|\| guardando"/)
  })

  it('el plazo manual sí se permite y recalcular lo deja por revisar', () => {
    assert.match(simulada, /definirPlazoProfesional: async \(/)
    assert.match(simulada, /origen = 'manual'/)
    assert.match(simulada, /Esta estimación no tiene un plazo sugerido por el modelo\./)
    assert.match(simulada, /return \{ \.\.\.pp, estado: 'por_revisar' \}/)
    assert.equal(puedeGuardarPlazoEscrito('90', profesionalSinDefinir()), true)
  })
})
