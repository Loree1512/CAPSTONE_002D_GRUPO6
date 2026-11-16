-- Verifica la migración 006_observaciones_estimacion.sql contra una base real.

begin;

set local plpgsql.check_asserts = on;


-- 1. Columna, función y privilegios

do $$
begin
    assert exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'estimaciones'
          and column_name = 'observaciones' and is_nullable = 'YES' and data_type = 'text'
    ), 'FALLO: falta estimaciones.observaciones opcional';

    assert has_function_privilege('service_role', 'public.actualizar_cotizacion(uuid, uuid, text)', 'execute')
       and not has_function_privilege('authenticated', 'public.actualizar_cotizacion(uuid, uuid, text)', 'execute')
       and not has_function_privilege('anon', 'public.actualizar_cotizacion(uuid, uuid, text)', 'execute'),
        'FALLO: privilegios de actualizar_cotizacion';
    assert has_function_privilege('service_role', 'public.crear_estimacion(uuid, jsonb, jsonb)', 'execute')
       and not has_function_privilege('authenticated', 'public.crear_estimacion(uuid, jsonb, jsonb)', 'execute'),
        'FALLO: privilegios de crear_estimacion';

    -- Las estimaciones siguen sin políticas de escritura.
    assert not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'estimaciones' and cmd <> 'SELECT'
    ), 'FALLO: estimaciones tiene políticas de escritura';
end;
$$;


-- 2. Datos de prueba
-- a: propietario. e: editor. l: lector. z: ajeno.

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000006a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-006-a@buildcast.test'),
    ('00000000-0000-4000-a000-0000000006a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-006-e@buildcast.test'),
    ('00000000-0000-4000-a000-0000000006a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-006-l@buildcast.test'),
    ('00000000-0000-4000-a000-0000000006a4', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-006-z@buildcast.test');

insert into public.categorias_partida (id, codigo, nombre, orden)
values (990006, 'V6', 'Verificar 006', 990006);

insert into public.versiones_precios (id, version)
values ('00000000-0000-4000-c000-0000000006c2', 'verificar-006');

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000006b1', '00000000-0000-4000-a000-0000000006a1', 'Verificar 006', 'Quilpué',
     'Verificar 006', 'Verificar 006', 48, 1, 'economico');

insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
values
    ('00000000-0000-4000-b000-0000000006b1', '00000000-0000-4000-a000-0000000006a2', 'editor'),
    ('00000000-0000-4000-b000-0000000006b1', '00000000-0000-4000-a000-0000000006a3', 'lector');

select set_config('verificar.estimacion', $json${
    "proyecto_id": "00000000-0000-4000-b000-0000000006b1",
    "version_precio_id": "00000000-0000-4000-c000-0000000006c2", "version_precio": "verificar-006",
    "comuna": "Quilpué", "tipo_obra": "Verificar 006", "materialidad": "Verificar 006",
    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "economico",
    "parametros_snapshot": {}, "version_motor": "verificar-006",
    "aplicar_factores": false, "factor_comuna": 1, "factor_pisos": 1, "factor_ajuste": 1,
    "costo_directo_base": 1000, "costo_directo": 1000, "gastos_generales_pct": 10, "gastos_generales": 100,
    "utilidad_pct": 10, "utilidad": 100, "costo_total": 1200, "costo_m2": 25,
    "partidas_calculadas": 1, "partidas_sin_precio": 0, "partidas_sin_cantidad": 0,
    "firma_partidas": "verificar-006", "completa": true
}$json$, true);

select set_config('verificar.lineas', $json$[{
    "orden": 1, "origen": "manual", "nombre_partida": "Uno", "unidad": "gl",
    "categoria_id": 990006, "categoria_codigo": "V6", "categoria_nombre": "Verificar 006", "categoria_orden": 990006,
    "estado": "calculada", "cantidad": 1, "precio_unitario_override": 1000, "precio_unitario_usado": 1000,
    "factor_aplicado": 1, "subtotal_base": 1000, "subtotal": 1000
}]$json$, true);


-- 3. Observación vacía y con contenido

set local role service_role;

do $$
declare
    v_estimacion jsonb := current_setting('verificar.estimacion')::jsonb;
    v_lineas jsonb := current_setting('verificar.lineas')::jsonb;
    v_creada public.estimaciones;
begin
    -- Sin observación.
    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000006a1', v_estimacion, v_lineas);
    assert v_creada.observaciones is null, 'FALLO: estimación sin observación';

    -- Solo espacios cuenta como vacía.
    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000006a1',
                                        v_estimacion || '{"observaciones": "   "}', v_lineas);
    assert v_creada.observaciones is null, 'FALLO: una observación en blanco se guardó';

    -- Con contenido; el HTML se guarda como texto, sin interpretar.
    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000006a2',
        v_estimacion || jsonb_build_object('observaciones',
            E'Valor preliminar sujeto a revisión.\n<script>alert(1)</script>'), v_lineas);
    assert v_creada.observaciones = E'Valor preliminar sujeto a revisión.\n<script>alert(1)</script>',
        'FALLO: la observación no se guardó tal cual';

    -- Más de 1000 caracteres: rechazada.
    begin
        perform public.crear_estimacion('00000000-0000-4000-a000-0000000006a1',
            v_estimacion || jsonb_build_object('observaciones', repeat('x', 1001)), v_lineas);
        raise exception 'FALLO: se aceptó una observación de 1001 caracteres';
    exception when check_violation then null;
    end;

    -- 1000 justos: aceptada.
    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000006a1',
        v_estimacion || jsonb_build_object('observaciones', repeat('x', 1000)), v_lineas);
    assert char_length(v_creada.observaciones) = 1000, 'FALLO: 1000 caracteres';
