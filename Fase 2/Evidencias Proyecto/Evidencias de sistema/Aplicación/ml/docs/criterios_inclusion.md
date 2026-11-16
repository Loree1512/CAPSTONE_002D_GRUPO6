# Criterios de inclusión y exclusión, y línea base paramétrica (HU-13)

Decisión de alcance aprobada por la usuaria (registrar en la Sprint Review): **el universo son todos los presupuestos reales con plazo explícito, de edificación y obras menores juntos.** `clase_obra` es una variable del modelo, no un filtro.

Los criterios se aplican fila a fila. `ml/src/validar_dataset.py` los recalcula y falla si no coinciden con las columnas `utilizable` / `motivo_exclusion` del CSV.

## Criterios de inclusión (todos deben cumplirse)

| Código | Criterio | Cómo se verifica |
|---|---|---|
| I1 | El plazo aparece escrito y es numérico (días o semanas). | `plazo_explicito = true` y `plazo_dias` > 0. |
| I2 | El costo neto se puede leer en el documento. | `costo_neto_clp` > 0. |

Lo que **no** es requisito de inclusión, y por qué:
- **Clase de obra:** se modela como variable (decisión de alcance).
- **Superficie:** solo 5 de los 14 casos con plazo la tienen. Se marca con `superficie_fuente`.
- **Fecha:** solo es necesaria para convertir a UF. R07 no la tiene y se queda en el dataset.
- **Pisos y estándar:** no aparecen en ningún caso real (ver `hallazgos_hu13.md`).

## Criterios de exclusión (se evalúan en orden; el primero que aplica define el motivo)

| Código | Criterio | Cómo se verifica | Efecto |
|---|---|---|---|
| E2 | Sin plazo, o con plazo "a acordar con el cliente". | `plazo_explicito = false` o `plazo_dias` vacío. | La fila queda en el dataset con `utilizable = false`. |
| E3 | Revisión duplicada de un documento ya incluido. | `archivo_origen` repetido en filas reales. Si un mismo proyecto llegara en dos PDFs distintos, se marca a mano y se conserva la última revisión. | Se excluye. |
| E4 | No se puede leer el costo neto. | `costo_neto_clp` vacío. | Se excluye. |

Los códigos E1 (trabajo puntual) y E5 (plazo como cota) del diagnóstico anterior quedan derogados; por eso la numeración no es correlativa:
- **Clase de obra:** ya no excluye.
- **Plazo como cota (`plazo_es_cota = true`, hoy solo R08 – local comercial):** el caso **entra** al dataset utilizable y **se reporta aparte**. En la evaluación se calculan las métricas con y sin R08, y para R08 se informa además si la predicción respeta la cota (predicción ≤ 35 días).

## Resultado actual

| | Casos |
|---|---|
| Filas totales | 17 |
| Utilizables | 14 (3 de edificación: R08, R11, R17; 11 puntuales) |
| Con cota | R08 |
| E2 | R01 (ampliación Villa Alemana), R12 (baño Reñaca), R15 (mantención Mantagua) |
| E3 / E4 | 0 |

Todos los plazos son **ofertados**. El objetivo del modelo es, por ahora, "plazo que RAM oferta", no "plazo que la obra dura".

## Decisiones del 2026-11-01 (cambian lo acordado el 2026-10-29; registrar en la Sprint Review)

