-- Verifica la migración 009_plazo_estimaciones.sql contra una base real.
-- Termina en rollback: no deja datos.

begin;

set local plpgsql.check_asserts = on;


-- 1. Estructura y privilegios

do $$
begin
    assert (select relrowsecurity from pg_class where oid = 'public.valores_uf'::regclass),
        'FALLO: RLS desactivada en valores_uf';
    assert (select relrowsecurity from pg_class where oid = 'public.versiones_modelo'::regclass),
        'FALLO: RLS desactivada en versiones_modelo';
    assert has_table_privilege('authenticated', 'public.valores_uf', 'select')
       and not has_table_privilege('authenticated', 'public.valores_uf', 'insert, update, delete'),
        'FALLO: authenticated escribe valores_uf';
    assert not has_table_privilege('anon', 'public.valores_uf', 'select')
       and not has_table_privilege('anon', 'public.versiones_modelo', 'select'),
        'FALLO: anon lee valores_uf o versiones_modelo';
    assert has_table_privilege('service_role', 'public.valores_uf', 'insert')
       and not has_table_privilege('service_role', 'public.valores_uf', 'delete'),
        'FALLO: privilegios de service_role sobre valores_uf';
    assert not has_table_privilege('authenticated', 'public.versiones_modelo', 'insert, update, delete'),
        'FALLO: authenticated escribe versiones_modelo';

    assert (select count(*) from public.versiones_modelo where vigente and objetivo = 'plazo') = 1,
        'FALLO: no hay exactamente una versión vigente del modelo de plazo';
    assert exists (
        select 1 from public.versiones_modelo
        where version = 'v1.0-2026-11-01' and metodo = 'P2' and estado = 'provisional'
          and (dominio ->> 'costo_uf_min')::numeric = 14.56 and (dominio ->> 'costo_uf_max')::numeric = 438.95
          and (parametros -> 'parametros' ->> 'beta')::float8 = 0.8901844312875308
    ), 'FALLO: la versión v1.0-2026-11-01 no quedó registrada con su dominio y parámetros';

    assert (select attgenerated from pg_attribute
            where attrelid = 'public.estimaciones'::regclass and attname = 'plazo_fuera_dominio') = 's',
        'FALLO: plazo_fuera_dominio no es columna generada';
    assert not exists (select 1 from public.estimaciones where plazo_estado is null),
        'FALLO: hay estimaciones sin plazo_estado';
    assert not exists (
        select 1 from public.estimaciones
        where plazo_estado = 'no_disponible' and plazo_dias is not null
    ), 'FALLO: estimación no_disponible con plazo';
end;
$$;


-- 2. Datos de prueba

insert into auth.users (id, instance_id, aud, role, email)
values ('00000000-0000-4000-a000-0000000009a1', '00000000-0000-0000-0000-000000000000', 'authenticated',
        'authenticated', 'verificar-009-a@buildcast.test');

insert into public.categorias_partida (id, codigo, nombre, orden)
values (990009, 'V9', 'Verificar 009', 990009);

insert into public.versiones_precios (id, version)
values ('00000000-0000-4000-c000-0000000009c1', 'verificar-009');

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000009b1', '00000000-0000-4000-a000-0000000009a1', 'Verificar 009', 'Quilpué',
     'Ampliación', 'Verificar 009', 48, 1, 'economico');

-- Fecha fuera de la serie real de la CMF para no chocar con datos cargados.
insert into public.valores_uf (fecha, valor, fuente)
values ('1999-01-01', 1.00, 'verificar-009');

select set_config('verificar.estimacion', $json${
    "proyecto_id": "00000000-0000-4000-b000-0000000009b1",
    "version_precio_id": "00000000-0000-4000-c000-0000000009c1", "version_precio": "verificar-009",
    "comuna": "Quilpué", "tipo_obra": "Ampliación", "materialidad": "Verificar 009",
    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "economico",
    "parametros_snapshot": {}, "version_motor": "verificar-009",
    "aplicar_factores": false, "factor_comuna": 1, "factor_pisos": 1, "factor_ajuste": 1,
    "costo_directo_base": 1000, "costo_directo": 1000, "gastos_generales_pct": 10, "gastos_generales": 100,
    "utilidad_pct": 10, "utilidad": 100, "costo_total": 1200, "costo_m2": 25,
    "partidas_calculadas": 1, "partidas_sin_precio": 0, "partidas_sin_cantidad": 0,
    "firma_partidas": "verificar-009", "completa": true
}$json$, true);

