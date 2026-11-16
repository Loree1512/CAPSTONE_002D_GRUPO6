# Model card: plazo v1.0-2026-11-01 (regla paramétrica P2, provisional)

| Campo | Valor |
|---|---|
| Versión | `v1.0-2026-11-01` |
| Algoritmo (`versiones_modelo.algoritmo`) | `parametrica` (P2: plazo por costo en UF) |
| Estado | `validado = true` (LOO medido), `provisional = true`, `vigente = true`. Se mantuvo P2 frente a Ridge por robustez (ver "Selección") |
| Artefacto | `ml/models/plazo_v1.0-2026-11-01.joblib` (+ `.json` con la fila de `versiones_modelo`) |
| Entrenado en | 2026-11-01, con `ml/src/entrenar.py` |
| Filas de entrenamiento | 13 reales (12 de evaluación + R08 con 35 días), 0 sintéticos |
| Evaluación | Leave-one-out sobre 12 casos reales |
| Entorno | Python 3.13.15, scikit-learn 1.5.2, pandas 2.2.3, numpy 2.5.4, joblib 1.4.2 (`ml/requirements.txt`) |

## Qué predice

El **plazo ofertado** por RAM, en días corridos, para un trabajo de un `tipo_obra` y un costo neto dados. Todos los plazos de entrenamiento son ofertados (ninguno ejecutado), así que el modelo no estima la duración real de la obra. La interfaz debe decir "plazo estimado según presupuestos" y mostrar "estimación provisional (regla paramétrica)".

## Regla

`log(plazo) = α + β·log(costo_neto_uf) + γ·[clase = edificacion]`, con `plazo = max(1, round(exp(·)))`.

- β por Theil–Sen (mediana de pendientes entre pares de casos), α por mediana de residuos de todos los casos y γ por mediana de residuos de los casos de edificación.
- Parámetros finales, calibrados con 13 casos: **α = −1,6150, β = 0,8902, γ = 0,2686**. Se leen así: con un 10% más de costo, el plazo sube un 8,9%. A igual costo, la edificación lleva un factor e^γ = 1,31 sobre los trabajos puntuales.
- La clase sale de `tipo_obra` con un mapeo determinista (`ml/docs/notas_backend.md`).
- El costo se convierte a UF con la UF CMF del día (`ml/src/uf.py`).

## Datos

- **Origen:** 17 presupuestos reales de RAM (nov-2025 a sep-2026), de los cuales 14 son utilizables.
- **Excluidos:**
  - R07, porque no tiene fecha y por lo tanto no tiene UF. Queda fuera de todos los métodos.
  - R08, porque su plazo es una cota ("hasta 5 semanas"). Entra al entrenamiento con 35 días, pero no a la métrica principal.
- **Evaluación (12 casos):** R02, R03, R04, R05, R06, R09, R10, R11, R13, R14, R16 y R17. Son 10 puntuales y 2 de edificación (R11 y R17).
- **Sintéticos:** no se usan en esta versión (ver "Sintéticos").
- **Variables que el modelo no usa:** pisos, estándar, materialidad, comuna y superficie. No existen en los datos reales, o están en muy pocos casos para usarlas.

## Desempeño (LOO, 12 casos reales, días)

| Método | MAE | RMSE | DE error abs. | Rango error abs. | R² (inf.) |
|---|---|---|---|---|---|
| Mediana (línea base a) | 6,92 | 10,41 | 8,13 | 0,00–28,00 | −0,01 |
| **P2 (línea base b, elegida)** | **5,60** | **7,70** | **5,52** | **0,29–19,76** | **0,45** |
| P2 sin R08 (sensibilidad) | 4,93 | 5,65 | 2,89 | 1,62–12,21 | 0,70 |
| Ridge | 4,37 | 5,33 | 3,19 | 0,20–11,73 | 0,73 |
| Ridge + sintéticos | 4,46 | 5,85 | 3,96 | 0,15–12,15 | 0,68 |
| kNN (k = 3) | 6,16 | 8,01 | 5,35 | 2,00–20,25 | 0,40 |
| kNN + sintéticos | 6,62 | 8,10 | 4,87 | 0,19–14,60 | 0,39 |
| Árbol (prof. 2) | 5,79 | 7,26 | 4,58 | 0,14–14,89 | 0,51 |
| Árbol + sintéticos | 6,72 | 8,14 | 4,79 | 0,83–14,76 | 0,38 |

