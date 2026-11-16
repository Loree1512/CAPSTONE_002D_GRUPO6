# Diccionario de variables: dataset de plazo (HU-13)

Archivo: `ml/data/processed/presupuestos_reales.csv` (17 filas reales). Los sintéticos, cuando existan, usarán las mismas columnas con `origen_dato = sintetico`.
Validador: `python ml/src/validar_dataset.py`. Este documento y el diccionario `ESQUEMA` del script deben coincidir.

Convenciones:
- Vacío significa "no informado" en columnas numéricas. En las categóricas se usa `ni`.
- Booleanos en minúscula: `true` / `false`.
- Fechas en ISO `AAAA-MM-DD`. Los documentos de RAM vienen en `dd/mm/aaaa` o `dd-mm-aaaa` y se transcriben con ese orden.
- Montos en CLP enteros, sin separadores de miles.
- No se guardan nombres ni teléfonos de clientes. La columna `oferente` del PDF no se transcribe.

Valores de la columna **Rol**: `id` = identificación y trazabilidad, `predictor` = candidato a variable de entrada, `objetivo` = lo que se predice, `flag` = marca de calidad, `meta` = control del dataset.

| Columna | Tipo | Unidad | Dominio | Oblig. | Origen | Rol | Descripción |
|---|---|---|---|---|---|---|---|
| `id_caso` | str | — | `R01…R17` reales, `S0001…` sintéticos; único | Sí | derivada | id | Identificador anónimo del caso. |
| `archivo_origen` | str | — | nombre exacto del PDF en `data/raw/`, o alias neutro si el nombre contiene datos del cliente | Sí si `real` | real | id | Trazabilidad al documento fuente. Los alias se resuelven con `data/raw/alias_archivos.csv` (columnas `alias,archivo_real`; ignorado por git). Hoy solo R08 usa alias. |
| `revision` | str | — | p. ej. `REV-01`; vacío si el documento no la indica | No | real | id | Revisión impresa en el documento, que puede diferir del nombre de archivo. |
| `origen_dato` | cat | — | `real`, `sintetico` | Sí | derivada | meta | Los sintéticos solo entran al entrenamiento, nunca a la evaluación. |
| `clase_obra` | cat | — | `edificacion`, `puntual` | Sí | derivada | predictor | Se deriva de `tipo_obra` con el mapeo determinista (ver `tipo_obra`). **Es variable, no filtro.** En el modelo entra como indicador `edif` (1 = edificación). |
| `tipo_obra` | cat | — | `ampliacion`, `obra_nueva`, `alteracion_interior`, `habilitacion_comercial`, `reparacion_mantencion`, `terminaciones`, `muro_cierre`, `radier`, `remodelacion_bano_cocina`, `obra_menor_varia` | Sí | real / sintético | predictor | Vocabulario cerrado. Combinaciones válidas con `clase_obra`: **edificacion** → `ampliacion`, `obra_nueva`, `alteracion_interior`, `habilitacion_comercial`; **puntual** → `reparacion_mantencion`, `terminaciones`, `muro_cierre`, `radier`, `remodelacion_bano_cocina`, `obra_menor_varia`. **El mapeo `tipo_obra → clase_obra` es determinista** desde el 2026-11-01: `obra_nueva` es siempre edificación. R13 (cobertizo, estructura nueva no habitable) se recodificó de `obra_nueva` a `obra_menor_varia` y sigue siendo `puntual`. `ml/src/predict.py` deduce la clase con este mapeo. La base de datos hoy acepta texto libre (ver `notas_backend.md`). |
| `comuna` | cat | — | `Viña del Mar`, `Valparaíso`, `Concón`, `Quilpué`, `Villa Alemana`, `Quintero`, `La Ligua` (se amplía al aparecer nuevas) | Sí | real / sintético | predictor | Comuna oficial normalizada (Reñaca y Recreo → Viña del Mar, Mantagua → Quintero, Cerro Alegre y Laguna Verde → Valparaíso). |
| `comuna_fuente` | cat | — | `documento`, `inferida_localidad`, `sintetica` | Sí | derivada | flag | Indica si la comuna se dedujo de la localidad. |
| `localidad` | str | — | texto | No | real | id | Localidad o sector tal como aparece en el documento o en el nombre de archivo. |
| `materialidad` | cat | — | `albanileria`, `metalcon`, `madera`, `hormigon`, `acero`, `mixta`, `no_aplica`, `ni` | Sí | real / sintético | predictor | Sistema constructivo predominante. `no_aplica` para trabajos sin estructura (pintura, reparaciones). Mismo nombre que en el backend. |
| `superficie_m2` | float | m² | > 0; vacío si no informada | No | real / sintético | predictor | Superficie intervenida. |
| `superficie_fuente` | cat | — | `explicita`, `inferida_documento`, `no_informada`, `sintetica` | Sí | derivada | flag | `inferida_documento` = calculada desde una partida o dimensión del propio PDF. Debe ser `no_informada` si y solo si `superficie_m2` está vacía. |
| `numero_pisos` | int | pisos | ≥ 1; vacío si no informado | No | real / sintético | predictor | Pisos construidos o intervenidos. No se imputa en el dataset real: la imputación, si se hace, se decide en la preparación y se marca. |
| `pisos_fuente` | cat | — | `explicito`, `inferido`, `no_informado`, `sintetico` | Sí | derivada | flag | Debe ser `no_informado` si y solo si `numero_pisos` está vacío. |
| `estandar_terminaciones` | cat | — | `economico`, `medio`, `alto`, `ni` | Sí | real / sintético | predictor | Mismo dominio que la restricción de `proyectos` y `estimaciones`, más `ni`. |
| `costo_neto_clp` | int | CLP, sin IVA, con gastos generales y utilidad | > 0 | Sí para `utilizable` (I2) | real / sintético | **predictor** | Si el documento incluye IVA, se guarda el subtotal neto. Ver la sección "Costo como predictor". |
| `iva_incluido_doc` | cat | — | `true`, `false`, `ni` | Sí | real | flag | Si el total impreso en el documento incluía IVA. |
| `costo_neto_uf` | float | UF, 2 decimales | > 0; vacío si falta `fecha_documento` o `costo_neto_clp`, o si la fecha es posterior al día de cálculo | No | derivada | **predictor** | `round(costo_neto_clp / UF(fecha_documento), 2)`, con la UF **del mismo día de `fecha_documento`** según la CMF (ver "Fuente de la UF"). La calcula `ml/src/uf.py`; no se edita a mano. Completada en 16 de 17 filas; R07 queda vacía porque no tiene fecha. No se imputa, y por eso R07 queda fuera del modelo de plazo. En el modelo entra como `log(costo_neto_uf)`. |
| `gg_utilidad_pct` | float | % | 0–30 | No | real | meta | Suma de gastos generales y utilidad declarados. |
| `fecha_documento` | date | — | ISO | No (necesaria para UF) | real | meta | Fecha de la cotización. |
| **`plazo_dias`** | int | días corridos | > 0; vacío si no informado | Objetivo | real / sintético | **objetivo** | Plazo de entrega. Conversión: semanas × 7; "N dias" se toma como N días corridos (supuesto declarado en `hallazgos_hu13.md`). |
| `plazo_texto_original` | str | — | literal del documento | No | real | flag | Permite auditar la conversión a días. |
| `plazo_explicito` | bool | — | `true`, `false` | Sí | derivada | flag | Si el plazo aparece escrito en el documento. Debe ser `true` si y solo si `plazo_dias` está informado. |
| `plazo_es_cota` | bool | — | `true`, `false` | Sí | derivada | flag | Si el plazo es "hasta X" (cota superior). Exige `plazo_explicito = true`. Hoy solo R08. |
| `tipo_plazo` | cat | — | `ofertado`, `ejecutado` | Sí | derivada | flag | Hoy todos son `ofertado`. Un sintético no puede ser `ejecutado`. |
| `pagina_plazo` | int | — | ≥ 1 | No | real | id | Página del PDF donde aparece el plazo o la frase "a acordar". |
| `utilizable` | bool | — | `true`, `false` | Sí | derivada | meta | Resultado de los criterios de `criterios_inclusion.md`. El validador lo recalcula. |
| `motivo_exclusion` | cat | — | `E2`, `E3`, `E4`; vacío si es utilizable | Si `utilizable = false` | derivada | meta | Código del criterio que lo excluye. |
| `notas_calidad` | str | — | texto | No | derivada | meta | Erratas, inferencias y supuestos de la transcripción. |

