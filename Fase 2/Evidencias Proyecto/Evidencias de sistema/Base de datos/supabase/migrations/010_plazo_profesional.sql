-- 010: plazo para la cotización, definido por el profesional.
--
-- El modelo de plazo (009) sugiere; el profesional decide. Las columnas plazo_* de la
-- 009 siguen siendo el snapshot de la sugerencia del modelo y no se renombran. Este
-- archivo agrega, aparte, el plazo que define el profesional y que muestra el documento
-- de entrega. El plazo real ejecutado es otro dato (obras_ejecutadas, otra HU).
--
-- Datos históricos: todas las filas existentes quedan 'sin_definir', con lo demás en
-- null. No se copia plazo_dias a plazo_profesional_dias: la sugerencia del modelo no se
-- convierte en decisión del profesional sin una acción explícita.


-- 1. Columnas

alter table public.estimaciones
    add column plazo_profesional_dias integer
        constraint estimaciones_plazo_profesional_dias_chk
        check (plazo_profesional_dias is null or plazo_profesional_dias between 1 and 3650),
    -- sin_definir: el profesional aún no decide. definido: decidió sobre esta estimación.
    -- por_revisar: decidió sobre una anterior y el costo se recalculó después.
    add column plazo_profesional_estado text not null default 'sin_definir'
        constraint estimaciones_plazo_profesional_estado_valor_chk
        check (plazo_profesional_estado in ('sin_definir', 'definido', 'por_revisar')),
    -- sugerencia: aceptó el plazo del modelo. manual: escribió otro valor.
    add column plazo_profesional_origen text
        constraint estimaciones_plazo_profesional_origen_chk
        check (plazo_profesional_origen is null or plazo_profesional_origen in ('sugerencia', 'manual')),
    add column plazo_profesional_fecha timestamptz,
    -- Igual que usuario_id: si se elimina la cuenta, la decisión se conserva sin autor.
    add column plazo_profesional_usuario_id uuid
        references auth.users(id) on delete set null;

alter table public.estimaciones
    add constraint estimaciones_plazo_profesional_estado_chk check (
        case
            when plazo_profesional_estado = 'sin_definir' then
                plazo_profesional_dias is null and plazo_profesional_origen is null
                and plazo_profesional_fecha is null and plazo_profesional_usuario_id is null
            else
                -- usuario_id puede quedar en null por el on delete set null.
                plazo_profesional_dias is not null and plazo_profesional_origen is not null
                and plazo_profesional_fecha is not null
        end
    );


-- 2. El snapshot sigue siendo inmutable, también en el plazo profesional
-- Igual que en la 009, más las columnas plazo_profesional_*. La única excepción es que
-- plazo_profesional_usuario_id pase a null: lo hace el on delete set null de la FK al
-- eliminar una cuenta, y no cambia el significado de la decisión.

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
    if (new.plazo_profesional_dias, new.plazo_profesional_estado, new.plazo_profesional_origen,
        new.plazo_profesional_fecha)
       is distinct from
       (old.plazo_profesional_dias, old.plazo_profesional_estado, old.plazo_profesional_origen,
        old.plazo_profesional_fecha)
       or (new.plazo_profesional_usuario_id is distinct from old.plazo_profesional_usuario_id
           and new.plazo_profesional_usuario_id is not null) then
        raise exception 'El plazo para la cotización de una estimación emitida no se modifica; se define en una estimación nueva.'
            using errcode = '55000';
    end if;
    return new;
end;
$$;

revoke execute on function public.bloquear_cambio_plazo() from public, anon, authenticated, service_role;


-- 3. crear_estimacion: el plazo profesional nunca viene del payload
-- Igual que en la 009. Además lee la estimación más reciente del proyecto:
--   - si su plazo profesional estaba definido o por revisar, la nueva queda 'por_revisar'
--     y conserva valor, origen, fecha y autor (no se borra en silencio);
--   - si no, la nueva queda 'sin_definir'.
-- Cualquier plazo_profesional_* que llegue en p_estimacion se ignora.

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
    v_previa public.estimaciones;
    v_conserva boolean;
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

    -- La decisión del profesional sobre la estimación que esta reemplaza.
    select e.* into v_previa
    from public.estimaciones e
    where e.proyecto_id = v_proyecto_id
    order by e.fecha_creacion desc, e.id desc
    limit 1;

    v_conserva := coalesce(v_previa.plazo_profesional_estado in ('definido', 'por_revisar'), false);

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
        plazo_estado, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha,
        plazo_profesional_dias, plazo_profesional_estado, plazo_profesional_origen,
        plazo_profesional_fecha, plazo_profesional_usuario_id
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
        r.version_modelo, r.tipo_obra_modelo, r.uf_valor, r.uf_fecha,
        -- Del proyecto, no del payload.
        case when v_conserva then v_previa.plazo_profesional_dias end,
        case when v_conserva then 'por_revisar' else 'sin_definir' end,
        case when v_conserva then v_previa.plazo_profesional_origen end,
        case when v_conserva then v_previa.plazo_profesional_fecha end,
        case when v_conserva then v_previa.plazo_profesional_usuario_id end
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


