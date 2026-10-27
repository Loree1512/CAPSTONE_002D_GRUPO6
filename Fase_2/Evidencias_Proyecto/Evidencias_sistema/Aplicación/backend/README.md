# Backend

API y lógica de negocio de BuildCast.

## Tecnologías

- Python
- FastAPI
- Pydantic
- Supabase / PostgreSQL

## Responsabilidad

Esta carpeta contiene el backend de BuildCast.

El backend será responsable de:

- Exponer la API REST.
- Validar los datos recibidos desde el frontend.
- Gestionar proyectos.
- Comunicarse con Supabase.
- Ejecutar el motor de estimación de costos.
- Aplicar factores y configuraciones.
- Integrar el modelo de Machine Learning.
- Registrar la trazabilidad de las estimaciones.
- Generar documentos PDF.
- Gestionar integraciones externas cuando corresponda.


## Banco de precios

Router: `app/routers/banco.py` · Servicio: `app/services/servicio_banco.py` · Schemas: `app/schemas/banco.py`.
Tablas, triggers y RPCs: `supabase/migrations/001_schema_buildcast.sql`.

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| GET | `/banco/categorias` | autenticado | `CategoriaPartida[]` (solo vigentes, por `orden`) |
| GET | `/banco/versiones` | autenticado | `VersionPrecios[]` (más recientes primero) |
| POST | `/banco/versiones` | editor | `VersionPrecios` — cuerpo `{version, copiar_de}` |
| POST | `/banco/versiones/{id}/publicar` | editor | `VersionPrecios` |
| GET | `/banco/partidas?version={id}` | autenticado | `FilaBanco[]` — sin `version`, la vigente |
| POST | `/banco/partidas` | editor | `Partida` — cuerpo `{categoria_id, nombre, unidad}` |
| PUT | `/banco/partidas/{id}` | editor | `Partida` — cuerpo parcial `{nombre, unidad, categoria_id}` |
| POST | `/banco/partidas/{id}/baja` | editor | `Partida` |
| PUT | `/banco/versiones/{versionId}/precios/{partidaId}` | editor | `FilaBanco` — cuerpo `{precio_unitario, rendimiento_mo, fuente?}` |

- Las formas de respuesta son las de `frontend/src/tipos/api.ts`.
- `GET /banco/partidas` devuelve todas las partidas (incluidas las dadas de baja);
  las que no tienen valores en la versión llegan con `precio_unitario`, `rendimiento_mo`
  y `fuente` en `null`. Un id de versión inexistente responde 404.
- El precio y el rendimiento de mano de obra están versionados en `precios_partida`
  (el rendimiento es un dato de referencia: el motor no lo usa):
  editar una versión no altera las demás. Si ambos quedan en `null`, la fila se elimina.
  Sin `fuente`, una edición queda marcada como `Editado por la oficina`.
- Estados de una versión: `borrador` (`fecha_publicacion` null, editable), `vigente` y `historica` (publicadas:
  inmutables para siempre). Editar precios o rendimientos de una publicada responde 409; triggers de la base lo impiden
  también en la base. Para cambiar precios se copia a un borrador, se edita y se publica; las estimaciones hechas con
  la anterior quedan en `recalcular`. Publicar fija `fecha_publicacion` la primera vez; volver a marcar vigente una
  histórica no la cambia.
- Una partida con precios en cualquier versión no cambia de unidad (409; también por trigger): se da de baja y se crea
  otra. `GET /banco/partidas` informa `tiene_precios` (vista `partidas_con_precios`).
- Crear versión (con copia), publicar versión y crear partida son RPCs de PostgreSQL:
  cada una es atómica y solo puede ejecutarla `service_role`.
- Errores en `detail` (español): 403 sin permiso de edición, 404 recurso inexistente,
  409 duplicado / partida base / partida dada de baja, 422 datos inválidos
  (incluye `precio_unitario` o `rendimiento_mo` menores o iguales a 0).

