-- Observaciones opcionales de la cotización, guardadas como parte del snapshot de cada
-- estimación. Una estimación emitida no cambia su observación: un cambio crea otra.


-- 1. Columna

alter table public.estimaciones
    add column observaciones text
        constraint estimaciones_observaciones_chk
        check (observaciones is null or (btrim(observaciones) <> '' and char_length(observaciones) <= 1000));

-- Las estimaciones emitidas conservan su observación.
create or replace function public.bloquear_cambio_observaciones()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.observaciones is distinct from old.observaciones then
        raise exception 'La observación de una estimación emitida no se modifica.'
            using errcode = '55000';
    end if;
    return new;
end;
$$;

revoke execute on function public.bloquear_cambio_observaciones() from public, anon, authenticated, service_role;

create trigger estimaciones_observaciones_inmutables
    before update of observaciones on public.estimaciones
    for each row
    execute function public.bloquear_cambio_observaciones();


-- 2. crear_estimacion guarda también la observación
-- Igual que en 003, más la columna observaciones.

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
        firma_partidas, completa, observaciones
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
        r.firma_partidas, r.completa, nullif(btrim(r.observaciones), '')
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


-- 3. Actualizar cotización
-- Cambia solo la observación: copia la última estimación (montos, líneas, versión y
-- firma) con la observación nueva. No pasa por el motor, así que el estado del
-- proyecto (vigente o por recalcular) no cambia.

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
        firma_partidas, completa, observaciones
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
        v_origen.firma_partidas, v_origen.completa, v_observaciones
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


-- PostgREST vuelve a leer el esquema (columna y función nuevas).
notify pgrst, 'reload schema';