select set_config('verificar.plazo', $json${
    "plazo_dias": 41, "plazo_min_dias": 19, "plazo_max_dias": 209, "plazo_metodo": "P2",
    "plazo_provisional": true, "plazo_estado": "dentro_dominio", "version_modelo": "v1.0-2026-11-01",
    "tipo_obra_modelo": "ampliacion", "uf_valor": 41263.57, "uf_fecha": "2026-11-03"
}$json$, true);

select set_config('verificar.lineas', $json$[{
    "orden": 1, "origen": "manual", "nombre_partida": "Uno", "unidad": "gl",
    "categoria_id": 990009, "categoria_codigo": "V9", "categoria_nombre": "Verificar 009", "categoria_orden": 990009,
    "estado": "calculada", "cantidad": 1, "precio_unitario_override": 1000, "precio_unitario_usado": 1000,
    "factor_aplicado": 1, "subtotal_base": 1000, "subtotal": 1000
}]$json$, true);


-- 3. Reglas, con los permisos del backend (service_role)

set local role service_role;

do $$
declare
    v_a uuid := '00000000-0000-4000-a000-0000000009a1';
    v_est jsonb := current_setting('verificar.estimacion')::jsonb;
    v_plazo jsonb := current_setting('verificar.plazo')::jsonb;
    v_lin jsonb := current_setting('verificar.lineas')::jsonb;
    v_creada public.estimaciones;
    v_copia public.estimaciones;
begin
    assert current_user = 'service_role', 'FALLO: la sección 3 debe correr como service_role';

    -- Con plazo: se guarda tal cual y queda dentro del dominio.
    v_creada := public.crear_estimacion(v_a, v_est || v_plazo, v_lin);
    assert (v_creada.plazo_dias, v_creada.plazo_min_dias, v_creada.plazo_max_dias) = (41, 19, 209),
        'FALLO: plazo no guardado';
    assert v_creada.version_modelo = 'v1.0-2026-11-01' and v_creada.plazo_fuera_dominio = false,
        'FALLO: versión o dominio';

    -- Sin datos de plazo (backend anterior): la estimación se guarda igual.
    v_copia := public.crear_estimacion(v_a, v_est, v_lin);
    assert v_copia.plazo_estado = 'no_disponible' and v_copia.plazo_dias is null and v_copia.plazo_fuera_dominio,
        'FALLO: estimación sin plazo';

    -- Orden min ≤ plazo ≤ max.
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"plazo_min_dias": 50}', v_lin);
        raise exception 'FALLO: se aceptó min > plazo';
    exception when check_violation then null;
    end;
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"plazo_min_dias": 0, "plazo_dias": 0}', v_lin);
        raise exception 'FALLO: se aceptó un plazo de 0 días';
    exception when check_violation then null;
    end;

    -- Estado desconocido, no_disponible con días, o UF incompleta: rechazados.
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"plazo_estado": "confiable"}', v_lin);
        raise exception 'FALLO: se aceptó un estado desconocido';
    exception when check_violation then null;
    end;
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"plazo_estado": "no_disponible"}', v_lin);
        raise exception 'FALLO: no_disponible con días';
    exception when check_violation then null;
    end;
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"uf_fecha": null}', v_lin);
        raise exception 'FALLO: UF sin fecha';
    exception when check_violation then null;
    end;

    -- Versión no registrada: FK.
    begin
        perform public.crear_estimacion(v_a, v_est || v_plazo || '{"version_modelo": "v9.9-2099-01-01"}', v_lin);
        raise exception 'FALLO: se aceptó una versión no registrada';
    exception when foreign_key_violation then null;
    end;

    -- Actualizar cotización copia el plazo exacto. now() es fijo en la transacción:
    -- se envejecen las anteriores para que esta sea la más reciente.
    v_creada := public.crear_estimacion(v_a, v_est || v_plazo, v_lin);
    update public.estimaciones set fecha_creacion = fecha_creacion - interval '1 hour'
    where proyecto_id = '00000000-0000-4000-b000-0000000009b1' and id <> v_creada.id;
    v_copia := public.actualizar_cotizacion(v_a, v_creada.id, 'Nueva nota');
    assert (v_copia.plazo_dias, v_copia.plazo_min_dias, v_copia.plazo_max_dias, v_copia.plazo_metodo,
            v_copia.plazo_estado, v_copia.version_modelo, v_copia.uf_valor, v_copia.uf_fecha, v_copia.tipo_obra_modelo)
         = (v_creada.plazo_dias, v_creada.plazo_min_dias, v_creada.plazo_max_dias, v_creada.plazo_metodo,
            v_creada.plazo_estado, v_creada.version_modelo, v_creada.uf_valor, v_creada.uf_fecha,
            v_creada.tipo_obra_modelo),
        'FALLO: actualizar_cotizacion no copió el plazo';

    -- El plazo emitido no se modifica.
    begin
        update public.estimaciones set plazo_dias = 99 where id = v_creada.id;
        raise exception 'FALLO: se modificó el plazo de una estimación emitida';
    exception when sqlstate '55000' then null;
    end;
    begin
        update public.estimaciones set version_modelo = null, plazo_estado = 'no_disponible',
            plazo_dias = null, plazo_min_dias = null, plazo_max_dias = null where id = v_creada.id;
        raise exception 'FALLO: se cambió la versión de una estimación emitida';
    exception when sqlstate '55000' then null;
    end;

    -- La versión publicada no cambia sus parámetros, pero sí su estado y observaciones.
    -- service_role tiene UPDATE: el rechazo viene del trigger.
    begin
        update public.versiones_modelo set parametros = '{}' where version = 'v1.0-2026-11-01';
        raise exception 'FALLO: se modificaron los parámetros de una versión publicada';
    exception when sqlstate '55000' then null;
    end;
    update public.versiones_modelo set observaciones = 'verificar-009' where version = 'v1.0-2026-11-01';

    -- Primera capa: el backend no tiene DELETE. El rechazo debe ser por permisos (42501),
    -- antes de llegar al trigger. El trigger se prueba aparte, en la sección 4.
    begin
        delete from public.versiones_modelo where version = 'v1.0-2026-11-01';
        raise exception 'FALLO: service_role borró una versión publicada';
    exception when insufficient_privilege then null;
    end;

    -- Una segunda versión vigente choca con la actual.
    begin
        insert into public.versiones_modelo (version, metodo, algoritmo, entrenado_en, estado, vigente, parametros, dominio)
        values ('v9.9-2099-01-01', 'P2', 'parametrica', '2099-01-01', 'provisional', true, '{}', '{}');
        raise exception 'FALLO: dos versiones vigentes';
    exception when unique_violation then null;
    end;

    -- valores_uf: sin valores no positivos.
    begin
        insert into public.valores_uf (fecha, valor, fuente) values ('1999-01-02', 0, 'verificar-009');
        raise exception 'FALLO: se aceptó una UF de 0';
    exception when check_violation then null;
    end;