## Fuente de la UF (estado al 2026-10-31)

**Fuente vigente: API de indicadores de la CMF**, endpoint `https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/2025/01?formato=json`, con la API key de la usuaria leída de la variable de entorno `CMF_API_KEY` (nunca se escribe en archivos ni en la caché). Descarga realizada el **2026-10-31** con `python ml/src/uf.py`. No se usan otras fuentes: si una fecha no está en la caché, el script falla en vez de buscarla en otro lado.

Regla de cálculo: UF del **mismo día** de `fecha_documento` (no promedio mensual ni UF del día de cálculo). Las 14 fechas distintas del dataset (2025-11-10 a 2026-09-24) están cubiertas por la caché.

### Caché `ml/data/processed/uf_cmf.csv`

| Columna | Tipo | Descripción |
|---|---|---|
| `fecha` | date ISO | Día al que corresponde el valor. |
| `valor_uf` | float (2 decimales) | Valor de la UF en CLP publicado por la CMF (convertido de `"39.643,59"` a `39643.59`). |
| `fecha_descarga` | date ISO | Día en que se llamó a la API (2026-10-31 en la caché actual). |
| `fuente` | str | Endpoint consultado, **sin** la API key. |

Contenido actual: 647 días, del **2025-02-01 al 2026-11-09**, sin días faltantes en ese rango. El endpoint `posteriores/2025/01` entrega valores *posteriores* a enero de 2025, por lo que la serie parte el 2025-02-01 (no el 2025-01-01). La CMF publica la UF hasta el día 9 del mes siguiente, por eso la serie llega a una fecha futura. Las ejecuciones siguientes de `uf.py` usan la caché sin llamar a la API; para refrescarla se borra el archivo y se vuelve a ejecutar.

