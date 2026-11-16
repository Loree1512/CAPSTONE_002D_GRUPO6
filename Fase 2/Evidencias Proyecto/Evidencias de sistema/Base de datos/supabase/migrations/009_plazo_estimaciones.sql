-- 009: plazo estimado (modelo de ML v1, provisional) guardado junto a cada estimación.

-- 1. Valores de la UF
-- Una fila por día, tal como la publica la CMF. Se cargan con
create table public.valores_uf (
    fecha date primary key,
    valor numeric(12, 2) not null
        check (valor > 0),
    fuente text not null
        check (btrim(fuente) <> ''),
    fecha_actualizacion timestamptz not null default now()
);

alter table public.valores_uf enable row level security;

create policy "valores_uf_seleccionar"
    on public.valores_uf
    for select
    to authenticated
    using (true);

revoke all on public.valores_uf from public, anon, authenticated, service_role;
grant select on public.valores_uf to authenticated;
grant select, insert, update on public.valores_uf to service_role;


-- 2. Versiones del modelo
-- Cada versión publicada queda fija: parámetros, dominio y métricas no se editan.
-- Solo cambian su estado, si es la vigente y sus observaciones.

create table public.versiones_modelo (
    id uuid primary key default gen_random_uuid(),

    version text not null unique
        check (version ~ '^v[0-9]+\.[0-9]+-[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
    objetivo text not null default 'plazo'
        check (objetivo in ('plazo')),
    metodo text not null
        check (btrim(metodo) <> ''),
    algoritmo text not null
        check (btrim(algoritmo) <> ''),
    entrenado_en date not null,

    estado text not null
        check (estado in ('provisional', 'validado', 'retirado')),
    vigente boolean not null default false,

    -- El mismo JSON que carga el backend (app/modelos/plazo_<version>.json).
    parametros jsonb not null,
    -- Rango conocido: costo en UF, plazos y tipos de obra del entrenamiento.
    dominio jsonb not null,
    metricas jsonb,

    observaciones text,
    fecha_publicacion timestamptz not null default now(),

    constraint versiones_modelo_retirada_no_vigente_chk
        check (not (vigente and estado = 'retirado'))
);

-- Como máximo una versión vigente por objetivo.
create unique index versiones_modelo_vigente_idx
    on public.versiones_modelo (objetivo)
    where vigente;

create or replace function public.proteger_version_modelo()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'Una versión del modelo publicada no se elimina; se retira.'
            using errcode = '55000';
    end if;
    if new.version is distinct from old.version
       or new.objetivo is distinct from old.objetivo
       or new.metodo is distinct from old.metodo
       or new.algoritmo is distinct from old.algoritmo
       or new.entrenado_en is distinct from old.entrenado_en
       or new.parametros is distinct from old.parametros
       or new.dominio is distinct from old.dominio
       or new.metricas is distinct from old.metricas
       or new.fecha_publicacion is distinct from old.fecha_publicacion then
        raise exception 'Los parámetros de una versión del modelo publicada no se modifican; publica una versión nueva.'
            using errcode = '55000';
    end if;
    return new;
end;
$$;

revoke execute on function public.proteger_version_modelo() from public, anon, authenticated, service_role;

create trigger versiones_modelo_inmutables
    before update or delete on public.versiones_modelo
    for each row
    execute function public.proteger_version_modelo();

alter table public.versiones_modelo enable row level security;

create policy "versiones_modelo_seleccionar"
    on public.versiones_modelo
    for select
    to authenticated
    using (true);

revoke all on public.versiones_modelo from public, anon, authenticated, service_role;
grant select on public.versiones_modelo to authenticated;
grant select, insert, update on public.versiones_modelo to service_role;

-- v1: la regla paramétrica P2 de ml/models/plazo_v1.0-2026-11-01.joblib.
insert into public.versiones_modelo (
    version, objetivo, metodo, algoritmo, entrenado_en, estado, vigente,
    parametros, dominio, metricas, observaciones
)
select
    m ->> 'version', 'plazo', m ->> 'metodo', m ->> 'algoritmo', (m ->> 'entrenado_en')::date,
    m ->> 'estado', true,
    m, m -> 'dominio', m -> 'metricas_loo', m ->> 'observaciones'
from (select $modelo$
{
  "formato": 1,
  "objetivo": "plazo",
  "version": "v1.0-2026-11-01",
  "metodo": "P2",
  "algoritmo": "parametrica",
  "entrenado_en": "2026-11-01",
  "estado": "provisional",
  "validado": true,
  "provisional": true,
  "parametros": {
    "alpha": -1.6149928711098143,
    "beta": 0.8901844312875308,
    "gamma": 0.2685900893730273
  },
  "tipo_a_clase": {
    "ampliacion": "edificacion",
    "habilitacion_comercial": "edificacion",
    "obra_nueva": "edificacion",
    "alteracion_interior": "edificacion",
    "terminaciones": "puntual",
    "remodelacion_bano_cocina": "puntual",
    "radier": "puntual",
    "muro_cierre": "puntual",
    "obra_menor_varia": "puntual",
    "reparacion_mantencion": "puntual"
  },
  "traduccion_tipo_obra": {
    "Ampliación": "ampliacion",
    "Vivienda unifamiliar": "obra_nueva",
    "Edificación habitacional": "obra_nueva"
  },
  "intervalo": {
    "q_inf_log": -0.7412831495147608,
    "q_sup_log": 1.6385059990348552,
    "percentiles": [
      10,
      90
    ],
    "metodo_percentil": "weibull"
  },
  "mediana_respaldo": {
    "plazo_dias": 14.0,
    "q_inf_log": -1.6710229294930663,
    "q_sup_log": 0.8906681345001272,
    "percentiles": [
      10,
      90
    ],
    "metodo_percentil": "weibull"
  },
  "dominio": {
    "costo_uf_min": 14.56,
    "costo_uf_max": 438.95,
    "plazo_dias_min": 2,
    "plazo_dias_max": 42,
    "tipos_obra_representados": [
      "alteracion_interior",
      "ampliacion",
      "habilitacion_comercial",
      "muro_cierre",
      "obra_menor_varia",
      "radier",
      "remodelacion_bano_cocina",
      "reparacion_mantencion",
      "terminaciones"
    ],
    "filas_entrenamiento": 13,
    "ids_entrenamiento": [
      "R02",
      "R03",
      "R04",
      "R05",
      "R06",
      "R08",
      "R09",
      "R10",
      "R11",
      "R13",
      "R14",
      "R16",
      "R17"
    ],
    "tipo_plazo": "ofertado"
  },
  "metricas_loo": {
    "mae": 5.597655503039676,
    "rmse": 7.697974088577048,
    "sd_ae": 5.519393043477937,
    "ae_min": 0.28949678106509946,
    "ae_max": 19.75626517699255,
    "r2": 0.44743457036520606
  },
  "fuente_uf": "https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/2025/01",
  "origen": {
    "artefacto": "ml/models/plazo_v1.0-2026-11-01.joblib",
    "sha256": "b2e17823b6fd48816d70a3a29f73e70b94dad1894015a576e5370a5c61d4b2c8"
  },
  "observaciones": "Versión provisional. Regla paramétrica P2 calibrada con la totalidad del dataset histórico disponible (13 presupuestos reales de RAM, plazos ofertados). Fuera del rango de costo o de los tipos de obra representados, el resultado es una extrapolación. No se usaron datos sintéticos."
}
$modelo$::jsonb as m) v
on conflict (version) do nothing;


-- 3. Plazo en cada estimación

alter table public.estimaciones
    add column plazo_dias integer,
    add column plazo_min_dias integer,
    add column plazo_max_dias integer,
    add column plazo_metodo text
        constraint estimaciones_plazo_metodo_chk check (plazo_metodo is null or btrim(plazo_metodo) <> ''),
    add column plazo_provisional boolean,
    -- Solo dentro_dominio corresponde al dominio conocido del modelo.
    add column plazo_estado text not null default 'no_disponible'
        constraint estimaciones_plazo_estado_chk check (plazo_estado in (
            'dentro_dominio', 'fuera_rango_costo', 'tipo_obra_no_representado',
            'costo_incompleto', 'respaldo', 'no_disponible')),
    add column plazo_fuera_dominio boolean
        generated always as (plazo_estado <> 'dentro_dominio') stored,
    add column plazo_motivo text
        constraint estimaciones_plazo_motivo_chk check (plazo_motivo is null or btrim(plazo_motivo) <> ''),
    add column version_modelo text
        references public.versiones_modelo(version) on delete restrict,
    -- Tipo de obra en el vocabulario del modelo (p. ej. ampliacion, obra_nueva).
    add column tipo_obra_modelo text,
    add column uf_valor numeric(12, 2)
        constraint estimaciones_uf_valor_chk check (uf_valor is null or uf_valor > 0),
    add column uf_fecha date;

alter table public.estimaciones
    add constraint estimaciones_plazo_orden_chk check (
        (plazo_dias is null and plazo_min_dias is null and plazo_max_dias is null)
        or (plazo_dias is not null and plazo_min_dias is not null and plazo_max_dias is not null
            and 1 <= plazo_min_dias and plazo_min_dias <= plazo_dias and plazo_dias <= plazo_max_dias)
    ),
    add constraint estimaciones_plazo_estado_datos_chk check (
        case
            when plazo_estado = 'no_disponible' then plazo_dias is null
            else plazo_dias is not null and version_modelo is not null and plazo_metodo is not null
                 and plazo_provisional is not null
        end
    ),
    add constraint estimaciones_uf_completa_chk check ((uf_valor is null) = (uf_fecha is null)),
    -- Sin UF solo cabe el respaldo o no tener plazo.
    add constraint estimaciones_plazo_uf_chk check (
        uf_valor is not null or plazo_estado in ('respaldo', 'no_disponible')
    );

-- Estimaciones anteriores: el plazo se calculaba en el navegador y no se guardaba.
update public.estimaciones
set plazo_motivo = 'anterior_al_modelo'
where plazo_estado = 'no_disponible' and plazo_motivo is null;

-- El plazo emitido no cambia: una versión nueva del modelo no reescribe el pasado.
create or replace function public.bloquear_cambio_plazo()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if (new.plazo_dias, new.plazo_min_dias, new.plazo_max_dias, new.plazo_metodo, new.plazo_provisional,
        new.plazo_estado, new.plazo_motivo, new.version_modelo, new.tipo_obra_modelo, new.uf_valor, new.uf_fecha)
       is distinct from
       (old.plazo_dias, old.plazo_min_dias, old.plazo_max_dias, old.plazo_metodo, old.plazo_provisional,
        old.plazo_estado, old.plazo_motivo, old.version_modelo, old.tipo_obra_modelo, old.uf_valor, old.uf_fecha) then
        raise exception 'El plazo de una estimación emitida no se modifica.'
            using errcode = '55000';
    end if;
    return new;
end;
$$;

revoke execute on function public.bloquear_cambio_plazo() from public, anon, authenticated, service_role;

create trigger estimaciones_plazo_inmutable
    before update on public.estimaciones
    for each row
    execute function public.bloquear_cambio_plazo();


-- 4. crear_estimacion guarda también el plazo
-- Igual que en 006, más las columnas del plazo.

create or replace function public.crear_estimacion(
    p_usuario_id uuid,
    p_estimacion jsonb,
    p_partidas jsonb
)
returns public.estimaciones
language plpgsql
set search_path = ''
as $$
declare
    v_proyecto_id uuid := (p_estimacion ->> 'proyecto_id')::uuid;
    v_existe boolean;
    v_creador uuid;
    v_rol text;
    v_estimacion public.estimaciones;
begin
    select true, p.usuario_id into v_existe, v_creador
    from public.proyectos p
    where p.id = v_proyecto_id;

    select m.rol into v_rol
    from public.proyecto_miembros m
    where m.proyecto_id = v_proyecto_id
      and m.usuario_id = p_usuario_id;

    -- Sin proyecto, sin usuario o sin pertenecer a él: no se revela que existe.
    if v_existe is not true
       or p_usuario_id is null
       or (v_rol is null and v_creador is distinct from p_usuario_id) then
        raise exception 'El proyecto no existe.'
            using errcode = 'P0002';
    end if;

    if v_creador is distinct from p_usuario_id and v_rol not in ('propietario', 'editor') then
        raise exception 'Tu permiso en este proyecto no permite generar estimaciones.'
            using errcode = '42501';
    end if;

    if jsonb_typeof(p_partidas) is distinct from 'array' then
        raise exception 'Las partidas de la estimación deben ser una lista.'
            using errcode = '22023';
    end if;

    insert into public.estimaciones (
        proyecto_id, usuario_id,
        version_precio_id, version_precio, fuente_version_precio,
        comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones,
        parametros_snapshot, version_motor,
        aplicar_factores, factor_comuna, factor_pisos, factor_ajuste,
        costo_directo_base, costo_directo, gastos_generales_pct, gastos_generales,
        utilidad_pct, utilidad, costo_total, costo_m2,
        partidas_calculadas, partidas_sin_precio, partidas_sin_cantidad,
        firma_partidas, completa, observaciones,
        plazo_dias, plazo_min_dias, plazo_max_dias, plazo_metodo, plazo_provisional,
        plazo_estado, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha
    )
    select
        v_proyecto_id, p_usuario_id,
        r.version_precio_id, r.version_precio, r.fuente_version_precio,
        r.comuna, r.tipo_obra, r.materialidad, r.superficie_m2, r.numero_pisos, r.estandar_terminaciones,
        r.parametros_snapshot, r.version_motor,
        r.aplicar_factores, r.factor_comuna, r.factor_pisos, r.factor_ajuste,
        r.costo_directo_base, r.costo_directo, r.gastos_generales_pct, r.gastos_generales,
        r.utilidad_pct, r.utilidad, r.costo_total, r.costo_m2,
        r.partidas_calculadas, r.partidas_sin_precio, r.partidas_sin_cantidad,
        r.firma_partidas, r.completa, nullif(btrim(r.observaciones), ''),
        r.plazo_dias, r.plazo_min_dias, r.plazo_max_dias, r.plazo_metodo, r.plazo_provisional,
        -- Un backend sin plazo (anterior a la 009) guarda la estimación igual.
        coalesce(r.plazo_estado, 'no_disponible'),
        case when r.plazo_estado is null then coalesce(r.plazo_motivo, 'sin_datos_de_plazo') else r.plazo_motivo end,
        r.version_modelo, r.tipo_obra_modelo, r.uf_valor, r.uf_fecha
    from jsonb_populate_record(null::public.estimaciones, p_estimacion) r
    returning * into v_estimacion;

    insert into public.estimacion_partidas (
        estimacion_id, proyecto_partida_id, partida_id, orden, origen,
        codigo_partida, nombre_partida, unidad, observacion,
        categoria_id, categoria_codigo, categoria_nombre, categoria_orden,
        estado, cantidad,
        precio_unitario_banco, precio_unitario_override, precio_unitario_usado, fuente_precio,
        factor_aplicado, subtotal_base, subtotal
    )
    select
        v_estimacion.id, r.proyecto_partida_id, r.partida_id, r.orden, r.origen,
        r.codigo_partida, r.nombre_partida, r.unidad, r.observacion,
        r.categoria_id, r.categoria_codigo, r.categoria_nombre, r.categoria_orden,
        r.estado, r.cantidad,
        r.precio_unitario_banco, r.precio_unitario_override, r.precio_unitario_usado, r.fuente_precio,
        r.factor_aplicado, r.subtotal_base, r.subtotal
    from jsonb_populate_recordset(null::public.estimacion_partidas, p_partidas) r;

    return v_estimacion;
end;
$$;

revoke execute on function public.crear_estimacion(uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.crear_estimacion(uuid, jsonb, jsonb) to service_role;


-- 5. actualizar_cotizacion copia también el plazo
-- Igual que en 006: solo cambia la observación. El plazo, su versión y su UF se
-- copian tal cual; el modelo no se vuelve a ejecutar.

create or replace function public.actualizar_cotizacion(
    p_usuario_id uuid,
    p_estimacion_id uuid,
    p_observaciones text
)
returns public.estimaciones
language plpgsql
set search_path = ''
as $$
declare
    v_origen public.estimaciones;
    v_creador uuid;
    v_rol text;
    v_ultima uuid;
    v_observaciones text := nullif(btrim(p_observaciones), '');
    v_estimacion public.estimaciones;
begin
    select * into v_origen from public.estimaciones e where e.id = p_estimacion_id;

    if found then
        select p.usuario_id into v_creador from public.proyectos p where p.id = v_origen.proyecto_id;
        select m.rol into v_rol
        from public.proyecto_miembros m
        where m.proyecto_id = v_origen.proyecto_id
          and m.usuario_id = p_usuario_id;
    end if;

    -- Sin estimación o sin pertenecer al proyecto: no se revela que existe.
    if v_origen.id is null
       or p_usuario_id is null
       or (v_rol is null and v_creador is distinct from p_usuario_id) then
        raise exception 'Estimación no encontrada'
            using errcode = 'P0002';
    end if;

    if v_creador is distinct from p_usuario_id and v_rol not in ('propietario', 'editor') then
        raise exception 'Tu permiso en este proyecto no permite actualizar la cotización.'
            using errcode = '42501';
    end if;

    -- Solo la vigente: copiar una antigua la haría pasar por la última.
    select e.id into v_ultima
    from public.estimaciones e
    where e.proyecto_id = v_origen.proyecto_id
    order by e.fecha_creacion desc, e.id desc
    limit 1;

    if v_ultima is distinct from v_origen.id then
        raise exception 'Solo se puede actualizar la cotización de la estimación más reciente.'
            using errcode = '55000';
    end if;

    if v_observaciones is not distinct from v_origen.observaciones then
        raise exception 'La observación no cambió.'
            using errcode = '55000';
    end if;

    insert into public.estimaciones (
        proyecto_id, usuario_id,
        version_precio_id, version_precio, fuente_version_precio,
        comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones,
        parametros_snapshot, version_motor,
        aplicar_factores, factor_comuna, factor_pisos, factor_ajuste,
        costo_directo_base, costo_directo, gastos_generales_pct, gastos_generales,
        utilidad_pct, utilidad, costo_total, costo_m2,
        partidas_calculadas, partidas_sin_precio, partidas_sin_cantidad,
        firma_partidas, completa, observaciones,
        plazo_dias, plazo_min_dias, plazo_max_dias, plazo_metodo, plazo_provisional,
        plazo_estado, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha
    )
    values (
        v_origen.proyecto_id, p_usuario_id,
        v_origen.version_precio_id, v_origen.version_precio, v_origen.fuente_version_precio,
        v_origen.comuna, v_origen.tipo_obra, v_origen.materialidad, v_origen.superficie_m2,
        v_origen.numero_pisos, v_origen.estandar_terminaciones,
        v_origen.parametros_snapshot, v_origen.version_motor,
        v_origen.aplicar_factores, v_origen.factor_comuna, v_origen.factor_pisos, v_origen.factor_ajuste,
        v_origen.costo_directo_base, v_origen.costo_directo, v_origen.gastos_generales_pct, v_origen.gastos_generales,
        v_origen.utilidad_pct, v_origen.utilidad, v_origen.costo_total, v_origen.costo_m2,
        v_origen.partidas_calculadas, v_origen.partidas_sin_precio, v_origen.partidas_sin_cantidad,
        v_origen.firma_partidas, v_origen.completa, v_observaciones,
        v_origen.plazo_dias, v_origen.plazo_min_dias, v_origen.plazo_max_dias, v_origen.plazo_metodo,
        v_origen.plazo_provisional, v_origen.plazo_estado, v_origen.plazo_motivo, v_origen.version_modelo,
        v_origen.tipo_obra_modelo, v_origen.uf_valor, v_origen.uf_fecha
    )
    returning * into v_estimacion;

    insert into public.estimacion_partidas (
        estimacion_id, proyecto_partida_id, partida_id, orden, origen,
        codigo_partida, nombre_partida, unidad, observacion,
        categoria_id, categoria_codigo, categoria_nombre, categoria_orden,
        estado, cantidad,
        precio_unitario_banco, precio_unitario_override, precio_unitario_usado, fuente_precio,
        factor_aplicado, subtotal_base, subtotal
    )
    select
        v_estimacion.id, l.proyecto_partida_id, l.partida_id, l.orden, l.origen,
        l.codigo_partida, l.nombre_partida, l.unidad, l.observacion,
        l.categoria_id, l.categoria_codigo, l.categoria_nombre, l.categoria_orden,
        l.estado, l.cantidad,
        l.precio_unitario_banco, l.precio_unitario_override, l.precio_unitario_usado, l.fuente_precio,
        l.factor_aplicado, l.subtotal_base, l.subtotal
    from public.estimacion_partidas l
    where l.estimacion_id = v_origen.id;

    return v_estimacion;
end;
$$;

revoke execute on function public.actualizar_cotizacion(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.actualizar_cotizacion(uuid, uuid, text) to service_role;


-- PostgREST vuelve a leer el esquema (tablas, columnas y funciones nuevas).
notify pgrst, 'reload schema';