end;
$$;


-- 4. Inmutabilidad independiente de los permisos
-- Se vuelve al rol que ejecuta el script (dueño de las tablas en el SQL Editor), que sí
-- puede borrar: así el único freno es el trigger. Se usa una versión de prueba sin
-- estimaciones asociadas para que la FK (on delete restrict) no tape un trigger ausente.

reset role;

insert into public.versiones_modelo (version, metodo, algoritmo, entrenado_en, estado, vigente, parametros, dominio)
values ('v9.8-2099-01-01', 'P2', 'parametrica', '2099-01-01', 'retirado', false, '{}', '{}');

do $$
begin
    assert current_user <> 'service_role', 'FALLO: la sección 4 no debe correr como service_role';
    assert has_table_privilege(current_user, 'public.versiones_modelo', 'delete'),
        'FALLO: el rol del script no puede borrar; la prueba del trigger no sería concluyente';

    -- Sin referencias ni restricción de permisos: solo el trigger lo impide (55000).
    begin
        delete from public.versiones_modelo where version = 'v9.8-2099-01-01';
        raise exception 'FALLO: se borró una versión publicada (el trigger no la protege)';
    exception when sqlstate '55000' then null;
    end;

    -- Tampoco la vigente, aunque tenga estimaciones: el trigger actúa antes que la FK.
    begin
        delete from public.versiones_modelo where version = 'v1.0-2026-11-01';
        raise exception 'FALLO: se borró la versión vigente';
    exception when sqlstate '55000' then null;
    end;

    assert (select count(*) from public.versiones_modelo
            where version in ('v1.0-2026-11-01', 'v9.8-2099-01-01')) = 2,
        'FALLO: falta una versión después de los intentos de borrado';

    -- Ni un cambio de parámetros por el dueño.
    begin
        update public.versiones_modelo set dominio = '{}' where version = 'v1.0-2026-11-01';
        raise exception 'FALLO: el dueño modificó el dominio de una versión publicada';
    exception when sqlstate '55000' then null;
    end;
end;
$$;


-- Nada de lo anterior queda en la base: ni la versión v9.8 de prueba ni las estimaciones.
rollback;