### Historial de consultas (2026-10-29, previas a contar con API key)

Regla de la usuaria: usar solo fuentes oficiales (CMF o Banco Central de Chile). Si exigen credenciales, no se usa otra fuente y la usuaria carga los valores o la credencial.

| Fuente | Consulta (2026-10-29) | Resultado |
|---|---|---|
| CMF, API SBIF v3 | `GET https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/2025/11/dias/10?formato=json` (sin datos del proyecto, solo la fecha) | HTTP 422, `CodigoError 92: "API key no ha sido suministrada"`. **Exige API key.** |
| Banco Central, BDE SieteRestWS, serie `F073.UFF.PRE.Z.D` | `GET https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx?function=GetSeries&timeseries=F073.UFF.PRE.Z.D&firstdate=2025-11-10&lastdate=2025-11-10` | HTTP 302 a `ErrorPage.htm` al consultar sin credenciales. Según la documentación del servicio, requiere los parámetros `user` y `pass` de una cuenta registrada en el BDE. **Exige credenciales.** |

**Resultado al 2026-10-29:** `costo_neto_uf` quedó vacía. Se resolvió el 2026-10-31 cuando la usuaria obtuvo la API key de la CMF (ver arriba). Fechas distintas presentes en `fecha_documento`: 2025-11-10, 2025-11-15, 2025-11-16, 2026-02-05, 2026-02-09, 2026-02-13, 2026-03-09, 2026-03-31, 2026-04-27, 2026-04-28, 2026-05-05, 2026-05-19, 2026-09-04 y 2026-09-24.

Alternativa oficial **no usada**: el SII publica tablas anuales de UF en `https://www.sii.cl/valores_y_fechas/uf/` (p. ej. `uf2026.htm`), que son páginas públicas sin credenciales. No se consultó ni se verificó su disponibilidad actual.

## Costo como predictor del plazo

`costo_neto_clp` y `costo_neto_uf` se consideran **predictores candidatos** del plazo, por lo siguiente:

1. **No hay fuga de información.** En BuildCast el costo lo calcula el motor determinista de costos (banco de precios por partidas) **antes** de estimar el plazo. Cuando el modelo de plazo predice, el costo ya está disponible como entrada y no depende del plazo real.
2. **Resume el alcance.** En 9 de los 14 casos utilizables no hay superficie informada. El costo es la única medida de tamaño de la obra presente en todos los casos con plazo.
3. **La definición es compatible con el motor.** El motor calcula `costo_total = costo_directo + gastos_generales + utilidad`, sin IVA (`backend/app/services/motor_costos.py`). `costo_neto_clp` usa la misma definición: neto de IVA, con gastos generales y utilidad.

Advertencias que deben quedar en la model card:
- **Desplazamiento de distribución.** En entrenamiento el costo viene de los precios propios de RAM; en producción viene del banco de precios del motor. Si ambos difieren de forma sistemática, el modelo hereda ese sesgo.
- **Estructura de costos.** Algunos documentos tienen gastos generales y utilidad en 0% (R08, R10), lo que agrega ruido.
- **Actualización monetaria.** Los costos son nominales de nov-2025 a sep-2026. Se recomienda usar `costo_neto_uf` (disponible desde el 2026-10-31 en 16 de 17 filas). En producción el motor entrega CLP, así que el endpoint también tendría que convertir con la UF del día de la estimación.
- **Contrato con el backend.** Usar el costo como entrada cambia el contrato: el endpoint del modelo debe recibirlo (ver `notas_backend.md`).