1. **Conjunto de evaluación: 12 casos.** Son los 14 utilizables menos R08 (plazo como cota) y menos R07 (sin fecha, por lo tanto sin UF). Reemplaza la evaluación "global con 14 casos, y con y sin R08" del protocolo original.
2. **R07** queda fuera del entrenamiento y de la evaluación de todos los métodos, también de la mediana, para que todos se comparen sobre los mismos casos. Así se resuelve la "decisión explícita" que pedía P2 al usar UF: se excluye, no se imputa.
3. **R08** entra al entrenamiento de cada pliegue con 35 días, pero no al MAE/RMSE principal. Se predice aparte y se informa si respeta la cota.
4. **P1 pasa a evaluarse** (antes estaba "solo documentada, no se calibra ni se evalúa"). Se evalúa en su subconjunto de 4 casos de evaluación con superficie (R03, R06, R11, R17), junto con el MAE de los demás métodos en esos mismos 4. La mejor línea base se sigue eligiendo entre las que cubren los 12 casos: mediana y P2. P1 no es candidata a vigente.
5. **R13 (cobertizo) se recodifica** de `tipo_obra = obra_nueva` a `obra_menor_varia` y mantiene `clase_obra = puntual`. Desde ahora `obra_nueva` es siempre edificación y el mapeo `tipo_obra → clase_obra` es determinista (ver `diccionario_variables.md`). El validador ya no acepta `puntual + obra_nueva`.
6. **Regla de selección con empate técnico (corregida).** Un candidato gana solo si su MAE LOO es menor que el de la mejor línea base y la diferencia supera el **error estándar de la diferencia pareada**, `SE = DE(|e_base| − |e_candidato|) / √n` (ddof = 1). Si la diferencia es menor, hay empate técnico y se elige P2. Si queda P2: `algoritmo = parametrica`, `provisional = true`.
   - *Versión original, superada por estar mal especificada:* comparaba la diferencia con la desviación estándar del error absoluto por caso (la mayor entre candidato y línea base). Esa DE mide la dispersión de cada método, no la incertidumbre de la diferencia.
   - Al aplicar la regla corregida se revisa además la robustez: casos ganados, Wilcoxon pareado y sensibilidad a R08. Con un margen mínimo, la usuaria puede mantener la línea base (decisión registrada abajo).
7. **Protocolo de sintéticos.** Pueden entrar al entrenamiento de los candidatos (nunca al de las líneas base ni a la evaluación). Se generan dentro de cada pliegue con los reales de entrenamiento del pliegue (`ml/src/generar_sinteticos.py`). Esto reemplaza al punto 3 del protocolo común para los candidatos; las líneas base siguen sin sintéticos. Se adoptan solo si bajan el MAE real.
8. **Intervalo.** Se mantienen los percentiles 10/90 de los residuos log LOO, con la definición de percentil de Weibull, `h = (n + 1)·p`.
9. **Versión final.** Se ajusta con 13 casos (los 12 de evaluación más R08), no con 14.

**Resultado (2026-11-01):** Ridge tuvo un MAE de 4,37 días y P2 de 5,60.
- Con la regla corregida, la diferencia de 1,225 días supera el SE de 1,180 por 0,045 días.
- La robustez indica que son indistinguibles: 6 casos ganados cada uno, Wilcoxon pareado exacto p = 0,91, ventaja concentrada en R11, y se invierte sin R08 (P2 4,93 frente a Ridge 5,27).
- **Decisión de la usuaria:** se mantiene P2 como `v1.0-2026-11-01`, `parametrica`, provisional. Ridge queda como alternativa a reevaluar con más datos.
- *Historial superado:* con la regla original se había declarado empate porque "1,22 < 5,52"; esa justificación ya no es válida.

Detalle en `model_card_v1.0-2026-11-01.md`.

## Línea base paramétrica (P2 principal): método de calibración

> **Actualización 2026-11-01:** P2 y P1 ya están calibradas y evaluadas con LOO (`ml/src/lineas_base.py`, `ml/src/evaluacion.py`). Resultados en `model_card_v1.0-2026-11-01.md`. El texto siguiente conserva el método aprobado el 2026-10-29; los cambios se registran en "Decisiones del 2026-11-01".

> **Decisión de la usuaria (2026-10-29), para presentar en la Sprint Review:** la regla principal es **P2 (plazo por costo, calibrada en los 14 casos)**. P2 es a la vez la línea base (b) y la contingencia. P1 (días por m²) queda **solo documentada** y no se calibra ni se evalúa. Esto modifica la forma de la regla escrita en la especificación ("días por m² ajustados por pisos y estándar"), por lo que se registra como decisión de alcance.

La regla paramétrica P2 cumple dos papeles:
1. **Línea base (b)** contra la que compite cualquier modelo, junto con la línea base (a), que es la mediana de `plazo_dias` sobre los reales del pliegue de entrenamiento.
2. **Contingencia.** Si ningún modelo mejora el MAE de la mejor línea base, o la validación es inestable, se entrega P2 con `algoritmo = parametrica` y `validado` según lo que efectivamente se haya medido, marcada como provisional en la interfaz.