**Subconjunto con superficie** (R03, R06, R11 y R17; es donde P1 aplica):

| Método | MAE | RMSE |
|---|---|---|
| P1 (días/m²) | 13,81 | 19,08 |
| Mediana | 11,75 | 15,63 |
| P2 | 6,75 | 10,10 |
| Ridge | 4,19 | 4,96 |

**Por clase** (MAE):

| Método | Puntual (n = 10) | Edificación (n = 2, descriptivo) |
|---|---|---|
| Mediana | 4,80 | 17,50 |
| P2 | 4,50 | 11,06 |
| Ridge | 4,37 | 4,36 |

**R08 aparte** (la cota es 35 días; se entrenó con los 12 de evaluación):

| Método | Predicción | ¿Respeta la cota? |
|---|---|---|
| Mediana | 14,0 | sí |
| P2 | 28,3 | sí |
| Ridge | 23,9 | sí |
| kNN | 23,1 | sí |
| Árbol | 29,7 | sí |
| Ridge + sintéticos | 37,9 | no |
| kNN + sintéticos | 51,3 | no |
| P1 | 81,9 | no |

**Estabilidad de P2 entre pliegues:** α ∈ [−2,085; −0,760], β ∈ [0,740; 1,001], γ ∈ [0,146; 0,302].

**Por qué R² no es criterio.** Con 12 casos, un objetivo asimétrico (de 2 a 42 días) y solo dos casos largos, R² depende casi por completo de R11 (42 días). Además, dentro de la clase puntual el R² es negativo para todos los métodos (incluida la mediana, con −0,97), porque la varianza del plazo dentro de esa clase es pequeña frente al error. MAE y RMSE en días se leen directamente y son los que importan a RAM.

## Selección

### Regla corregida (vigente desde el 2026-11-01)

La regla de empate original estaba **mal especificada**: comparaba la diferencia de MAE con la desviación estándar del error absoluto por caso, que mide la dispersión de cada método y no la incertidumbre de la diferencia entre ambos. La usuaria la corrigió así: un candidato supera a la mejor línea base solo si la diferencia de MAE es mayor que el **error estándar de la diferencia pareada**, `SE = DE(|e_P2| − |e_Ridge|) / √n` (DE con ddof = 1, n = 12).

| | Valor |
|---|---|
| Mejor línea base | P2: MAE 5,598 |
| Mejor candidato | Ridge (solo reales): MAE 4,373 |
| Diferencia de MAE (media pareada) | 1,225 días |
| DE de la diferencia pareada (ddof = 1) | 4,086 |
| SE = 4,086 / √12 | **1,180** |
| Diferencia / SE | 1,038 |

Con la regla corregida, **Ridge supera el umbral por 0,045 días** (1,225 frente a 1,180).

### Robustez y decisión

El análisis de robustez (`ml/src/analisis_empate.py`) muestra que los dos métodos son **estadísticamente indistinguibles**:
- Cada uno gana en 6 de los 12 casos, sin empates.
- Wilcoxon pareado de dos colas, exacto (no hay diferencias nulas ni empates en |d|): W = 37, **p = 0,910**. La aproximación normal da p = 0,875 y la t pareada, t = 1,038 con 11 gl, p = 0,322.
- La ventaja está concentrada en R11: aporta 11,70 de los 14,70 días de diferencia total. Sin R11, la diferencia media es de unos 0,27 días.
- La ventaja **se invierte sin R08** en el entrenamiento: P2 obtiene 4,93 y Ridge 5,27.

**Decisión de la usuaria (2026-11-01): se mantiene P2** como versión vigente y provisional. La ventaja de Ridge depende de incluir R08, cuyo plazo es una cota imprecisa ("hasta 5 semanas como máximo"). **Ridge queda como alternativa a reevaluar con más datos**, en particular cuando RAM confirme el plazo de R08 (`consultas_ram.md`, consulta 21) o existan plazos ejecutados (HU-22). Por esto la versión queda con `algoritmo = parametrica` y `provisional = true`.

### Historial: regla original (superada)

> **Superada el 2026-11-01; no es válida como justificación.** La regla original comparaba la mejora con la mayor DE del error absoluto entre el candidato y la línea base. Con ella, 1,22 < 5,52 daba "empate técnico". Los metadatos originales del artefacto registraban ese cálculo (`umbral_sd = 5,519`, `veredicto = empate_tecnico`), pero ya se regeneraron (ver abajo).

