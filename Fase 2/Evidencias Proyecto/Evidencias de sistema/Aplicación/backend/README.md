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

### Sesión y errores

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| POST | `/autenticacion/iniciar-sesion` | público | `{access_token, refresh_token, token_type, expires_in}` |
| POST | `/autenticacion/refrescar` | público (sin Bearer) | igual que iniciar sesión — cuerpo `{refresh_token}` |

- Validar el token (`obtener_usuario_actual`): 401 si Supabase Auth lo rechaza; 503 si Auth no responde
  (timeout, sin conexión, 5xx, 429). Lo mismo al refrescar: 401 = hay que volver a entrar, 503 = reintentar.
- Supabase rota el refresh token: el anterior deja de servir. El backend no refresca por su cuenta
  (`get_anon_client` sin auto-refresco).
- Una excepción no controlada responde `500 {"detail": "Error interno del servidor."}` con cabeceras CORS
  (`app/errores.py`, por dentro de `CORSMiddleware`); el detalle queda en el log `buildcast.errores`.

### Permisos de escritura

Banco, plantillas y configuración los administra quien tiene `perfiles.rol_global = 'administrador'`
(tabla y funciones: `supabase/migrations/002_roles_permisos_auditoria.sql`). Los demás usuarios son
`profesional`: consultan, no administran. `GET /autenticacion/yo` informa `rol_global` y
`es_administrador_principal`.

Desde la migración 005 el rol cambia solo con el flujo de aprobación 3/3 (ver *Administración de usuarios*);
el backend ya no puede escribir `rol_global`.

- Sin rol administrador: 403.
- Las lecturas usan el token del usuario y respetan RLS.
- Las escrituras pasan por `exigir_editor_banco` (o el de plantillas o configuración), que solo acepta
  `rol_global = 'administrador'`, y luego usan `supabase_admin` (service role).
  Las tablas del banco no tienen políticas RLS de escritura.


## Administración de usuarios