-- 4. actualizar_cotizacion copia también el plazo profesional
-- Igual que en la 009: solo cambia la observación. El plazo del modelo y el del
-- profesional (valor, estado, origen, fecha y autor) se copian tal cual.

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
        plazo_estado, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha,
        plazo_profesional_dias, plazo_profesional_estado, plazo_profesional_origen,
        plazo_profesional_fecha, plazo_profesional_usuario_id
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
        v_origen.tipo_obra_modelo, v_origen.uf_valor, v_origen.uf_fecha,
        v_origen.plazo_profesional_dias, v_origen.plazo_profesional_estado, v_origen.plazo_profesional_origen,
        v_origen.plazo_profesional_fecha, v_origen.plazo_profesional_usuario_id
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


-- 5. definir_plazo_profesional
-- Acción explícita del profesional. Como actualizar_cotizacion: crea una estimación
-- nueva que copia la vigente (montos, líneas, observación y plazo del modelo) y solo
-- cambia el plazo profesional, que queda 'definido'. No ejecuta el modelo ni toca las
-- columnas de la 009.
--   p_origen = 'sugerencia': el valor es el plazo_dias de esa estimación (falla si es null);
--                            p_dias se ignora.
--   p_origen = 'manual':     el valor es p_dias (1 a 3650).

create or replace function public.definir_plazo_profesional(
    p_usuario_id uuid,
    p_estimacion_id uuid,
    p_dias integer,
    p_origen text
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
    v_dias integer;
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

    -- Mismo permiso que generar o actualizar: propietario o editor. El lector solo lee.
    if v_creador is distinct from p_usuario_id and v_rol not in ('propietario', 'editor') then
        raise exception 'Tu permiso en este proyecto no permite definir el plazo para la cotización.'
            using errcode = '42501';
    end if;

    -- Solo la vigente: el documento de entrega sale de la más reciente.
    select e.id into v_ultima
    from public.estimaciones e
    where e.proyecto_id = v_origen.proyecto_id
    order by e.fecha_creacion desc, e.id desc
    limit 1;

    if v_ultima is distinct from v_origen.id then
        raise exception 'Solo se puede definir el plazo de la estimación más reciente.'
            using errcode = '55000';
    end if;

    if p_origen is null or p_origen not in ('sugerencia', 'manual') then
        raise exception 'El origen del plazo debe ser sugerencia o manual.'
            using errcode = '22023';
    end if;

    if p_origen = 'sugerencia' then
        v_dias := v_origen.plazo_dias;
        if v_dias is null then
            raise exception 'Esta estimación no tiene un plazo sugerido por el modelo.'
                using errcode = '55000';
        end if;
    else
        v_dias := p_dias;
        if v_dias is null or v_dias not between 1 and 3650 then
            raise exception 'El plazo debe ser un número entero de días entre 1 y 3650.'
                using errcode = '22023';
        end if;
    end if;

    -- Confirmar un plazo por revisar con el mismo valor sí es un cambio (de estado).
    if v_origen.plazo_profesional_estado = 'definido' and v_origen.plazo_profesional_dias = v_dias then
        raise exception 'El plazo para la cotización no cambió.'
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
        plazo_estado, plazo_motivo, version_modelo, tipo_obra_modelo, uf_valor, uf_fecha,
        plazo_profesional_dias, plazo_profesional_estado, plazo_profesional_origen,
        plazo_profesional_fecha, plazo_profesional_usuario_id
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
        v_origen.firma_partidas, v_origen.completa, v_origen.observaciones,
        v_origen.plazo_dias, v_origen.plazo_min_dias, v_origen.plazo_max_dias, v_origen.plazo_metodo,
        v_origen.plazo_provisional, v_origen.plazo_estado, v_origen.plazo_motivo, v_origen.version_modelo,
        v_origen.tipo_obra_modelo, v_origen.uf_valor, v_origen.uf_fecha,
        v_dias, 'definido', p_origen, now(), p_usuario_id
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

revoke execute on function public.definir_plazo_profesional(uuid, uuid, integer, text) from public, anon, authenticated;
grant execute on function public.definir_plazo_profesional(uuid, uuid, integer, text) to service_role;


-- PostgREST vuelve a leer el esquema (columnas y función nuevas).
notify pgrst, 'reload schema';