### Dónde queda registrado

`seleccion` en el `.joblib` y `detalle.seleccion` en el `.json` tienen dos bloques separados:
- **`veredicto_regla`**, que calcula `evaluacion.seleccionar`. Guarda la regla corregida con sus números: `dif_mae = 1,225`, `de_dif_ddof1 = 4,086`, `se_dif = 1,18`, `cociente_dif_se = 1,038`, 6/6/0 casos, Wilcoxon exacto W = 37 y p = 0,9097, `margen_sobre_se = 0,045`, y `veredicto = candidato_supera`.
- **`decision`**: el método vigente, `P2`, con su motivo y Ridge como alternativa. Viene de `METODO_VIGENTE` y `DECISION` en `ml/src/entrenar.py`; `seleccionar` ya no decide el método.

**Metadatos regenerados el 2026-11-01, el mismo día del entrenamiento, sin cambios en el modelo.** Los parámetros α, β y γ, los 12 residuos y q10/q90 son idénticos bit a bit. Las predicciones de `predecir_plazo` también son idénticas sobre una batería de 21 casos: los 13 de entrenamiento y 8 casos borde. Lo mismo ocurre con todos los campos del JSON salvo `detalle.seleccion`, incluido `entrenado_en = 2026-11-01`. Solo cambió `seleccion` / `detalle.seleccion`.

## Intervalo

- **Método:** percentiles 10 y 90 de los 12 residuos LOO de P2 en escala log (`log real − log predicho`). Se aplican de forma multiplicativa: `[plazo × e^q10, plazo × e^q90]`. Luego se redondea el mínimo hacia abajo y el máximo hacia arriba, y se fuerza `1 ≤ min ≤ plazo ≤ max`.
- **Definición del percentil:** Weibull, `h = (n + 1)·p`. Con 12 residuos, P10 interpola entre el 1.º y el 2.º valor ordenado y P90 entre el 11.º y el 12.º. Para un caso nuevo, la probabilidad esperada de quedar dentro es 0,8. P5/P95 quedarían fuera del rango de los datos (serían extrapolación) y por eso no se usan.
- **Valores:** q10 = −0,741 y q90 = 1,639. Los factores resultantes son **×0,48 y ×5,15**.
- **Cobertura empírica:** 10 de 12 (0,833) dentro de la muestra, y también 10 de 12 (0,833) en LOO anidado, con los percentiles recalculados sin el caso evaluado.
- **Advertencia:** el factor superior es muy amplio por un solo caso, R05 (muro divisor de 14,56 UF y 14 días, para el que P2 predice 1,8 días; residuo log de 2,04). Sin R05 el 12.º residuo sería 0,696. No se excluyó ni se recortó a posteriori. En la práctica, un plazo central de exactamente 12 días se muestra como 5–62 días. (R03, con una predicción central de 11,4 días que se redondea a 12, se muestra como 5–61.)
- **Respaldo:** la mediana tiene su propio intervalo, con los percentiles de sus residuos LOO: 14 días [×0,19, ×2,44], es decir, 2–35 días.

## Sensibilidad (para la Sprint Review)

Números de `ml/src/analisis_empate.py`, con el mismo LOO: 12 casos de evaluación y R08 en el entrenamiento, salvo donde se indique.

**Diferencia pareada por caso** (días; d > 0 significa que Ridge acierta mejor):

| id | real | pred P2 | pred Ridge | \|e\| P2 | \|e\| Ridge | d = \|e_P2\| − \|e_Ridge\| |
|---|---|---|---|---|---|---|
| R02 | 5 | 6,208 | 7,616 | 1,208 | 2,616 | −1,408 |
| R03 | 14 | 11,443 | 10,542 | 2,557 | 3,458 | −0,901 |
| R04 | 5 | 7,969 | 8,504 | 2,969 | 3,504 | −0,534 |
| R05 | 14 | 1,816 | 2,273 | 12,184 | 11,727 | 0,457 |
| R06 | 2 | 4,323 | 6,592 | 2,323 | 4,592 | −2,269 |
| R09 | 5 | 9,797 | 10,107 | 4,797 | 5,107 | −0,310 |
| R10 | 14 | 6,978 | 8,000 | 7,022 | 6,000 | 1,021 |
| R11 | 42 | 61,756 | 33,939 | 19,756 | 8,061 | 11,696 |
| R13 | 14 | 21,211 | 14,204 | 7,211 | 0,204 | 7,007 |
| R14 | 5 | 5,289 | 7,101 | 0,289 | 2,101 | −1,811 |
| R16 | 14 | 9,514 | 9,561 | 4,486 | 4,439 | 0,048 |
| R17 | 21 | 18,631 | 20,331 | 2,369 | 0,669 | 1,700 |
| **Media** | | | | 5,598 | 4,373 | **1,225** (DE 4,086; SE 1,180) |