end;
$$;

reset role;


-- 4. Persistencia histórica y actualizar cotización
-- En otro proyecto, para que la original sea su única estimación.

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000006b2', '00000000-0000-4000-a000-0000000006a1', 'Verificar 006 · histórico',
     'Quilpué', 'Verificar 006', 'Verificar 006', 48, 1, 'economico');

insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
values
    ('00000000-0000-4000-b000-0000000006b2', '00000000-0000-4000-a000-0000000006a2', 'editor'),
    ('00000000-0000-4000-b000-0000000006b2', '00000000-0000-4000-a000-0000000006a3', 'lector');

set local role service_role;

do $$
declare
    v_estimacion jsonb := current_setting('verificar.estimacion')::jsonb
        || '{"proyecto_id": "00000000-0000-4000-b000-0000000006b2"}';
    v_lineas jsonb := current_setting('verificar.lineas')::jsonb;
    v_original public.estimaciones;
begin
    v_original := public.crear_estimacion('00000000-0000-4000-a000-0000000006a1',
        v_estimacion || '{"observaciones": "Sujeto a confirmación de terreno."}', v_lineas);
    perform set_config('verificar.original', v_original.id::text, true);

    -- La emitida no cambia su observación, ni siquiera con service role.
    begin
        update public.estimaciones set observaciones = 'Otra' where id = v_original.id;
        raise exception 'FALLO: se modificó la observación de una estimación emitida';
    exception when sqlstate '55000' or insufficient_privilege then null;
    end;

    -- El lector y el ajeno no actualizan la cotización.
    begin
        perform public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a3', v_original.id, 'Lector');
        raise exception 'FALLO: un lector actualizó la cotización';
    exception when sqlstate '42501' then null;
    end;
    begin
        perform public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a4', v_original.id, 'Ajeno');
        raise exception 'FALLO: un ajeno actualizó la cotización';
    exception when sqlstate 'P0002' then null;
    end;

    -- Misma observación: no crea otra estimación.
    begin
        perform public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a2', v_original.id,
                                             ' Sujeto a confirmación de terreno. ');
        raise exception 'FALLO: se copió una estimación sin cambiar la observación';
    exception when sqlstate '55000' then null;
    end;
end;
$$;

reset role;

-- En una transacción now() no avanza: la original se marca como anterior.
update public.estimaciones set fecha_creacion = fecha_creacion - interval '1 hour'
where proyecto_id = '00000000-0000-4000-b000-0000000006b2';

set local role service_role;

do $$
declare
    v_original public.estimaciones;
    v_copia public.estimaciones;
begin
    select * into v_original from public.estimaciones where id = current_setting('verificar.original')::uuid;

    -- El editor la cambia: nueva estimación con los mismos montos y líneas.
    v_copia := public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a2', v_original.id,
                                            'Incluye revisión de especialidades.');
    assert v_copia.id <> v_original.id, 'FALLO: no se creó una estimación nueva';
    assert v_copia.observaciones = 'Incluye revisión de especialidades.', 'FALLO: observación de la copia';
    assert v_copia.usuario_id = '00000000-0000-4000-a000-0000000006a2', 'FALLO: autor de la copia';
    assert (v_copia.costo_total, v_copia.costo_m2, v_copia.firma_partidas, v_copia.version_precio_id,
            v_copia.gastos_generales_pct, v_copia.utilidad_pct, v_copia.comuna, v_copia.superficie_m2)
         = (v_original.costo_total, v_original.costo_m2, v_original.firma_partidas, v_original.version_precio_id,
            v_original.gastos_generales_pct, v_original.utilidad_pct, v_original.comuna, v_original.superficie_m2),
        'FALLO: la copia cambió montos, firma o datos del proyecto';
    assert (select count(*) from public.estimacion_partidas where estimacion_id = v_copia.id)
         = (select count(*) from public.estimacion_partidas where estimacion_id = v_original.id),
        'FALLO: la copia no tiene las mismas líneas';
    assert (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000006b2') = 2,
        'FALLO: no se agregó exactamente una estimación';

    -- La histórica conserva su observación.
    assert (select observaciones from public.estimaciones where id = v_original.id) = 'Sujeto a confirmación de terreno.',
        'FALLO: la estimación histórica perdió su observación';

    -- La original ya no es la más reciente.
    begin
        perform public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a1', v_original.id, 'Otra');
        raise exception 'FALLO: se actualizó una estimación que no es la más reciente';
    exception when sqlstate '55000' then null;
    end;

    -- Vaciar la observación también es un cambio válido.
    v_copia := public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a1', v_copia.id, '');
    assert v_copia.observaciones is null, 'FALLO: no se pudo dejar la observación vacía';
end;
$$;

reset role;


-- 5. Un usuario no ejecuta las RPC directamente

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000006a1","role":"authenticated"}', true);

do $$
begin
    begin
        perform public.actualizar_cotizacion('00000000-0000-4000-a000-0000000006a1', gen_random_uuid(), 'x');
        raise exception 'FALLO: authenticated ejecuta actualizar_cotizacion';
    exception when insufficient_privilege then null;
    end;

    -- El lector y el propietario ven la observación (RLS de lectura de la 003).
    assert exists (select 1 from public.estimaciones
                   where proyecto_id = '00000000-0000-4000-b000-0000000006b1' and observaciones is not null),
        'FALLO: el propietario no ve las observaciones';
end;
$$;

reset role;


-- Nada de lo anterior queda en la base.
rollback;
