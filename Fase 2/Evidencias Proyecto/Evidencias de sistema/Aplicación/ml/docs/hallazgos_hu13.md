# Hallazgos de HU-13: revisión de los 17 presupuestos reales de RAM

Fecha de revisión: 2026-10-29. Fuente: los 17 PDFs de `ml/data/raw/` (no versionados; contienen datos de clientes). Transcripción: `ml/data/processed/presupuestos_reales.csv`. Las preguntas pendientes para RAM están en `consultas_ram.md`.

## 1. Para la Sprint Review

### 1.1 Pisos y estándar de terminaciones no existen en los datos reales

- **`numero_pisos` no aparece en ninguno de los 17 presupuestos.** La única mención es indirecta: en R10 la vivienda existente tiene "2do piso", pero la obra es una reparación y no informa pisos construidos.
- **`estandar_terminaciones` no aparece en ninguno de los 17 presupuestos.** Algunos materiales sugieren un nivel (porcelanato y ventanas PVC termopanel en R01; piso flotante y aluminio blanco en R11), pero RAM no los clasifica y no corresponde que ML lo infiera sin validarlo.

**Consecuencia.** Ambas son entradas obligatorias del formulario de BuildCast, pero su efecto en el plazo no se puede aprender ni validar con datos reales. En los sintéticos, su efecto vendría solo de las reglas del generador.

**Decisión pendiente:**
- (a) RAM clasifica a posteriori los casos reales; o
- (b) se mantienen en el formulario, pero el modelo de plazo no las usa y la interfaz lo declara; o
- (c) se usan solo vía factores expertos documentados.

### 1.2 Decisiones de alcance tomadas en HU-13 (2026-10-29)

1. **Universo:** los 14 presupuestos con plazo explícito, de edificación y obras menores juntos. `clase_obra` es variable, no filtro.
2. **Costo como predictor:** `costo_neto_clp` / `costo_neto_uf` son predictores candidatos, porque el motor de costos calcula el costo antes que el plazo. Esto cambia el contrato del endpoint (ver `notas_backend.md`, punto 5).
3. **Regla paramétrica:** la principal es **P2 (plazo por costo, calibrada en los 14 casos)**, como línea base y contingencia. Reemplaza a la forma "días por m² ajustados por pisos y estándar" de la especificación (P1), que queda solo documentada porque solo 5 casos tienen superficie y ninguno tiene pisos ni estándar. Método en `criterios_inclusion.md`. **Actualización 2026-11-01:** P2 se calibró con 13 casos (sin R07) y se evaluó con LOO en 12, y P1 se evaluó en su subconjunto de 4 casos. Resultados en `model_card_v1.0-2026-11-01.md`.
4. **R08 (local comercial, La Ligua):** entra con `plazo_es_cota = true` y se reporta aparte. Su nombre de archivo se reemplazó por un alias neutro.
5. **R13 (cobertizo):** `clase_obra = puntual`, `tipo_obra = obra_nueva`. **Modificado el 2026-11-01:** `tipo_obra = obra_menor_varia` (sigue puntual). `obra_nueva` pasa a ser siempre edificación y el mapeo de tipo a clase queda determinista (ver `criterios_inclusion.md`, "Decisiones del 2026-11-01").
6. **Plazos:** se leen como **días corridos** (semanas × 7). Consulta pendiente a RAM.
7. **Fechas:** se acepta la lectura día/mes de las fechas ambiguas y la corrección de la errata de R17.

## 2. Hallazgos de calidad