**P2 frente a Ridge, con y sin R08 en el entrenamiento** (evaluación en los mismos 12 casos):

| Método | MAE | RMSE | DE \|e\| | Rango \|e\| |
|---|---|---|---|---|
| P2 con R08 (versión entregada) | 5,598 | 7,698 | 5,519 | 0,289–19,756 |
| P2 sin R08 | 4,926 | 5,652 | 2,895 | 1,624–12,206 |
| Ridge con R08 | 4,373 | 5,333 | 3,189 | 0,204–11,727 |
| Ridge sin R08 | 5,268 | 6,704 | 4,330 | 0,175–15,787 |

**Intervalos de ambos, con y sin R05 en los residuos.** Percentiles 10/90 Weibull de los residuos log LOO. Excluir R05 cambia solo el cálculo de los residuos; los modelos y las predicciones no cambian. Las coberturas se calculan sobre los 12 casos.

| Método | Residuos | q10 | q90 | Factores | Plazo de 12 días | Cobertura (12) | ¿R05 dentro? |
|---|---|---|---|---|---|---|---|
| P2 | con R05 (n = 12, entregado) | −0,741 | 1,639 | ×0,477 – ×5,147 | 5–62 | 0,833 (anidada 0,833) | no |
| P2 | sin R05 (n = 11) | −0,751 | 0,634 | ×0,472 – ×1,886 | 5–23 | 0,750 | no |
| Ridge | con R05 (n = 12) | −1,046 | 1,440 | ×0,351 – ×4,222 | 4–51 | 0,833 (anidada 0,833) | no |
| Ridge | sin R05 (n = 11) | −1,095 | 0,524 | ×0,335 – ×1,689 | 4–21 | 0,750 | no |

El residuo log de R05 es 2,042 en P2 y 1,818 en Ridge. Excluirlo achica el intervalo a menos de la mitad, pero la cobertura sobre los 12 casos baja de 0,833 a 0,750. Se mantiene el intervalo con R05 hasta que RAM confirme ese plazo (`consultas_ram.md`, consulta 20).

## Sintéticos

Los genera `ml/src/generar_sinteticos.py` con semilla 20261101 más el número de pliegue, y siempre dentro de cada pliegue:

- 24 filas por pliegue, repartidas en la proporción de clases de los reales.
- El log UF se muestrea uniforme dentro del rango real de cada clase.
- El plazo sale de P2 ajustada con los reales del pliegue, más ruido remuestreado de sus residuos.

**No bajaron el MAE real de ningún candidato** (Ridge pasó de 4,37 a 4,46, kNN de 6,16 a 6,62 y el árbol de 5,79 a 6,72), así que no se adoptan. Como se construyen con P2, no aportan información nueva: solo podrían estabilizar el ajuste.

## Limitaciones

1. Hay solo 12 casos de evaluación y 2 de edificación. Las cifras por clase son descriptivas.
2. El objetivo es plazo ofertado, que suele ser optimista y viene redondeado (5 días, 2, 3 o 6 semanas).
3. Distribución del costo: en el entrenamiento viene de los precios propios de RAM; en producción, del banco de precios del motor.
4. R08 entra al entrenamiento con su cota, y eso empuja γ hacia arriba. P2 sin R08 obtiene un MAE de 4,93 frente a 5,60 con R08. Se mantiene R08 por decisión de la usuaria. R08 también decide la comparación con Ridge (ver "Sensibilidad").
5. Pisos, estándar y materialidad no influyen en el plazo de esta versión, aunque el formulario los pida.
6. El intervalo es amplio y está dominado por un caso atípico (R05).

## Integración en BuildCast (2026-11-03)

Esta versión se integró al backend **tal cual, como versión provisional**, sin reentrenar ni usar datos sintéticos. Se calibró con la totalidad del dataset histórico disponible.