### Permisos de escritura (temporal)

Mientras no existan perfiles y roles, las escrituras del banco se autorizan con la variable
`BANCO_EDITORES`: UUIDs de `auth.users` separados por coma.

```env
BANCO_EDITORES=11111111-2222-3333-4444-555555555555,66666666-7777-8888-9999-000000000000
```

- Vacía o ausente: nadie puede escribir (403).
- Las lecturas usan el token del usuario y respetan RLS.
- Las escrituras pasan por `exigir_editor_banco` y luego usan `supabase_admin` (service role).
  Las tablas del banco no tienen políticas RLS de escritura.
- El UUID de un usuario se obtiene con `GET /autenticacion/yo` (campo `id`) o en Supabase:
  Authentication → Users.
- Configurarla en `backend/.env` (local) y en Vercel → proyecto del backend → Settings →
  Environment Variables. En Vercel, un cambio de variable requiere un nuevo despliegue.


## Motor de costos

Motor puro: `app/services/motor_costos.py` (sin Supabase, con `Decimal`) · Snapshot/respuesta:
`app/services/snapshot_estimacion.py` · Consultas y guardado: `app/services/servicio_estimaciones.py`,
`app/services/servicio_configuracion.py` · Routers: `app/routers/estimaciones.py`, `app/routers/configuracion.py`.
Tablas y RPC: `supabase/migrations/001_schema_buildcast.sql`.

Presupuesto por partidas del proyecto. Mismo cálculo que `frontend/src/lib/motorCosto.ts`:

```text
precio        = precio_unitario_override ?? precio del banco (versión usada)
subtotal_base = CLP(cantidad × precio)             (sin cantidad → sin_cantidad; sin precio → sin_precio)
factor        = aplicar_factores ? factor_comuna × factor_pisos : 1
subtotal      = CLP(subtotal_base × factor)
costo directo    = Σ subtotal
gastos generales = CLP(costo directo × GG% / 100)
utilidad         = CLP(costo directo × utilidad% / 100)
total = costo directo + gastos generales + utilidad        costo m² = total / superficie (sin redondear)
```

`CLP(x)` = peso entero con `ROUND_HALF_UP` (`redondear_clp`; en TypeScript `redondearClp`). Cada monto se redondea
una vez y el total suma montos ya redondeados: 1.875.750 con 5 % y 7 % da 93.788 + 131.303 → 2.100.841.

- Las cantidades las define el profesional en cada proyecto; la mano de obra es una partida más.
- Estándar y materialidad no afectan el costo; la materialidad elige la plantilla.

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| POST | `/proyectos/{id}/estimaciones` | dueño del proyecto | `EstimacionRespuesta` — cuerpo opcional `{version_precio_id?, gastos_generales_pct?, utilidad_pct?, aplicar_factores?}` |
| GET | `/proyectos/{id}/estimaciones` | dueño del proyecto | `EstimacionResumen[]` (más reciente primero) |
| GET | `/proyectos/{id}/estimaciones/{estimacionId}` | dueño del proyecto | `EstimacionRespuesta` |
| GET | `/configuracion` | autenticado | `Configuracion` de `configuracion.ts` + `capitulosEstandar`, `capitulosMaterialidad` |
| PUT | `/configuracion` | editor (`BANCO_EDITORES`) | igual que GET; los capítulos son opcionales |

- Cada POST guarda la estimación (cabecera + líneas) en una transacción (RPC `crear_estimacion`) y responde con lo
  guardado. GET nunca recalcula: una estimación no cambia al editar partidas, banco, plantillas o configuración.
- Cada línea guarda partida de origen (si viene del catálogo), origen, nombre, unidad, cantidad, precio del banco,
  precio particular, precio usado, fuente, factor, subtotal base y subtotal.
- `aplicar_factores` es `false` si no se envía. Sin `version_precio_id` se usa la versión vigente (409 si no hay).
- Un proyecto sin partidas responde 409.

