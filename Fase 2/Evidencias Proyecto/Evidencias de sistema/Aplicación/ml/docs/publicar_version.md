# Ciclo de versiones del modelo de plazo

Cómo pasan las obras reales de RAM a una versión nueva del modelo, sin tocar las estimaciones ya emitidas. **Nada de esto ocurre dentro de las peticiones de BuildCast**: entrenar, validar y publicar son pasos offline.

```text
nuevas obras reales → dataset → entrenamiento y validación offline → nueva versión → publicación → BuildCast usa la versión vigente
```

## Estado actual (v1.0-2026-11-01)

- **Versión provisional.** Regla paramétrica P2, calibrada con **la totalidad del dataset histórico disponible**: 13 presupuestos reales de RAM, con plazos **ofertados**, no ejecutados. No se reentrenó para integrarla.
- **Validación:** leave-one-out sobre 12 casos reales. MAE 5,60 días, RMSE 7,70 (ver la model card). Esas cifras solo valen **dentro del rango observado**:
  - costo de 14,56 a 438,95 UF;
  - plazos de 2 a 42 días;
  - tipos de obra presentes en el entrenamiento.
- **Fuera de ese rango el resultado es una extrapolación.** El backend lo calcula como valor referencial y lo marca con `plazo_estado` distinto de `dentro_dominio`. `obra_nueva`, que es como el backend traduce *Vivienda unifamiliar* y *Edificación habitacional*, no tiene ningún caso real.
- **Datos sintéticos:** no se usan. No constituyen evidencia de validación: como se generan con la propia regla, solo repetirían lo que el modelo ya supone. En las pruebas del backend aparecen modelos `v9.9-…`, que son fixtures técnicos y no versiones entrenadas.
- **Mejora esperada:** el modelo debería mejorar a medida que RAM incorpore obras ejecutadas con su plazo real.

## 1. Nuevas obras reales

La fuente prevista son los cierres de obra (HU-22: fecha de inicio y de término reales). **Hoy esa parte no existe**: no hay tabla `obras_ejecutadas`, y el frontend llama a `POST /proyectos/{id}/obra-ejecutada`, que el backend todavía no implementa. Es una tarea separada.

Diseño propuesto para esa tarea:
- Tabla `obras_ejecutadas`, una fila por proyecto cerrado, con estas columnas:
  - `proyecto_id`;
  - `estimacion_id`: la estimación con la que se ejecutó;
  - `fecha_inicio_real` y `fecha_termino_real`;
  - `plazo_real_dias` (corridos);
  - `costo_real` opcional;
  - `registrado_por` y `fecha_registro`.
- Cada estimación ya guarda lo necesario para armar el dataset sin recalcular nada:
  - el costo total (`costo_total`) y si estaba completa;
  - el tipo de obra (el de BuildCast y `tipo_obra_modelo`);
  - `uf_valor` y `uf_fecha`, que permiten obtener el costo en UF;
  - el plazo predicho, su rango, `version_modelo` y `plazo_estado`.

  Así el dataset puede comparar lo predicho con lo real por versión.

## 2. Dataset

- Exportar obras ejecutadas y sus estimaciones a `ml/data/` (anonimizado: sin nombres ni datos de clientes; ver `diccionario_variables.md`).
- Marcar `tipo_plazo = ejecutado`. No mezclar plazos ofertados y ejecutados sin una decisión explícita.
- Validar con `ml/src/validar_dataset.py`.

## 3. Entrenamiento y validación offline

- En el entorno de ML (`ml/requirements.txt`, Python 3.13): `evaluacion.py` y `entrenar.py`.
- Evaluar solo con casos reales, que no se usaron para calibrar. Comparar contra la versión vigente y contra las líneas base.
- Actualizar la model card con las métricas y el dominio nuevos.

## 4. Versión nueva

- `entrenar.py` genera `ml/models/plazo_<version>.joblib` y su `.json`. La versión lleva la fecha (`vX.Y-AAAA-MM-DD`).
- Exportar al backend:
  ```
  ml/.venv/Scripts/python ml/src/exportar_backend.py --version <version> --paridad
  ```
  Esto escribe `backend/app/modelos/plazo_<version>.json`, con parámetros, dominio sacado del dataset y traducción de tipos de obra, y los casos de paridad con `predict.py` en `backend/tests/datos/`.
