# Notas para backend (Ángel): contrato con el modelo de plazo

Propuestas de ML (HU-13 a HU-17). **No se modificó nada fuera de `ml/`.** Cada punto requiere decisión y cambio del responsable de backend o base de datos. Las referencias son al estado del repo al 2026-10-29.

> **Actualización 2026-11-03.** Los puntos 1, 2, 5 y 7 quedaron resueltos en la migración `009_plazo_estimaciones.sql`:
> - tablas `versiones_modelo` y `valores_uf`;
> - plazo, versión y UF en `estimaciones`;
> - servicio `backend/app/services/estimador_plazo.py`.
>
> El backend no importa `predict.py` ni `uf.py`: usa el JSON exportado por `ml/src/exportar_backend.py` y la UF de Supabase. Se mantienen dos decisiones distintas a lo propuesto aquí:
> - **`tipo_obra` sigue con los valores de BuildCast.** La traducción al vocabulario del modelo viaja con cada versión (`traduccion_tipo_obra`) y se guarda en `estimaciones.tipo_obra_modelo`.
> - **`version_modelo` es la FK** a `versiones_modelo.version`, en lugar de `version_modelo_id`.
>
> Detalle en `ml/docs/publicar_version.md`. El resto de este documento queda como registro de la propuesta original.

## 1. Tablas que faltan en Supabase

`supabase/migrations/` no define `presupuestos_historicos` ni `versiones_modelo`.

**`presupuestos_historicos`**: se propone alinearla con `ml/docs/diccionario_variables.md`. Columnas mínimas:
`id_caso` (UK), `archivo_origen`, `revision`, `origen_dato` (check `real`/`sintetico`), `clase_obra`, `tipo_obra`, `comuna`, `materialidad`, `superficie_m2` (nullable), `numero_pisos` (nullable), `estandar_terminaciones` (check `economico`/`medio`/`alto`, nullable), `costo_neto_clp`, `costo_neto_uf` (nullable), `fecha_documento` (nullable), `plazo_dias` (nullable), `plazo_explicito`, `plazo_es_cota`, `tipo_plazo` (check `ofertado`/`ejecutado`), `utilizable`, `motivo_exclusion`.
- Respecto de la definición original: `costo_total` pasa a `costo_neto_clp`, que no incluye IVA y sí incluye gastos generales y utilidad. `fecha_precios` pasa a `fecha_documento`.
- No debe guardar nombres ni teléfonos de clientes.

**`versiones_modelo`**: `version` (UK, formato `vX.Y-AAAA-MM-DD`), `algoritmo` (incluye el valor `parametrica`), `filas_entrenamiento`, `mae_dias`, `rmse_dias`, `r2` (todas nullable), `validado` (bool, default `false`), `ruta_artefacto`, `vigente` (como máximo una fila con `vigente = true`), `entrenado_en`.
- Se sugiere agregar `provisional` (bool), para que la interfaz muestre "regla provisional", y `filas_reales` / `filas_sinteticas`.

## 2. Columnas que faltan en `estimaciones`

Hoy `estimaciones` no tiene plazo, y `resumen_proyecto.py:112` devuelve `plazo_dias=None`. Se propone agregar:
- `plazo_dias` (int, nullable)
- `intervalo_min_dias` y `intervalo_max_dias` (int, nullable; check `min ≤ plazo ≤ max`)
- `version_modelo_id` (FK a `versiones_modelo`, nullable hasta que exista una versión). Corresponde a HU-17.

## 3. Nombres de columnas

El backend y la base usan `materialidad` y `numero_pisos`; parte de la documentación del proyecto usa `material` y `pisos`. ML adopta **`materialidad` y `numero_pisos`** (los del esquema). Se propone corregir la documentación en vez del esquema.

`tipo_obra` y `materialidad` hoy aceptan texto libre (`check (btrim(...) <> '')`). El modelo necesita vocabularios cerrados (ver diccionario). Se propone:
- restringir ambos con `check ... in (...)` o una tabla de dominio; o
- como mínimo, que el frontend use listas cerradas con esos mismos valores.

## 4. `*.joblib` ignorado en la raíz

El `.gitignore` de la raíz ignora `*.joblib` y `*.pkl`. Si FastAPI carga el artefacto desde `ml/models/` al iniciar, hay que decidir entre:
- (a) agregar en la raíz la excepción `!ml/models/*.joblib` (cambio de raíz: lo decide Loreto); o
- (b) no versionar el artefacto y publicarlo por otra vía (bucket de Supabase Storage o release).