### Partidas del proyecto y plantillas

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| GET | `/proyectos/{id}/partidas` | dueño | `{plantilla_aplicada, plantilla_sugerida, version_precios, partidas[]}` |
| POST | `/proyectos/{id}/partidas` | dueño | partida — `{origen: catalogo, partida_id, cantidad?}` o `{origen: manual, categoria_id, nombre, unidad, cantidad, precio_unitario_override}` |
| PUT | `/proyectos/{id}/partidas/{partidaProyectoId}` | dueño | partida — parcial: `nombre, cantidad, precio_unitario_override, observacion` (unidad y categoría solo en manuales) |
| DELETE | `/proyectos/{id}/partidas/{partidaProyectoId}` | dueño | 204 |
| POST | `/proyectos/{id}/partidas/ordenar` | dueño | partidas — `{ids}` con todas en el nuevo orden |
| POST | `/proyectos/{id}/partidas/aplicar-plantilla` | dueño | igual que GET — `{plantilla_id?, reemplazar}`; con partidas y sin `reemplazar` responde 409 |
| GET | `/plantillas` | autenticado | `PlantillaResumen[]` con `cantidad_partidas` |
| GET | `/plantillas/{id}` | autenticado | `PlantillaDetalle` con sus partidas |
| POST | `/plantillas` | editor | `PlantillaDetalle` — `{nombre, tipo_obra, materialidad, vigente?}` |
| PUT | `/plantillas/{id}` | editor | `PlantillaDetalle` — parcial |
| PUT | `/plantillas/{id}/partidas` | editor | `PlantillaDetalle` — `{partidas: [{partida_id, cantidad_sugerida?}]}` en orden |
| PUT | `/banco/partidas/{id}` | editor | `Partida` — parcial `{nombre, unidad, categoria_id}`; el código no cambia |

- Al crear un proyecto se copia la plantilla vigente de su `tipo_obra + materialidad` en la misma transacción
  (RPC `crear_proyecto_con_plantilla`): si la copia falla, el proyecto no se crea. Sin plantilla, nace sin partidas.
- La copia es por valor: editar la plantilla o el catálogo después no cambia proyectos ni estimaciones.
- Una partida manual no se agrega al catálogo global.
- Todo pasa por el token del usuario (RLS): un proyecto o partida ajena responde 404.
- `estado_estimacion` pasa a `recalcular` si cambian datos del proyecto, la versión vigente, o la cantidad, el precio
  particular, o se agrega o quita una partida (`firma_partidas`). Nombre, orden u observación no cuentan.

### Datos iniciales

Instalación desde cero: `supabase/migrations/001_schema_buildcast.sql` y luego, en orden, `supabase/seeds/`:

| Seed | Contenido |
|---|---|
| `001_catalogo_base.sql` | 12 categorías y 58 partidas base (`catalogoBase.ts`) |
| `002_precios_referenciales.sql` | versión `2026-T3-REF` con precios de mercado (`preciosReferenciales.ts`), publicada como vigente |
| `003_configuracion_base.sql` | parámetros del cálculo (`configuracion.ts`) |
| `004_plantillas_base.sql` | 12 plantillas (3 tipos de obra × 4 materialidades), vacías |

Son idempotentes y no sobrescriben datos editados por la oficina. `tests/test_motor_costos.py` verifica que catálogo,
precios y configuración coincidan con el frontend.

`supabase/reset_buildcast_dev.sql` borra datos y esquema de BuildCast en `public` (no toca `auth` ni `storage`) para
volver a instalar. **Solo desarrollo.**

### Pruebas

```bash
cd backend
python -m pytest            # o: python -m unittest discover -s tests -v
```

`tests/datos/referencia_motor_ts.json` guarda los datos de fábrica del frontend para comparar los seeds.
Si cambian, regenerarla (requiere `frontend/node_modules`):

```bash
node backend/tests/paridad/generar_referencia.mjs
```