| Hallazgo | Casos | Tratamiento |
|---|---|---|
| **Todos los plazos son ofertados**; ninguno es plazo ejecutado. Los plazos ofertados suelen ser optimistas y están redondeados (5 días, 2 / 3 / 6 semanas). | 17 de 17 | `tipo_plazo = ofertado`. El modelo estima "plazo que RAM oferta". Se declara en la model card y en la interfaz. |
| Plazo no informado ("acordar con cliente" o línea vacía). | R01, R12, R15 | `utilizable = false`, `E2`. |
| Plazo expresado como cota ("hasta 5 semanas como máximo"). | R08 | `plazo_dias = 35`, `plazo_es_cota = true`, se reporta aparte. |
| **El IVA de R08 no cuadra** (detalle en la sección 3). | R08 | Se usa el neto de $9.500.000. Consulta a RAM. |
| **IVA incierto en R07**: el documento no muestra línea de IVA. | R07 | Se asume provisionalmente que $3.100.000 es neto, con nota en `notas_calidad`. Consulta a RAM. |
| Solo dos documentos incluyen IVA; los demás muestran IVA $0. | R03, R08 | Siempre se guarda el neto. |
| Gastos generales y utilidad muy variables (0% a 20%). | todos | Se registra en `gg_utilidad_pct`. |
| **Errata de plantilla**: el título dice "COBERTIZO ESTACIONAMIENTO" en trabajos que no lo son. | R05 (muro divisor), R06 (radier) | Se clasifican por el contenido, no por el título. |
| **Revisión distinta** entre el nombre de archivo y el documento. | R03, R06 (archivo REV-01, documento REV-04), R09, R11, R13 (archivo REV0, documento REV-02), R14, R15, R16 | Se guarda la revisión del documento. No se encontraron dos revisiones del mismo proyecto. Consulta a RAM. |
| **Fecha con errata** "10/011/2025". | R17 | Se transcribe como 2025-11-10. Lectura aceptada por la usuaria; queda nota en el CSV. |
| Fechas `dd/mm/aaaa` ambiguas (día ≤ 12). | R02, R06, R09 | Se leen como día/mes. Lectura aceptada por la usuaria; queda nota en el CSV. |
| Documento sin fecha ni comuna, en formato de planilla distinto. | R07 (cabaña Laguna Verde) | Comuna inferida (Laguna Verde → Valparaíso), fecha vacía y, por lo tanto, sin UF. |
| La comuna del documento es una localidad. | R12 (Reñaca), R06 y R15 (Mantagua) | Se normaliza a comuna oficial y se conserva `localidad`. |
| Superficie: explícita en 3 casos e inferida del documento en 3; falta en 11. | explícita R01, R08, R11; inferida R03, R06, R17 | `superficie_fuente`. Por eso el costo se usa como medida de tamaño (P2). |
| **UF cargada el 2026-10-31** desde la API de la CMF con la API key de la usuaria (antes, CMF y Banco Central exigían credenciales). | 16 de 17 | `costo_neto_uf` calculada por `ml/src/uf.py` con la UF del día de `fecha_documento`. Detalle en la sección 4. |
| `costo_neto_uf` vacía por falta de fecha. | R07 | Sin `fecha_documento` no hay UF que aplicar; no se imputa. R07 es utilizable, así que en el universo de 14 casos `costo_neto_uf` cubre 13. |
| El nombre de archivo de R08 contenía el nombre comercial del cliente. | R08 | Alias `PPTO-LOCAL-COMERCIAL-LA-LIGUA-REV-01.pdf`. El mapa al nombre real está en `data/raw/alias_archivos.csv` (ignorado por git). |

## 3. Costo neto de R08: evidencia y resolución

Documento: PDF de una sola página (presupuesto del local comercial de La Ligua, REV-01, 24-09-2026).

| Línea del PDF (p. 1) | Monto |
|---|---|
| 1.1 Trabajo de mano de obra para local de 90 m2 | $4.000.000 |
| 2.1 Materiales (piso autonivelante, tabiquería, cielo falso, terminaciones, puerta, materiales eléctricos) | $5.000.000 |
| 3.1 Mano de obra especialidad eléctrica | $500.000 |
| Total Costo Directo | $9.500.000 |
| Gastos Generales y leyes sociales (0,00%) y segunda línea (0,00%) | $0 y $0 |
| Subtotal sin IVA | $9.500.000 |
| Impuestos (IVA 19%) | $2.228.395 |
| COSTO TOTAL | $11.728.395 |
| Condición final: "Ppto incluye mano de obra sin materiales" | — |

Lo que se puede verificar con estos montos:
- Las partidas suman exactamente el costo directo: 4.000.000 + 5.000.000 + 500.000 = 9.500.000. Ese valor coincide con el subtotal sin IVA.
- El total menos el IVA da 9.500.000, así que el total es aritméticamente coherente con el subtotal.
- El IVA no es el 19% del neto, que serían $1.805.000. **Es el 19% del total**: 0,19 × 11.728.395 = 2.228.395. Es decir, el total se calculó como 9.500.000 / 0,81, un error de fórmula en la planilla que calcula el IVA "por dentro".

**Decisión: neto = $9.500.000.** Es el único valor respaldado por dos fuentes independientes del documento (la suma de partidas y el "Subtotal sin IVA") y el error está aislado en la línea de IVA. Además, es comparable con el `costo_total` del motor, que incluye materiales y no incluye IVA.