Router: `app/routers/administracion.py` · Servicio: `app/services/servicio_administracion.py` ·
Tablas y RPC: `supabase/migrations/005_administracion_usuarios.sql`, `007_renovar_invitacion.sql` y
`008_acceso_configurado.sql`. Todo exige `rol_global = administrador`
(un profesional recibe 403).

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/administracion/usuarios` | `UsuarioAdministrado[]` — principales primero; con `estado` (Auth) y `solicitud_pendiente` |
| POST | `/administracion/usuarios` | `UsuarioCreado` (201) — cuerpo `{nombre, email}`; siempre `profesional` |
| POST | `/administracion/usuarios/{id}/renovar-invitacion` | `UsuarioCreado` — enlace nuevo (solo modo enlace); cuenta activa: 409 |
| GET | `/administracion/configuracion` | `{modo_invitacion}` — decide el texto de la acción en el panel |
| POST | `/administracion/usuarios/{id}/solicitar-administrador` | `SolicitudAdministrador` (201) |
| GET | `/administracion/solicitudes-administrador` | `SolicitudAdministrador[]` pendientes |
| POST | `/administracion/solicitudes-administrador/{id}/aprobar` | `SolicitudAdministrador` |
| POST | `/autenticacion/establecer-contrasena` | el invitado define su contraseña con la sesión del enlace; activa la cuenta; ya activa: 409 |

- **Administradores principales**: tabla `administradores_principales` (tres filas, se cargan una vez con
  `supabase/scripts/configurar_administradores_principales.sql`). Triggers: no entra un cuarto, no se quita ni
  se reemplaza a nadie, un principal no deja de ser administrador ni se puede borrar su perfil o su cuenta.
- **Promoción 3/3**: cualquier administrador solicita; solo los principales aprueban (también quien solicitó, si
  es principal). La RPC `aprobar_solicitud_administrador` bloquea la solicitud (`for update`), inserta la
  aprobación (única por principal), y con la tercera cambia el rol, cierra la solicitud y audita: todo en una
  transacción. 1/3 y 2/3 no cambian nada. Un administrador promovido no pasa a ser principal.
- **Crear usuarios**: con Supabase Auth Admin, después de validar al administrador. BuildCast no guarda
  contraseñas. `INVITACION_MODO=enlace` (por defecto) usa `generate_link(type=invite)` y devuelve el enlace
  solo en esa respuesta (`Cache-Control: no-store`; no se registra en logs ni en auditoría).
  `INVITACION_MODO=correo` usa `invite_user_by_email` y requiere SMTP propio. `FRONTEND_URL` define a dónde
  vuelve el enlace (`/acceso.html`).
- **Estado de acceso** (008): `perfiles.acceso_configurado_at` null = *Invitación pendiente*; fecha = *Activo*.
  No se usa `email_confirmed_at`: Supabase confirma el correo (y pone una contraseña aleatoria) apenas se abre el
  enlace. La fecha la pone la RPC `completar_acceso`, solo después de que Auth aceptó la contraseña. Los perfiles
  anteriores a la 008 quedan activos; las cuentas nuevas sin contraseña (invitadas) nacen pendientes.
- **Invitado pendiente**: su sesión vale solo para `GET /autenticacion/yo` (`acceso_configurado: false`) y
  `POST /autenticacion/establecer-contrasena`. Todo lo demás (lo que usa `obtener_usuario_actual`) responde 403
  con la cabecera `X-BuildCast-Acceso: pendiente`, que el frontend usa para llevarlo a *Crea tu contraseña*.
  Cerrar sesión es local. Sin la 008 aplicada, el control no bloquea a nadie.
- **Renovar invitación**: solo mientras el acceso siga pendiente; activa → 409.
  Reutiliza la misma cuenta: `generate_link(type=invite)` (o `invite_user_by_email` en modo correo) sobre un
  usuario existente sin confirmar reemplaza su token, así que el enlace anterior deja de servir. Si ya abrió un
  enlace (Auth lo confirmó), invite no aplica y se usa `generate_link(type=recovery)` (o
  `reset_password_for_email`), que lleva al mismo formulario. No se envía
  `data`, de modo que nombre y rol no cambian y no se crea otro perfil. Mismas reglas que al crear:
  `Cache-Control: no-store`, enlace fuera de logs y auditoría. Límite de envío de Supabase: 429.
- **Auditoría**: `auditoria_administracion` (solo anexar): `usuario_creado`, `solicitud_administrador_creada`,
  `administrador_aprobado`, `usuario_promovido_administrador`, `invitacion_renovada` (actor, usuario, correo y
  modo; nunca la URL, el OTP ni el token), `acceso_configurado` (sin contraseña ni token). No usa `historial_proyecto`.
- **Registro público**: `REGISTRO_PUBLICO=false` cierra `POST /autenticacion/registro` (403). Por defecto sigue
  abierto durante la transición; ver `docs/despliegue.md`.


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
| POST | `/proyectos/{id}/estimaciones` | propietario o editor | `EstimacionRespuesta` — cuerpo opcional `{version_precio_id?, gastos_generales_pct?, utilidad_pct?, aplicar_factores?, observaciones?}` |
| POST | `/proyectos/{id}/estimaciones/{estimacionId}/actualizar-cotizacion` | propietario o editor | `EstimacionRespuesta` (201) — cuerpo `{observaciones}` |
| POST | `/proyectos/{id}/estimaciones/{estimacionId}/plazo-profesional` | propietario o editor | `EstimacionRespuesta` (201) — cuerpo `{dias}` o `{usarSugerencia: true}` |
| GET | `/proyectos/{id}/estimaciones` | miembro | `EstimacionResumen[]` (más reciente primero) |
| GET | `/proyectos/{id}/estimaciones/{estimacionId}` | miembro | `EstimacionRespuesta` (incluye `observaciones`) |
| GET | `/configuracion` | autenticado | `Configuracion` de `configuracion.ts` + `capitulosEstandar`, `capitulosMaterialidad` |
| PUT | `/configuracion` | administrador | igual que GET; los capítulos son opcionales |

- Cada POST guarda la estimación (cabecera + líneas) en una transacción (RPC `crear_estimacion`) y responde con lo
  guardado. GET nunca recalcula: una estimación no cambia al editar partidas, banco, plantillas o configuración.
- Cada línea guarda partida de origen (si viene del catálogo), origen, nombre, unidad, cantidad, precio del banco,
  precio particular, precio usado, fuente, factor, subtotal base y subtotal.
- `aplicar_factores` es `false` si no se envía. Sin `version_precio_id` se usa la versión vigente (409 si no hay).
- Un proyecto sin partidas responde 409.
- **Observaciones** (migración 006): texto plano opcional, hasta 1000 caracteres; vacío se guarda como `null`.
  Cada estimación guarda su copia y no se modifica después (trigger). El formulario propone la observación de la
  última estimación; lo que se envía es lo que queda guardado.
- **Actualizar cotización**: si solo cambia la observación, la RPC `actualizar_cotizacion` crea una estimación nueva
  copiando montos, líneas, versión y firma de la más reciente (409 si no es la más reciente o si no cambió). No
  pasa por el motor, así que el estado del proyecto (vigente o por recalcular) no cambia. Queda en el historial
  como `cotizacion_actualizada`.

### Partidas del proyecto y plantillas

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| GET | `/proyectos/{id}/partidas` | miembro | `{plantilla_aplicada, plantilla_sugerida, version_precios, partidas[]}` |
| POST | `/proyectos/{id}/partidas` | propietario o editor | partida — `{origen: catalogo, partida_id, cantidad?}` o `{origen: manual, categoria_id, nombre, unidad, cantidad, precio_unitario_override}` |
| PUT | `/proyectos/{id}/partidas/{partidaProyectoId}` | propietario o editor | partida — parcial: `nombre, cantidad, precio_unitario_override, observacion` (unidad y categoría solo en manuales) |
| DELETE | `/proyectos/{id}/partidas/{partidaProyectoId}` | propietario o editor | 204 |
| POST | `/proyectos/{id}/partidas/ordenar` | propietario o editor | partidas — `{ids}` con todas en el nuevo orden |
| POST | `/proyectos/{id}/partidas/aplicar-plantilla` | propietario o editor | igual que GET — `{plantilla_id?, reemplazar}`; con partidas y sin `reemplazar` responde 409 |
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
- Permisos por proyecto (`proyecto_miembros`): `propietario`, `editor` y `lector`. "Miembro" es cualquiera de
  los tres. Quien no pertenece al proyecto recibe 404; un lector que intenta modificar, 403. Lo valida
  `servicio_proyectos.leer_proyecto(usuario, proyecto_id, minimo)` con `app/dependencies/permisos_proyecto.py`;
  el creador (`proyectos.usuario_id`) es propietario aunque le falte la fila de miembro. `ProyectoRespuesta`
  informa `mi_rol`.
- Todo pasa además por el token del usuario (RLS). Las políticas por membresía están en
  `supabase/migrations/003_rls_permisos_proyecto.sql`: propietario y editor leen y escriben, el lector solo
  lee y quien no pertenece no ve nada. El rol global no da acceso a proyectos: un administrador también debe
  ser miembro. Sin la 003 aplicada, RLS solo deja ver cada proyecto a su creador.

#### Miembros del proyecto

Router: `app/routers/miembros.py` · Servicio: `app/services/servicio_miembros.py` · Schemas: `app/schemas/miembro.py`.

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| GET | `/proyectos/{id}/miembros` | miembro | `Miembro[]` — `{usuario_id, email, nombre, rol, fecha_creacion}`, propietario primero |
| GET | `/proyectos/{id}/miembros/candidatos?buscar=` | propietario | `Candidato[]` — `{usuario_id, nombre, email}`, máx. 20 |
| POST | `/proyectos/{id}/miembros` | propietario | `Miembro` (201) — cuerpo `{email, rol: editor \| lector}` |
| PUT | `/proyectos/{id}/miembros/{usuarioId}` | propietario | `Miembro` — cuerpo `{rol: editor \| lector}` |
| DELETE | `/proyectos/{id}/miembros/{usuarioId}` | propietario | 204 |

- Se agrega a un usuario ya registrado por su correo exacto; no hay invitaciones. Correo sin cuenta: 404.
  Usuario que ya es miembro (o el propietario): 409.
- Candidatos: solo para el modal de agregar. Perfiles con correo que no son el propietario ni miembros,
  ordenados por nombre (o correo) y filtrados por `buscar` en nombre o correo, sin distinguir mayúsculas y como
  texto literal. Se leen con service role después de confirmar al propietario.
- Solo se asignan `editor` y `lector` (otro valor: 422). El propietario es único: no cambia de permiso ni se
  quita (409; también lo impide un trigger). Usuario que no es miembro: 404.
- Editor o lector que intenta modificar: 403. Quien no pertenece al proyecto: 404.
- Agregar, cambiar y quitar son RPC de PostgreSQL (`agregar_miembro_proyecto`,
  `cambiar_rol_miembro_proyecto`, `quitar_miembro_proyecto`; migración 003) que solo ejecuta `service_role`.
  El backend las llama después de comprobar que quien llama es propietario y cada una lo vuelve a comprobar.
  `proyecto_miembros` no se escribe de otra forma, tampoco con service role.
- Cada RPC hace el cambio y anexa su evento a `historial_proyecto` en la misma transacción
  (`miembro_agregado`, `miembro_rol_cambiado`, `miembro_eliminado`, con quién lo hizo, su correo,
  `entidad = miembro`, `entidad_id` = usuario afectado, valores anteriores y nuevos, `origen = rpc`):
  si falla el registro, tampoco queda el cambio.
- La lista se lee con service role después de comprobar que quien llama es miembro (por RLS cada usuario solo
  lee su propio perfil).
- `estado_estimacion` pasa a `recalcular` si cambian datos del proyecto, la versión vigente, o la cantidad, el precio
  particular, o se agrega o quita una partida (`firma_partidas`). Nombre, orden u observación no cuentan.

#### Historial del proyecto

Router: `app/routers/historial.py` · Servicio: `app/services/servicio_historial.py` · Schema: `app/schemas/historial.py`.

| Método | Ruta | Permiso | Respuesta |
|---|---|---|---|
| GET | `/proyectos/{id}/historial?limite=50` | miembro | `EventoHistorial[]`, el más reciente primero (`limite` de 1 a 200) |

- `EventoHistorial`: `{id, accion, entidad, entidad_id, usuario_id, usuario_email, usuario_nombre,
  valores_anteriores, valores_nuevos, origen, fecha}`. `usuario_nombre` sale de `perfiles` (service role,
  después de comprobar la membresía). Quien no pertenece: 404; sin token: 401. Solo lectura: no hay POST,
  PUT ni DELETE.
- Eventos de miembros: RPC de la 003, atómicos (`origen = rpc`).
- Eventos que anexa el backend después de la operación (`origen = api`), sin transacción común: si falla el
  registro, el cambio queda igual y el error va al log.
  - `proyecto_editado` (`proyecto`): solo los campos que cambiaron. Guardar lo mismo no registra nada.
  - `partida_agregada` / `partida_eliminada` (`proyecto_partida`): `nombre, unidad, cantidad, origen`.
  - `partida_editada` (`proyecto_partida`): campos cambiados; `valores_nuevos` incluye siempre `nombre`.
  - `plantilla_aplicada` (`plantilla`): `{nombre, partidas}`; `valores_anteriores = {partidas}` si reemplazó.
  - `estimacion_generada` (`estimacion`): `{costo_total, costo_m2, version_precio, completa, plazo_dias, version_modelo}`.
  - `plazo_profesional_definido` (`estimacion`): `valores_anteriores = {plazo_profesional_dias, plazo_profesional_estado}`,
    `valores_nuevos = {plazo_profesional_dias, plazo_profesional_origen}`.
  - `plazo_profesional_por_revisar` (`estimacion`): un recálculo deja por revisar un plazo que estaba definido.
    `valores_anteriores = {plazo_profesional_dias, plazo_profesional_estado: definido}`,
    `valores_nuevos = {plazo_profesional_dias, plazo_profesional_estado: por_revisar}`. Solo en ese paso:
    recalcular otra vez un plazo ya por revisar no lo repite.
- No se registran: creación del proyecto, reordenar partidas, eliminación del proyecto (el historial se va
  en cascada).

### Plazo estimado (modelo de ML v1, provisional)

El costo es determinista; el plazo lo estima el modelo de ML **después** del costo y se guarda en la misma fila de
`estimaciones` (migración `009_plazo_estimaciones.sql`).

- **Servicio:** `app/services/estimador_plazo.py`. Solo usa la biblioteca estándar, sin numpy, scikit-learn ni joblib.
  - Carga una sola vez `app/modelos/plazo_<version>.json`, que exporta `ml/src/exportar_backend.py`.
  - La versión vigente es `MODELO_PLAZO_VERSION` o, si no está definida, `v1.0-2026-11-01`.
  - Reproduce `ml/src/predict.py` exactamente; la paridad se prueba en 650 casos.
- **Flujo:** motor de costos → UF del día en Chile (`valores_uf`) → `estimar(tipo_obra, costo_total, completa, fecha)`
  → RPC `crear_estimacion`, que guarda costo y plazo juntos.
- **`estimar` nunca lanza.** Si falla, el plazo queda `no_disponible` con un motivo, y el costo se guarda igual.
  - Si la versión no está en `versiones_modelo` (FK), se guarda sin plazo, con motivo `version_no_registrada`.
- **`plazo_estado`**, en orden de prioridad:

  | Estado | Cuándo |
  |---|---|
  | `costo_incompleto` | la estimación tiene partidas sin precio o sin cantidad; P2 se calcula sobre el costo parcial |
  | `tipo_obra_no_representado` | el tipo traducido no tiene casos de entrenamiento (`obra_nueva`: *Vivienda unifamiliar*, *Edificación habitacional*) |
  | `fuera_rango_costo` | costo en UF fuera de 14,56–438,95 (motivo `costo_bajo_rango` o `costo_sobre_rango`) |
  | `dentro_dominio` | dentro del rango histórico; es el único que no es extrapolación (`plazo_fuera_dominio = false`) |
  | `respaldo` | sin UF para el día, o costo 0; se usa la mediana del entrenamiento (14 días, 2–35) |
  | `no_disponible` | tipo de obra sin traducción, modelo no cargado o error; sin días |

- **Snapshot:** se guardan `version_modelo`, `tipo_obra_modelo`, `uf_valor` y `uf_fecha` con el plazo.
  - *Actualizar cotización* copia el plazo tal cual, sin volver a ejecutar el modelo.
  - El plazo emitido y los parámetros de una versión publicada no se pueden modificar (triggers).
- **UF:** `valores_uf` se carga con `supabase/seeds/005_valores_uf_cmf.sql`. Para los días siguientes:
  ```bash
  cd backend
  CMF_API_KEY=... python -m scripts.actualizar_uf   # usa SUPABASE_SECRET_KEY; no pisa días ya cargados
  ```
  Programarlo todos los días (cron) está **pendiente**; ver `docs/despliegue.md`.
- **Versiones nuevas:** `ml/docs/publicar_version.md`.
- **Error medio observado:** `plazo.error_medio_dias` sale de `versiones_modelo.metricas.mae` (embebido por la FK
  `version_modelo`) y solo cuando `plazo_metodo` coincide con el método de la versión; con la mediana de respaldo
  es `null`. `plazo.estado_modelo` es `versiones_modelo.estado`. Nada de esto va al documento del cliente.

### Plazo para la cotización (lo define el profesional)

El modelo **sugiere**; el profesional **decide** (migración `010_plazo_profesional.sql`). Las columnas de la 009
siguen siendo el snapshot de la sugerencia y no se renombran. El plazo para la cotización se guarda aparte, en la
misma fila: `plazo_profesional_dias`, `_estado` (`sin_definir`, `definido`, `por_revisar`), `_origen`
(`sugerencia`, `manual`), `_fecha` y `_usuario_id`. Es el único plazo que muestra el documento de entrega.

- **Estimación nueva:** queda `sin_definir`. `crear_estimacion` ignora cualquier `plazo_profesional_*` del payload.
- **Definir:** `POST …/plazo-profesional` → RPC `definir_plazo_profesional`, que crea una estimación nueva igual a
  la vigente (montos, líneas, observación y sugerencia) con el plazo `definido`. No ejecuta el modelo.
  - `usarSugerencia`: el valor lo toma la RPC de `plazo_dias` de esa fila (409 si no hay sugerencia).
  - Solo sobre la estimación más reciente (409); mismo valor ya definido: 409; lector: 403; ajeno: 404.
- **Recalcular:** si la anterior tenía el plazo `definido` o `por_revisar`, la nueva queda `por_revisar` y conserva
  valor, origen, fecha y autor. *Actualizar cotización* copia el plazo profesional tal cual.
- **Inmutable:** el trigger `estimaciones_plazo_inmutable` cubre también las columnas `plazo_profesional_*` (salvo
  que `_usuario_id` pase a `null` al eliminar la cuenta).
- **Históricas:** las anteriores a la 010 quedan `sin_definir`; no se copia la sugerencia como plazo profesional.
- **Entrenamiento:** el plazo profesional no es verdad de entrenamiento; ver `ml/docs/publicar_version.md`.

### Datos iniciales

Instalación desde cero: `supabase/migrations/001_schema_buildcast.sql` y luego, en orden, `supabase/seeds/`:

| Seed | Contenido |
|---|---|
| `001_catalogo_base.sql` | 12 categorías y 58 partidas base (`catalogoBase.ts`) |
| `002_precios_referenciales.sql` | versión `2026-T3-REF` con precios de mercado (`preciosReferenciales.ts`), publicada como vigente |
| `003_configuracion_base.sql` | parámetros del cálculo (`configuracion.ts`) |
| `004_plantillas_base.sql` | 12 plantillas (3 tipos de obra × 4 materialidades), vacías |
| `005_valores_uf_cmf.sql` | UF diaria de la CMF, del 2025-02-01 al 2026-11-09, copiada de `ml/data/processed/uf_cmf.csv` (requiere la 009) |

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
