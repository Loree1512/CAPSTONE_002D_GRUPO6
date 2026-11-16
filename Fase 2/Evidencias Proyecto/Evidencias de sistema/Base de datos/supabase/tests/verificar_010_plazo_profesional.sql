-- Verifica la migración 010_plazo_profesional.sql contra una base de prueba.
-- Requiere la 009 aplicada (versión v1.0-2026-11-01 registrada). Termina en rollback:
-- no deja datos. No ejecutar contra producción.

begin;

set local plpgsql.check_asserts = on;


-- 1. Estructura y datos históricos

do $$
begin
    assert exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'estimaciones'
          and column_name = 'plazo_profesional_estado' and is_nullable = 'NO'
          and column_default like '''sin_definir''%'
    ), 'FALLO: plazo_profesional_estado no es not null con default sin_definir';

    assert (select count(*) from information_schema.columns
            where table_schema = 'public' and table_name = 'estimaciones'
              and column_name in ('plazo_profesional_dias', 'plazo_profesional_estado', 'plazo_profesional_origen',
                                  'plazo_profesional_fecha', 'plazo_profesional_usuario_id')) = 5,
        'FALLO: faltan columnas del plazo profesional';

    -- Las columnas de la 009 siguen con su nombre.
    assert (select count(*) from information_schema.columns
            where table_schema = 'public' and table_name = 'estimaciones'
              and column_name in ('plazo_dias', 'plazo_min_dias', 'plazo_max_dias', 'plazo_metodo',
                                  'plazo_provisional', 'plazo_estado', 'plazo_fuera_dominio', 'plazo_motivo',
                                  'version_modelo', 'tipo_obra_modelo', 'uf_valor', 'uf_fecha')) = 12,
        'FALLO: se perdió o renombró una columna de la 009';

    -- Ninguna fila histórica recibió un plazo profesional inventado.
    assert not exists (
        select 1 from public.estimaciones
        where plazo_profesional_estado = 'sin_definir'
          and (plazo_profesional_dias is not null or plazo_profesional_origen is not null
               or plazo_profesional_fecha is not null or plazo_profesional_usuario_id is not null)
    ), 'FALLO: estimación sin_definir con datos del profesional';

    assert has_function_privilege('service_role', 'public.definir_plazo_profesional(uuid, uuid, integer, text)', 'execute')
       and not has_function_privilege('authenticated', 'public.definir_plazo_profesional(uuid, uuid, integer, text)', 'execute')
       and not has_function_privilege('anon', 'public.definir_plazo_profesional(uuid, uuid, integer, text)', 'execute'),
        'FALLO: privilegios de definir_plazo_profesional';
end;
$$;


-- 2. Datos de prueba

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000010a1', '00000000-0000-0000-0000-000000000000', 'authenticated',
     'authenticated', 'verificar-010-propietario@buildcast.test'),
    ('00000000-0000-4000-a000-0000000010a2', '00000000-0000-0000-0000-000000000000', 'authenticated',
     'authenticated', 'verificar-010-editor@buildcast.test'),
    ('00000000-0000-4000-a000-0000000010a3', '00000000-0000-0000-0000-000000000000', 'authenticated',
     'authenticated', 'verificar-010-lector@buildcast.test'),
    ('00000000-0000-4000-a000-0000000010a4', '00000000-0000-0000-0000-000000000000', 'authenticated',
     'authenticated', 'verificar-010-ajeno@buildcast.test');

insert into public.categorias_partida (id, codigo, nombre, orden)
values (990010, 'V10', 'Verificar 010', 990010);

insert into public.versiones_precios (id, version)
values ('00000000-0000-4000-c000-0000000010c1', 'verificar-010');

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000010b1', '00000000-0000-4000-a000-0000000010a1', 'Verificar 010', 'Quilpué',
     'Ampliación', 'Verificar 010', 48, 1, 'economico');

insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
values
    ('00000000-0000-4000-b000-0000000010b1', '00000000-0000-4000-a000-0000000010a2', 'editor'),
    ('00000000-0000-4000-b000-0000000010b1', '00000000-0000-4000-a000-0000000010a3', 'lector')
on conflict do nothing;

select set_config('verificar.estimacion', $json${
    "proyecto_id": "00000000-0000-4000-b000-0000000010b1",
    "version_precio_id": "00000000-0000-4000-c000-0000000010c1", "version_precio": "verificar-010",
    "comuna": "Quilpué", "tipo_obra": "Ampliación", "materialidad": "Verificar 010",
    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "economico",
    "parametros_snapshot": {}, "version_motor": "verificar-010",
    "aplicar_factores": false, "factor_comuna": 1, "factor_pisos": 1, "factor_ajuste": 1,
    "costo_directo_base": 1000, "costo_directo": 1000, "gastos_generales_pct": 10, "gastos_generales": 100,
    "utilidad_pct": 10, "utilidad": 100, "costo_total": 1200, "costo_m2": 25,
    "partidas_calculadas": 1, "partidas_sin_precio": 0, "partidas_sin_cantidad": 0,
    "firma_partidas": "verificar-010", "completa": true
}$json$, true);

select set_config('verificar.plazo', $json${
    "plazo_dias": 120, "plazo_min_dias": 85, "plazo_max_dias": 170, "plazo_metodo": "P2",
    "plazo_provisional": true, "plazo_estado": "dentro_dominio", "version_modelo": "v1.0-2026-11-01",
    "tipo_obra_modelo": "ampliacion", "uf_valor": 41263.57, "uf_fecha": "2026-11-03"
}$json$, true);

select set_config('verificar.lineas', $json$[{
    "orden": 1, "origen": "manual", "nombre_partida": "Uno", "unidad": "gl",
    "categoria_id": 990010, "categoria_codigo": "V10", "categoria_nombre": "Verificar 010", "categoria_orden": 990010,
    "estado": "calculada", "cantidad": 1, "precio_unitario_override": 1000, "precio_unitario_usado": 1000,
    "factor_aplicado": 1, "subtotal_base": 1000, "subtotal": 1000
}]$json$, true);


-- 3. Reglas, con los permisos del backend (service_role)
-- now() es fijo en la transacción: antes de cada paso se envejecen las estimaciones
-- anteriores para que la recién creada sea la más reciente. La función temporal se crea
-- con el rol del script y se ejecuta con los permisos de quien la llama (service_role).

create or replace function pg_temp.envejecer(p_vigente uuid)
returns void
language sql
as $$
    update public.estimaciones set fecha_creacion = fecha_creacion - interval '1 hour'
    where proyecto_id = '00000000-0000-4000-b000-0000000010b1' and id <> p_vigente;
$$;

set local role service_role;

do $$
declare
    v_prop uuid := '00000000-0000-4000-a000-0000000010a1';
    v_editor uuid := '00000000-0000-4000-a000-0000000010a2';
    v_lector uuid := '00000000-0000-4000-a000-0000000010a3';
    v_ajeno uuid := '00000000-0000-4000-a000-0000000010a4';
    v_est jsonb := current_setting('verificar.estimacion')::jsonb;
    v_plazo jsonb := current_setting('verificar.plazo')::jsonb;
    v_lin jsonb := current_setting('verificar.lineas')::jsonb;
    v_primera public.estimaciones;
    v_definida public.estimaciones;
    v_copia public.estimaciones;
    v_recalculada public.estimaciones;
    v_otra public.estimaciones;
    v_sin_sugerencia public.estimaciones;
begin
    assert current_user = 'service_role', 'FALLO: la sección 3 debe correr como service_role';

    -- Estimación nueva: sugerencia del modelo, pero el plazo profesional sin definir.
    -- Un payload con plazo_profesional_* se ignora.
    v_primera := public.crear_estimacion(v_prop, v_est || v_plazo
        || '{"plazo_profesional_dias": 999, "plazo_profesional_estado": "definido", "plazo_profesional_origen": "manual"}',
        v_lin);
    assert v_primera.plazo_dias = 120, 'FALLO: no se guardó la sugerencia del modelo';
    assert v_primera.plazo_profesional_estado = 'sin_definir' and v_primera.plazo_profesional_dias is null
       and v_primera.plazo_profesional_origen is null and v_primera.plazo_profesional_fecha is null
       and v_primera.plazo_profesional_usuario_id is null,
        'FALLO: crear_estimacion tomó el plazo profesional del payload';

    -- Lector: 42501. Ajeno o estimación inexistente: P0002.
    begin
        perform public.definir_plazo_profesional(v_lector, v_primera.id, 135, 'manual');
        raise exception 'FALLO: un lector definió el plazo';
    exception when insufficient_privilege then null;
    end;
    begin
        perform public.definir_plazo_profesional(v_ajeno, v_primera.id, 135, 'manual');
        raise exception 'FALLO: alguien ajeno definió el plazo';
    exception when sqlstate 'P0002' then null;
    end;
    begin
        perform public.definir_plazo_profesional(v_prop, gen_random_uuid(), 135, 'manual');
        raise exception 'FALLO: se definió el plazo de una estimación inexistente';
    exception when sqlstate 'P0002' then null;
    end;

    -- Valores inválidos: 22023.
    begin
        perform public.definir_plazo_profesional(v_editor, v_primera.id, 0, 'manual');
        raise exception 'FALLO: se aceptó un plazo de 0 días';
    exception when sqlstate '22023' then null;
    end;
    begin
        perform public.definir_plazo_profesional(v_editor, v_primera.id, 135, 'modelo');
        raise exception 'FALLO: se aceptó un origen desconocido';
    exception when sqlstate '22023' then null;
    end;

    -- Plazo manual del editor: estimación nueva, la anterior no cambia.
    v_definida := public.definir_plazo_profesional(v_editor, v_primera.id, 135, 'manual');
    assert v_definida.id <> v_primera.id, 'FALLO: no se creó una estimación nueva';
    assert (v_definida.plazo_profesional_dias, v_definida.plazo_profesional_estado, v_definida.plazo_profesional_origen,
            v_definida.plazo_profesional_usuario_id) = (135, 'definido', 'manual', v_editor)
       and v_definida.plazo_profesional_fecha is not null,
        'FALLO: plazo profesional manual';
    assert (v_definida.plazo_dias, v_definida.plazo_min_dias, v_definida.plazo_max_dias, v_definida.version_modelo,
            v_definida.costo_total)
         = (v_primera.plazo_dias, v_primera.plazo_min_dias, v_primera.plazo_max_dias, v_primera.version_modelo,
            v_primera.costo_total),
        'FALLO: definir el plazo cambió la sugerencia o el costo';
    assert (select count(*) from public.estimacion_partidas where estimacion_id = v_definida.id) = 1,
        'FALLO: no se copiaron las líneas';
    assert (select plazo_profesional_estado from public.estimaciones where id = v_primera.id) = 'sin_definir',
        'FALLO: cambió la estimación anterior';
    perform pg_temp.envejecer(v_definida.id);

    -- Solo la más reciente.
    begin
        perform public.definir_plazo_profesional(v_editor, v_primera.id, 140, 'manual');
        raise exception 'FALLO: se definió el plazo de una estimación antigua';
    exception when sqlstate '55000' then null;
    end;

    -- Mismo valor ya definido: 55000.
    begin
        perform public.definir_plazo_profesional(v_editor, v_definida.id, 135, 'manual');
        raise exception 'FALLO: se aceptó un plazo sin cambios';
    exception when sqlstate '55000' then null;
    end;

    -- Usar la sugerencia: el valor sale de plazo_dias de la fila, no de p_dias.
    v_otra := public.definir_plazo_profesional(v_prop, v_definida.id, 1, 'sugerencia');
    assert (v_otra.plazo_profesional_dias, v_otra.plazo_profesional_origen) = (120, 'sugerencia'),
        'FALLO: usar sugerencia';
    perform pg_temp.envejecer(v_otra.id);

    -- Actualizar cotización copia el plazo profesional tal cual.
    v_copia := public.actualizar_cotizacion(v_editor, v_otra.id, 'Nota');
    assert (v_copia.plazo_profesional_dias, v_copia.plazo_profesional_estado, v_copia.plazo_profesional_origen,
            v_copia.plazo_profesional_fecha, v_copia.plazo_profesional_usuario_id)
         = (v_otra.plazo_profesional_dias, v_otra.plazo_profesional_estado, v_otra.plazo_profesional_origen,
            v_otra.plazo_profesional_fecha, v_otra.plazo_profesional_usuario_id),
        'FALLO: actualizar_cotizacion no copió el plazo profesional';
    perform pg_temp.envejecer(v_copia.id);

    -- Recalcular: nueva sugerencia y el plazo profesional queda por revisar, sin borrarse.
    v_recalculada := public.crear_estimacion(v_prop, v_est || v_plazo || '{"plazo_dias": 130, "plazo_max_dias": 180}',
                                             v_lin);
    assert v_recalculada.plazo_dias = 130, 'FALLO: no se guardó la nueva sugerencia';
    assert (v_recalculada.plazo_profesional_dias, v_recalculada.plazo_profesional_estado,
            v_recalculada.plazo_profesional_origen, v_recalculada.plazo_profesional_usuario_id)
         = (120, 'por_revisar', 'sugerencia', v_prop),
        'FALLO: recalcular no dejó el plazo profesional por revisar';
    perform pg_temp.envejecer(v_recalculada.id);

    -- Confirmar el mismo valor sí se permite: sale de por revisar.
    v_otra := public.definir_plazo_profesional(v_editor, v_recalculada.id, 120, 'manual');
    assert v_otra.plazo_profesional_estado = 'definido', 'FALLO: confirmar un plazo por revisar';
    perform pg_temp.envejecer(v_otra.id);

    -- Sin sugerencia del modelo: usar sugerencia falla; manual funciona.
    v_sin_sugerencia := public.crear_estimacion(v_prop, v_est, v_lin);
    perform pg_temp.envejecer(v_sin_sugerencia.id);
    assert v_sin_sugerencia.plazo_dias is null and v_sin_sugerencia.plazo_profesional_estado = 'por_revisar',
        'FALLO: estimación sin sugerencia';
    begin
        perform public.definir_plazo_profesional(v_editor, v_sin_sugerencia.id, null, 'sugerencia');
        raise exception 'FALLO: se usó una sugerencia inexistente';
    exception when sqlstate '55000' then null;
    end;

    -- Inmutabilidad: el plazo profesional de una estimación emitida no se edita (trigger).
    begin
        update public.estimaciones set plazo_profesional_dias = 10 where id = v_primera.id;
        raise exception 'FALLO: se modificó el plazo profesional de una estimación emitida';
    exception when sqlstate '55000' then null;
    end;
    begin
        update public.estimaciones set plazo_profesional_estado = 'definido' where id = v_primera.id;
        raise exception 'FALLO: se cambió el estado del plazo profesional de una estimación emitida';
    exception when sqlstate '55000' then null;
    end;
end;
$$;


-- 4. Restricciones e inmutabilidad independientes de las RPC
-- Se vuelve al rol del script (dueño de las tablas), para que el único freno sea la
-- restricción o el trigger.

reset role;

do $$
declare
    v_editor uuid := '00000000-0000-4000-a000-0000000010a2';
    v_id uuid;
begin
    assert current_user <> 'service_role', 'FALLO: la sección 4 no debe correr como service_role';

    -- El check de coherencia rechaza un definido sin días al insertar.
    begin
        insert into public.estimaciones (
            proyecto_id, version_precio_id, version_precio, comuna, tipo_obra, materialidad, superficie_m2,
            numero_pisos, estandar_terminaciones, parametros_snapshot, version_motor, aplicar_factores,
            factor_comuna, factor_pisos, factor_ajuste, costo_directo_base, costo_directo, gastos_generales_pct,
            gastos_generales, utilidad_pct, utilidad, costo_total, costo_m2, partidas_calculadas,
            partidas_sin_precio, partidas_sin_cantidad, firma_partidas, completa, plazo_profesional_estado)
        values (
            '00000000-0000-4000-b000-0000000010b1', '00000000-0000-4000-c000-0000000010c1', 'verificar-010',
            'Quilpué', 'Ampliación', 'Verificar 010', 48, 1, 'economico', '{}', 'verificar-010', false,
            1, 1, 1, 1000, 1000, 10, 100, 10, 100, 1200, 25, 1, 0, 0, 'verificar-010', true, 'definido');
        raise exception 'FALLO: se aceptó un plazo profesional definido sin días';
    exception when check_violation then null;
    end;

    -- Eliminar la cuenta de quien definió el plazo: la decisión se conserva sin autor.
    select id into v_id from public.estimaciones
    where plazo_profesional_usuario_id = v_editor
    order by fecha_creacion desc limit 1;
    assert v_id is not null, 'FALLO: no hay una estimación definida por el editor';

    delete from auth.users where id = v_editor;

    assert exists (
        select 1 from public.estimaciones
        where id = v_id and plazo_profesional_usuario_id is null and plazo_profesional_estado = 'definido'
          and plazo_profesional_dias is not null
    ), 'FALLO: al eliminar la cuenta se perdió la decisión o no quedó sin autor';
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