ML recomienda (a), por reproducibilidad (RNF-08), siempre que los artefactos pesen poco.

**Actualización 2026-11-01:** se resolvió sin tocar la raíz. `ml/.gitignore` incluye `!models/*.joblib`, y `git check-ignore ml/models/plazo_v1.0-2026-11-01.joblib` sale con código 1 (no ignorado). El artefacto pesa 1.559 bytes. `ml/.venv/` también quedó ignorado en `ml/.gitignore`.

## 5. El endpoint de plazo necesita el costo neto (nuevo)

Por decisión de HU-13, `costo_neto_clp` (y `costo_neto_uf` cuando exista) es **predictor candidato** del plazo. El endpoint o servicio que invoque al modelo deberá recibir, además de `comuna`, `tipo_obra`, `materialidad`, `superficie_m2`, `numero_pisos` y `estandar_terminaciones`:

- `costo_neto_clp`: el `costo_total` calculado por el motor de costos (`costo_directo + gastos_generales + utilidad`, sin IVA, `backend/app/services/motor_costos.py:335`) para la misma estimación.
- Opcional: `fecha_precios` de la versión de precios usada, para convertir a UF.

Implicaciones:
- **Orden de cálculo:** primero el motor de costos, después el plazo. No hay fuga de información, porque el costo existe antes de predecir.
- Si el costo no se pudo calcular (partidas sin precio o sin cantidad), el servicio debe pasar `null`. ML definirá el comportamiento de respaldo, que será la regla paramétrica sin costo o "plazo no disponible".
- Se sugiere guardar en `estimaciones` el costo efectivamente usado como entrada del modelo. Ya existe `costo_total`; basta documentar que es el mismo valor.
- **Conversión a UF (2026-10-31).** Si el modelo usa `costo_neto_uf`, el backend debe convertir el `costo_total` del motor (CLP) a UF con la **UF del día de la estimación**: `costo_neto_uf = round(costo_total / UF(día de la estimación), 2)`. Debe usar la misma fuente que el entrenamiento, la API de la CMF (`https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/2025/01?formato=json`), con la clave leída de la variable de entorno `CMF_API_KEY`. La clave no debe quedar en el código, los logs, las respuestas de error ni la base de datos. Referencia de implementación: `ml/src/uf.py` (descarga, parseo de `"39.643,59"` y caché). Se sugiere guardar en `estimaciones` el valor de UF usado, para que la estimación se pueda reproducir. Si la CMF no responde, el servicio no debe recurrir a otra fuente: pasa `null` como costo en UF y se aplica el mismo respaldo que cuando falta el costo.

## 6. Interfaz (para coordinar con frontend)

- Mientras `validado = false`: mostrar "métricas pendientes" (HU-16). Esto incluye cada estimación que devuelva `metodo = "mediana_respaldo"`, aunque la versión esté validada (ver punto 7).
- Si `algoritmo = parametrica` y `provisional = true`: mostrar "estimación provisional (regla paramétrica)".
- Todos los plazos de entrenamiento son **ofertados**. El texto de la interfaz debería decir "plazo estimado según presupuestos", no "duración real".

## 7. Contrato de `predecir_plazo` (2026-11-01)

Versión entregada: **`v1.0-2026-11-01`**, regla paramétrica P2, provisional. Se mantuvo frente a Ridge porque son estadísticamente indistinguibles y la ventaja de Ridge depende de R08; ver `ml/docs/model_card_v1.0-2026-11-01.md`, "Selección". El campo `detalle.seleccion` del JSON tiene dos bloques: `veredicto_regla`, con la regla de empate corregida y sus números (veredicto `candidato_supera`), y `decision`, con el método vigente `P2` y su motivo. Para saber qué método está vigente hay que leer `decision.metodo`, no `veredicto_regla.veredicto`. Los metadatos se regeneraron el 2026-11-01 sin cambios en el modelo: mismos parámetros, residuos y predicciones. Artefacto: `ml/models/plazo_v1.0-2026-11-01.joblib`. Es un diccionario de Python con parámetros y números, sin clases propias de ML, así que solo requiere `joblib` y `numpy` para cargarse.

```python
# ml/src/predict.py  (importar con ml/src en sys.path: también importa uf.py)
predecir_plazo(tipo_obra: str, costo_neto_clp: int | float | None, fecha: date | str | None) -> dict
```