- **Parámetros:**
  - `ml/src/exportar_backend.py` los copia, sin redondear, a `backend/app/modelos/plazo_v1.0-2026-11-01.json`.
  - El backend los ejecuta con la biblioteca estándar (`backend/app/services/estimador_plazo.py`).
  - La paridad con `predict.py` se prueba en 650 casos (`backend/tests/datos/paridad_plazo_v1.0-2026-11-01.json`).
- **Dominio conocido:**
  - Sale del dataset de entrenamiento: 14,56–438,95 UF, plazos de 2 a 42 días y los tipos de obra presentes.
  - Fuera de ese rango, el backend calcula el valor como **referencial** y lo marca como extrapolación (`plazo_estado`). No lo presenta como validado.
- **Tipos de obra de BuildCast:**
  - *Ampliación* → `ampliacion` (con casos reales).
  - *Vivienda unifamiliar* y *Edificación habitacional* → `obra_nueva`, que **no tiene casos reales**: siempre quedan como `tipo_obra_no_representado`.
- **Estimaciones incompletas:** el plazo se calcula sobre el costo parcial y se marca `costo_incompleto`. Como el plazo crece con el costo, ese valor queda por debajo del que tendría la obra completa.
- **UF:**
  - Se lee de la tabla `valores_uf` de Supabase, con el día de la estimación en Chile.
  - Sin UF para ese día, se usa el respaldo de la mediana (14 días, 2–35), marcado `respaldo`.
  - La CMF no se consulta en cada estimación.
- **Ciclo de versiones nuevas:** ver `ml/docs/publicar_version.md`.

## Reproducción

```
python -m venv ml/.venv
ml/.venv/Scripts/python -m pip install -r ml/requirements.txt
ml/.venv/Scripts/python ml/src/validar_dataset.py
ml/.venv/Scripts/python ml/src/evaluacion.py
ml/.venv/Scripts/python ml/src/entrenar.py      # reescribe el artefacto con la fecha del día
ml/.venv/Scripts/python -m pytest ml/tests -q
ml/.venv/Scripts/python ml/src/analisis_empate.py   # sensibilidad P2 frente a Ridge; no escribe archivos
```

`entrenar.py` nombra la versión con la fecha del día. Volver a ejecutarlo en otra fecha genera una versión nueva y no sobrescribe esta. Para reproducir exactamente esta versión: `entrenar.py --entrenado-en 2026-11-01 --salida <directorio>`.

## Párrafo para el informe final

Para el modelo de plazo se compararon dos líneas base y tres candidatos simples mediante validación leave-one-out sobre doce presupuestos reales de RAM. Del universo de catorce se excluyeron el caso sin fecha, que no admite conversión a UF, y el caso cuyo plazo es una cota superior, que se usó en el entrenamiento y se informó por separado. La regla paramétrica P2, que relaciona el logaritmo del plazo con el logaritmo del costo neto en UF y con un factor por edificación, obtuvo un error absoluto medio de 5,60 días, frente a 6,92 de la mediana y 4,37 de una regresión Ridge con las mismas variables. La regla de selección se corrigió durante el análisis: en su versión inicial comparaba la mejora con la dispersión del error de cada caso, lo que no mide la incertidumbre de la diferencia entre dos métodos. Con la regla corregida, que exige que la diferencia de MAE supere el error estándar de la diferencia pareada (1,18 días), Ridge supera el umbral por solo 0,045 días. El análisis de robustez muestra, sin embargo, que ambos métodos son estadísticamente indistinguibles: cada uno acierta mejor en seis de los doce casos, la prueba de Wilcoxon pareada da p = 0,91, la ventaja de Ridge proviene casi por completo de un solo caso y se invierte al quitar del entrenamiento el presupuesto con plazo como cota (P2 4,93 días frente a Ridge 5,27). Por eso se mantuvo P2 como versión provisional v1.0-2026-11-01 y Ridge quedó como alternativa a reevaluar cuando haya más datos o se confirme ese plazo. El intervalo se construye con los percentiles 10 y 90 de los residuos de validación en escala logarítmica, cubrió diez de los doce casos y es amplio porque un trabajo de bajo costo y plazo largo domina el extremo superior; ese caso y el de la cota quedaron como consultas a RAM. El coeficiente de determinación se informa solo como referencia, y todas las cifras corresponden a plazos ofertados, no ejecutados.