- Si la versión nueva usa un estimador (Ridge u otro), `exportar_backend.py` rechaza el artefacto: hay que exportar sus coeficientes a JSON. El backend no carga scikit-learn.

## 5. Publicación

En este orden, para que ninguna estimación quede apuntando a una versión inexistente:

1. Registrar la versión en Supabase (`insert into versiones_modelo …`, con el mismo JSON en `parametros`), con `vigente = false`.
2. Desplegar el backend con el JSON nuevo y `MODELO_PLAZO_VERSION=<version>`.
3. Marcar la nueva como `vigente = true` y la anterior como `false`. Solo puede haber una vigente: un índice único lo impide.

Si el backend usa una versión que no está registrada, la estimación de costo se guarda igual y el plazo queda como `no_disponible`, con motivo `version_no_registrada`.

## 6. BuildCast usa la versión vigente

- Cada estimación nueva guarda su plazo y `version_modelo`.
- Las anteriores no cambian:
  - el plazo emitido es inmutable (trigger `estimaciones_plazo_inmutable`);
  - los parámetros de una versión publicada también (trigger `versiones_modelo_inmutables`);
  - una versión se retira con `estado = 'retirado'`, nunca se borra.
- *Actualizar cotización* copia el plazo de la estimación que reemplaza y no vuelve a ejecutar el modelo.

## 7. Plazo sugerido, plazo para la cotización y plazo real (migración 010)

Desde la migración `010_plazo_profesional.sql`, BuildCast guarda **tres datos de plazo distintos**, que no se mezclan ni se copian entre sí sin una acción explícita del usuario:

| Dato | Dónde se guarda | Quién lo escribe | Para qué sirve |
|---|---|---|---|
| Plazo sugerido por el modelo | `estimaciones.plazo_dias`, `plazo_min_dias`, `plazo_max_dias` y la metadata de la 009 (`version_modelo`, `plazo_estado`, `uf_valor`…) | El backend, con la versión vigente del modelo | Referencia interna para el profesional; trazabilidad de cada versión |
| Plazo para la cotización | `estimaciones.plazo_profesional_dias`, `_estado`, `_origen`, `_fecha`, `_usuario_id` | El profesional (propietario o editor), aceptando la sugerencia o escribiendo otro valor | Es el plazo del documento de entrega al cliente |
| Plazo real ejecutado | `obras_ejecutadas.plazo_real_dias` (otra HU; todavía no existe) | Quien registra el cierre de la obra | **Evidencia principal para entrenar** |

Flujo previsto:

```text
modelo sugiere → profesional decide → obra se ejecuta → se registra el plazo real
              → entrenamiento offline → nueva versión del modelo
```

Reglas para armar datasets futuros:

- **`plazo_profesional_dias` no es verdad de entrenamiento.** Es una decisión comercial (puede incluir holguras, acuerdos con el mandante o simplemente aceptar la sugerencia). Si se exporta, es solo una variable de análisis, marcada con `tipo_plazo = profesional`, y nunca se mezcla con `ejecutado`.
- Cuando el profesional usó la sugerencia (`plazo_profesional_origen = 'sugerencia'`), su valor es el mismo número del modelo: entrenar con él solo repetiría lo que el modelo ya supone, igual que los datos sintéticos.
- La etiqueta para entrenar es `plazo_real_dias` (`tipo_plazo = ejecutado`), junto con el costo y la UF de la estimación con que se ejecutó la obra.
- Comparar `plazo_dias` (sugerido), `plazo_profesional_dias` (comprometido) y `plazo_real_dias` (ejecutado) por versión sirve para evaluar el modelo y el criterio de ajuste del profesional, sin reescribir ninguno de los tres.
- Las estimaciones anteriores a la 010 quedan con el plazo profesional `sin_definir`: la sugerencia histórica no se convirtió en decisión del profesional.
- No hay reentrenamiento automático: todo lo anterior ocurre offline, siguiendo las secciones 2 a 5.

Al recalcular el costo, el plazo profesional anterior no se borra: la estimación nueva lo conserva como `por_revisar` hasta que el profesional lo confirme o lo cambie. *Actualizar cotización* (solo la observación) copia tanto la sugerencia como el plazo profesional, sin ejecutar el modelo.