| Entrada | Qué pasar |
|---|---|
| `tipo_obra` | Valor del vocabulario cerrado (tabla de abajo). Si no está, lanza `ValueError` y el endpoint debe responder 422. |
| `costo_neto_clp` | El `costo_total` del motor (CLP, sin IVA, con GG y utilidad). Si no se pudo calcular, `None`. |
| `fecha` | Día de la estimación (`date` o `'AAAA-MM-DD'`). Se usa para la UF CMF del día. |

| Salida | Tipo | Notas |
|---|---|---|
| `plazo_dias` | int | ≥ 1 |
| `intervalo_min_dias` | int | `1 ≤ min ≤ plazo` |
| `intervalo_max_dias` | int | `max ≥ plazo` |
| `version_modelo` | str | p. ej. `v1.0-2026-11-01`. El backend lo resuelve a `versiones_modelo.id` y lo guarda en `estimaciones.version_modelo_id` (HU-17). |
| `metodo` | str | `P2`, o `mediana_respaldo` si no hubo costo o UF. |
| `validado` | bool | El de la versión, salvo con `mediana_respaldo`, que es **siempre `false`**. |
| `provisional` | bool | `true` en esta versión (y siempre con `mediana_respaldo`). Campo agregado al contrato del plan para que la interfaz muestre "estimación provisional". |

Comportamiento:
- **Respaldo (`mediana_respaldo`).** Se activa si el costo es `None`, no numérico o ≤ 0, o si no hay UF para la fecha: fecha `None` o mal formada, fecha anterior al 2025-02-01 o posterior a la serie, o la CMF no responde. Devuelve 14 días, con intervalo 2–35.
- **Carga del artefacto.** Se hace una sola vez por proceso (`functools.lru_cache`). La ruta se puede cambiar con la variable de entorno `BUILDCAST_MODELO_PLAZO`.
- **UF.** Usa `uf.uf_del_dia` y la caché `ml/data/processed/uf_cmf.csv`. Si la caché no existe, la descarga desde la CMF con `CMF_API_KEY` (ver la nota de UF del punto 5).
- **Salida por consola.** `uf.py` escribe por `print` a stdout la línea "UF: usando caché …" la primera vez que carga la serie. Si molesta en los logs del backend, se puede capturar o se ajusta en una versión siguiente de `uf.py`.
- **Ejemplos** (UF real de la caché):
  - `predecir_plazo("ampliacion", 17_640_000, "2026-05-05")` devuelve `plazo_dias = 59`, intervalo 27–302.
  - `predecir_plazo("terminaciones", 3_869_750, "2025-11-16")` devuelve `plazo_dias = 12`, intervalo 5–61. La predicción central es 11,4 días y se redondea a 12; un plazo central de exactamente 12 días daría 5–62.

  El intervalo es amplio por un caso atípico (R05). Ver la model card.

### Mapeo `tipo_obra` → `clase_obra` (para el formulario)

| `tipo_obra` | `clase_obra` |
|---|---|
| `ampliacion` | edificacion |
| `obra_nueva` | edificacion |
| `alteracion_interior` | edificacion |
| `habilitacion_comercial` | edificacion |
| `reparacion_mantencion` | puntual |
| `terminaciones` | puntual |
| `muro_cierre` | puntual |
| `radier` | puntual |
| `remodelacion_bano_cocina` | puntual |
| `obra_menor_varia` | puntual |

El mapeo es determinista. **Nota R13:** el cobertizo (estructura nueva no habitable) se recodificó el 2026-11-01 de `obra_nueva` a `obra_menor_varia`. Por eso `obra_nueva` ya no admite la clase puntual. Si el formulario ofrece "obra nueva" para estructuras menores (cobertizos, bodegas abiertas), debe guiar a `obra_menor_varia`.

### INSERT a `versiones_modelo`

Los valores son los de `ml/models/plazo_v1.0-2026-11-01.json`. `provisional`, `filas_reales` y `filas_sinteticas` requieren las columnas sugeridas en el punto 1. Si no se agregan, hay que quitarlas del INSERT.

```sql
insert into versiones_modelo
  (version, algoritmo, filas_entrenamiento, mae_dias, rmse_dias, r2, validado,
   ruta_artefacto, vigente, entrenado_en, provisional, filas_reales, filas_sinteticas)
values
  ('v1.0-2026-11-01', 'parametrica', 13, 5.60, 7.70, 0.45, true,
   'ml/models/plazo_v1.0-2026-11-01.joblib', true, '2026-11-01', true, 13, 0);
```

- Las métricas son de leave-one-out sobre 12 casos reales, no del ajuste final.
- R² es solo informativo.
- `vigente = true` porque es la contingencia acordada (regla paramétrica provisional), no porque haya superado a la línea base: es la línea base.