### Por qué P2 y no P1

La regla de la especificación es "días por m² ajustados por pisos y estándar". Sobre los 14 casos utilizables:
- Superficie: solo 5 la tienen (R03, R06, R08, R11, R17).
- Pisos y estándar: no hay ningún dato real.

P1 solo se podría calibrar con 5 casos y sus factores de pisos y estándar quedarían en valores neutros sin respaldo. En cambio, `costo_neto_clp` está en los 14 casos y, en producción, el motor de costos lo calcula antes que el plazo, sin fuga de información (ver `diccionario_variables.md`).

**P2: plazo por costo (regla principal).**
`log(plazo) = α + β·log(costo_neto) + γ·[clase_obra = edificacion]`, de modo que `plazo = max(1, e^α · costo_neto^β · e^γ)`.
- `α` y `β` se estiman con un ajuste robusto en escala log-log: estimador de **Theil–Sen** (mediana de pendientes por pares) para `β` y mediana de residuos para `α`.
- `γ` es la mediana de los residuos de los casos de edificación. Con n = 3 de edificación (n = 2 en los pliegues que dejan fuera uno de ellos), γ es frágil y se reporta su variación entre pliegues.
- Son tres parámetros con lectura directa: β es la elasticidad del plazo frente al costo y e^γ el factor por edificación.
- `costo_neto` en UF (`costo_neto_uf`, cargada el 2026-10-31). R07 no tiene fecha y se excluye (decisión del 2026-11-01).
- α es la mediana de `log(plazo) − β·log(costo_neto_uf)` sobre todos los casos de entrenamiento. γ es la mediana de `log(plazo) − (α + β·log(costo_neto_uf))` sobre los casos de edificación.
- R08 entra en la calibración con su cota (35 días). Como análisis de sensibilidad se reporta también P2 calibrada sin R08.
- Comportamiento sin costo: si el motor no pudo calcular el costo, P2 no aplica y se usa la línea base (a), la mediana, marcada como tal.

**P1: días por m² (evaluada desde el 2026-11-01 en su subconjunto; no es candidata a vigente).**
`plazo = max(1, r_clase × superficie_m2 × f_pisos × f_estandar)`, con `r_clase` igual a la mediana de `plazo_dias / superficie_m2` por clase en el entrenamiento del pliegue y `f_pisos = f_estandar = 1,0`. Si una clase no tiene casos con superficie en el pliegue, se usa la mediana de todas las clases. En LOO sobre R03, R06, R11 y R17 obtuvo un MAE de 13,81 días; en esos mismos 4 casos, la mediana tuvo 11,75 y P2 6,75. Se retomaría si RAM entrega superficie, pisos y estándar para suficientes casos.

### Protocolo común (para que la comparación sea justa)

1. **Calibración dentro de cada pliegue.** Se usa leave-one-out sobre los reales utilizables: en cada pliegue, la regla se recalibra sin el caso que se evalúa. Nunca se calibra con todos los casos y luego se mide sobre ellos mismos.
2. **Métricas.** MAE y RMSE en días, con su dispersión entre pliegues. Se reportan:
   - global (14 casos) — *reemplazado el 2026-11-01 por 12 casos, con R08 aparte (ver Decisiones del 2026-11-01, punto 1)*;
   - sin R08;
   - por `clase_obra` (la de edificación tiene n = 3 y se presenta solo como descriptiva).

   R² se informa pero **no es criterio**: con n = 14 y un objetivo muy asimétrico (2 a 42 días) es inestable y está dominado por los casos extremos.
3. **Sintéticos.** No participan en la calibración de la regla ni en ninguna evaluación. *Desde el 2026-11-01 pueden entrar al entrenamiento de los candidatos (punto 7 de las Decisiones del 2026-11-01).*
4. **Intervalo de la regla.** Percentiles 10 y 90 de los residuos leave-one-out de P2, en escala log. El método queda declarado en la model card.
5. **Versión final.** Si la regla queda vigente, sus parámetros finales se calibran con los 14 casos (*13 desde el 2026-11-01: sin R07*) y se registran en `versiones_modelo` con nombre `vX.Y-AAAA-MM-DD` y `algoritmo = parametrica`. El desempeño reportado es el de leave-one-out, no el del ajuste final.