Otras lecturas posibles, descartadas por ahora:
- (a) **Total / 1,19 = $9.855.794**, si se confiara en el total impreso. Contradice la suma de partidas y el subtotal.
- (b) **Solo mano de obra = $4.500.000** (partidas 1.1 + 3.1), si "mano de obra sin materiales" significara que el cliente compra los materiales y la partida 2.1 fuera solo referencial. Sería un alcance distinto del que estima el motor (que incluye materiales). Si RAM confirma esta lectura, habría que cambiar el neto o marcar el caso como de alcance no comparable.

No se propone cambiar el neto; queda sujeto a la respuesta de RAM (`consultas_ram.md`).

## 4. Conversión a UF (2026-10-31)

Ejecución: `python ml/src/uf.py`. Una sola llamada a la API de la CMF (`uf/posteriores/2025/01`); la serie quedó en la caché `ml/data/processed/uf_cmf.csv`. La API key no se escribe en la caché, el CSV ni los mensajes.

- **Serie descargada:** 647 valores diarios, del 2025-02-01 al 2026-11-09, sin días faltantes. Valor mínimo 38.362,10 y máximo 41.295,46 CLP.
- **Cobertura:** 16 de 17 filas con `costo_neto_uf`; 1 nula (R07, sin fecha). En los 14 utilizables: 13 completadas, 1 nula (R07). Ninguna fecha del dataset es posterior al día de cálculo.
- **Rango de `costo_neto_uf`:** 14,56 UF (R05) a 791,94 UF (R01, no utilizable). En los utilizables: 14,56 UF (R05) a 438,95 UF (R11).
- **Diferencias con el CSV anterior:** solo cambió la columna `costo_neto_uf` en las 16 filas; el resto del archivo (entrecomillado, fin de línea, BOM) se conserva.

Anomalías y observaciones:
1. **La serie empieza el 2025-02-01, no el 2025-01-01.** El endpoint `posteriores/2025/01` devuelve los días posteriores a enero de 2025, aunque el docstring de `uf.py` y su constante `FECHA_MINIMA` dicen 2025-01-01. No afecta al dataset actual (la fecha más antigua es 2025-11-10), pero una fecha de enero de 2025 fallaría con "No hay valor de UF" en vez del mensaje de fecha fuera de rango. **Corregido el 2026-11-01:** `FECHA_MINIMA = 2025-02-01` en `uf.py`, con el docstring alineado.
2. **Tramos de UF constante.** La UF es la misma entre el 2025-11-09 y al menos el 2025-11-17 (39.643,59) y entre el 2026-03-09 y el 2026-04-09 (39.841,72). Por eso R03, R05, R13 y R17 comparten valor de UF, y también R09 y R15. Es coherente con la metodología de la UF (del 10 de un mes al 9 del siguiente se reajusta según el IPC del mes anterior, y con IPC 0% queda plana), pero no se contrastó contra el IPC publicado por el INE.
3. **La caché contiene fechas futuras** (hasta el 2026-11-09), porque la CMF publica la UF por adelantado hasta el día 9 del mes siguiente. Son valores oficiales, no proyecciones.
4. La UF corrige solo la inflación general entre nov-2025 y sep-2026 (la UF subió un 3,4% entre las fechas extremas del dataset). No corrige diferencias de precios propias de la construcción ni la variación de gastos generales y utilidad entre documentos.

### 4.1 Hallazgos del modelado (2026-11-01)

- **R13 recodificado** a `obra_menor_varia` (antes `obra_nueva`, con clase puntual). El validador da OK tras el cambio.
- **R05 es atípico frente al costo:** muro divisor de 14,56 UF y 14 días. P2 le predice 1,8 días (residuo log de 2,04, el mayor de los 12) y ese caso define casi solo el factor superior del intervalo (×5,15). No se excluyó. Queda como consulta a RAM (`consultas_ram.md`, consulta 20).
- **R08 con su cota empuja γ hacia arriba.** P2 calibrada sin R08 obtiene en LOO un MAE de 4,93 días, frente a 5,60 con R08. Se mantiene R08 por decisión de la usuaria. Queda como consulta a RAM (consulta 21).
- **Los sintéticos no ayudaron:** ningún candidato bajó su MAE real con ellos.
- **La regla de empate original estaba mal especificada** y se corrigió. La original comparaba la diferencia de MAE con la DE del error absoluto por caso ("1,22 < 5,52, empate técnico"); esa justificación queda **superada**. La regla corregida compara con el error estándar de la diferencia pareada, `SE = DE(|e_P2| − |e_Ridge|)/√n = 4,086/√12 = 1,180`. Con ella, Ridge supera el umbral por 0,045 días (1,225 frente a 1,180).
- **Robustez: P2 y Ridge son estadísticamente indistinguibles.**
  - Cada uno gana 6 de los 12 casos.
  - Wilcoxon pareado exacto: p = 0,91. La t pareada da p = 0,32.
  - La ventaja de Ridge se concentra en R11, que aporta 11,70 de los 14,70 días de diferencia; sin R11, la diferencia es de unos 0,27 días.
  - La ventaja se invierte sin R08: P2 obtiene 4,93 y Ridge 5,27.
- **Decisión de la usuaria:** se mantiene P2 (`v1.0-2026-11-01`, provisional) porque la ventaja de Ridge depende de incluir R08, que es una cota imprecisa. Ridge queda como alternativa a reevaluar con más datos. Los metadatos del artefacto se regeneraron el 2026-11-01 sin cambios en el modelo. `seleccion` guarda ahora por separado el veredicto de la regla corregida (`candidato_supera`, margen 0,045) y la decisión (`P2`, con su motivo). El detalle está en `model_card_v1.0-2026-11-01.md`, secciones "Selección" y "Sensibilidad".

Resumen de sensibilidad (LOO, 12 casos, días):

| | P2 | Ridge |
|---|---|---|
| MAE con R08 en el entrenamiento (entregado) | 5,60 | 4,37 |
| MAE sin R08 | 4,93 | 5,27 |
| Casos ganados (pareado) | 6 | 6 |
| Intervalo con R05: factores / plazo de 12 días / cobertura | ×0,48–×5,15 / 5–62 / 0,833 | ×0,35–×4,22 / 4–51 / 0,833 |
| Intervalo sin R05 en los residuos | ×0,47–×1,89 / 5–23 / 0,750 | ×0,34–×1,69 / 4–21 / 0,750 |

Diferencia pareada media de 1,225 días (DE 4,086, SE 1,180), Wilcoxon exacto p = 0,910.

## 5. Supuestos de transcripción vigentes

1. Plazo en días corridos (semanas × 7). Aprobado; pendiente de confirmación con RAM.
2. Costo neto = subtotal sin IVA, con gastos generales y utilidad; es la misma definición que el `costo_total` del motor.
3. R07: total asumido neto (IVA incierto).
4. Fechas ambiguas leídas como día/mes; R17 como 2025-11-10. Aprobado.
5. `costo_neto_uf` = costo neto dividido por la UF CMF del día de `fecha_documento`; vacía si no hay fecha (R07).

## 6. Párrafo para el acta

En el cierre de HU-13 se transcribieron de forma anonimizada los diecisiete presupuestos reales de RAM a un dataset procesado con columna de origen, marcas de calidad y trazabilidad al documento fuente. El archivo del local comercial de La Ligua se identifica con un alias neutro y su correspondencia con el nombre real se guarda fuera del control de versiones. Por decisión de alcance, el universo comprende los catorce casos con plazo explícito, de edificación y obras menores, con la clase de obra como variable. Los tres presupuestos sin plazo permanecen como no utilizables y el caso de La Ligua entra con su plazo marcado como cota superior para reportarse aparte. El costo neto calculado por el motor se incorporó como predictor candidato, dado que en la aplicación se conoce antes que el plazo. La regla paramétrica principal, que será línea base y contingencia, pasa a ser una relación robusta entre plazo y costo calibrada sobre los catorce casos, y la forma de días por metro cuadrado queda solo documentada porque apenas cinco casos informan superficie y ninguno informa pisos ni estándar. Esta regla aún no se calibra ni se mide. La conversión del costo a UF, que quedó pendiente en un principio porque las fuentes oficiales exigían credenciales, se completó el 31 de octubre con la API de la CMF y la clave de la Encargada de Machine Learning. Se usó la UF del mismo día de cada cotización, a partir de una serie diaria guardada en caché. Quedaron convertidas dieciséis de las diecisiete filas; la cabaña de Laguna Verde queda sin valor porque su documento no tiene fecha. Un validador automático confirmó diecisiete filas, catorce utilizables y ningún error. Para la Sprint Review se llevan la ausencia de pisos y estándar en los datos reales, el hecho de que todos los plazos sean ofertados, el cambio de forma de la regla paramétrica y una lista de consultas a RAM orientada a obtener plazos ejecutados.
