-- Verifica la migración 004_eliminar_proyectos.sql contra una base real.

begin;

-- Los ASSERT deben estar activos durante toda la prueba.
set local plpgsql.check_asserts = on;


-- 1. Función, privilegios y política

do $$
begin
    assert (select prosecdef from pg_proc where oid = 'public.es_propietario_proyecto(uuid)'::regprocedure),
        'FALLO: es_propietario_proyecto no es security definer';
    assert (select proconfig from pg_proc where oid = 'public.es_propietario_proyecto(uuid)'::regprocedure)
        @> array['search_path=""'],
        'FALLO: es_propietario_proyecto sin search_path vacío';
    assert has_function_privilege('authenticated', 'public.es_propietario_proyecto(uuid)', 'execute')
       and not has_function_privilege('anon', 'public.es_propietario_proyecto(uuid)', 'execute'),
        'FALLO: privilegios de es_propietario_proyecto';

    assert has_table_privilege('authenticated', 'public.proyectos', 'delete'),
        'FALLO: authenticated no tiene privilegio delete sobre proyectos';

    assert (select array_agg(policyname::text order by policyname::text collate "C") from pg_policies
            where schemaname = 'public' and tablename = 'proyectos')
        = array['proyectos_actualizar_editores', 'proyectos_eliminar_propietario',
                'proyectos_insertar_propios', 'proyectos_seleccionar_miembros'],
        'FALLO: políticas de proyectos';

    assert (select cmd from pg_policies
            where schemaname = 'public' and tablename = 'proyectos' and policyname = 'proyectos_eliminar_propietario')
        = 'DELETE',
        'FALLO: proyectos_eliminar_propietario no es de DELETE';

    -- La política de borrado no puede apoyarse en una comprobación que incluya al editor.
    assert (select qual from pg_policies
            where schemaname = 'public' and tablename = 'proyectos' and policyname = 'proyectos_eliminar_propietario')
        not like '%puede_editar_proyecto%',
        'FALLO: la política de DELETE usa puede_editar_proyecto';

    -- Todas las FK hacia proyectos borran en cascada.
    assert (select count(*) from pg_constraint
            where contype = 'f' and confrelid = 'public.proyectos'::regclass) = 4,
        'FALLO: cambió el número de FK hacia proyectos; revisar la cascada';
    assert not exists (
        select 1 from pg_constraint
        where contype = 'f' and confrelid = 'public.proyectos'::regclass and confdeltype <> 'c'
    ), 'FALLO: una FK hacia proyectos no es on delete cascade';
end;
$$;


-- 2. Datos de prueba

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000004a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-004-a@buildcast.test'),
    ('00000000-0000-4000-a000-0000000004a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-004-b@buildcast.test'),
    ('00000000-0000-4000-a000-0000000004a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-004-c@buildcast.test'),
    ('00000000-0000-4000-a000-0000000004a4', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-004-d@buildcast.test'),
    ('00000000-0000-4000-a000-0000000004a5', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-004-e@buildcast.test');

-- Catálogo mínimo propio: no depende de los seeds.
insert into public.categorias_partida (id, codigo, nombre, orden)
values (990004, 'V4', 'Verificar 004', 990004);

insert into public.versiones_precios (id, version)
values ('00000000-0000-4000-c000-0000000004c2', 'verificar-004');

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-a000-0000000004a1', 'Verificar 004 · P1', 'Quilpué', 'Verificar 004', 'Verificar 004', 48, 1, 'economico'),
    ('00000000-0000-4000-b000-0000000004b2', '00000000-0000-4000-a000-0000000004a1', 'Verificar 004 · P2', 'Quilpué', 'Verificar 004', 'Verificar 004', 48, 1, 'economico'),
    -- P3 nace sin creador y se le asigna después: queda sin fila en proyecto_miembros.
    ('00000000-0000-4000-b000-0000000004b3', null, 'Verificar 004 · P3', 'Quilpué', 'Verificar 004', 'Verificar 004', 48, 1, 'economico');

update public.proyectos set usuario_id = '00000000-0000-4000-a000-0000000004a5'
where id = '00000000-0000-4000-b000-0000000004b3';

insert into public.proyecto_miembros (proyecto_id, usuario_id, rol, agregado_por)
values
    ('00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-a000-0000000004a2', 'editor', '00000000-0000-4000-a000-0000000004a1'),
    ('00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-a000-0000000004a3', 'lector', '00000000-0000-4000-a000-0000000004a1'),
    ('00000000-0000-4000-b000-0000000004b2', '00000000-0000-4000-a000-0000000004a2', 'lector', '00000000-0000-4000-a000-0000000004a1');

-- Una partida y un evento de historial en cada proyecto.
insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, cantidad, precio_unitario_override, origen, orden)
select p, 990004, 'Partida de prueba', 'gl', 1, 1000, 'manual', 1
from unnest(array[
    '00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-b000-0000000004b2',
    '00000000-0000-4000-b000-0000000004b3']::uuid[]) p;

insert into public.historial_proyecto (proyecto_id, accion, entidad)
select p, 'proyecto_creado', 'proyecto'
from unnest(array[
    '00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-b000-0000000004b2',
    '00000000-0000-4000-b000-0000000004b3']::uuid[]) p;

select set_config('verificar.estimacion', $json${
    "version_precio_id": "00000000-0000-4000-c000-0000000004c2", "version_precio": "verificar-004",
    "comuna": "Quilpué", "tipo_obra": "Verificar 004", "materialidad": "Verificar 004",
    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "economico",
    "parametros_snapshot": {}, "version_motor": "verificar-004",
    "aplicar_factores": false, "factor_comuna": 1, "factor_pisos": 1, "factor_ajuste": 1,
    "costo_directo_base": 1000, "costo_directo": 1000, "gastos_generales_pct": 10, "gastos_generales": 100,
    "utilidad_pct": 10, "utilidad": 100, "costo_total": 1200, "costo_m2": 25,
    "partidas_calculadas": 1, "partidas_sin_precio": 0, "partidas_sin_cantidad": 0,
    "firma_partidas": "verificar-004", "completa": true
}$json$, true);

select set_config('verificar.lineas', $json$[{
    "orden": 1, "origen": "manual", "nombre_partida": "Partida de prueba", "unidad": "gl",
    "categoria_id": 990004, "categoria_codigo": "V4", "categoria_nombre": "Verificar 004", "categoria_orden": 990004,
    "estado": "calculada", "cantidad": 1, "precio_unitario_override": 1000, "precio_unitario_usado": 1000,
    "factor_aplicado": 1, "subtotal_base": 1000, "subtotal": 1000
}]$json$, true);

-- Una estimación con su línea en cada proyecto.
do $$
declare
    v_p uuid;
begin
    foreach v_p in array array[
        '00000000-0000-4000-b000-0000000004b1', '00000000-0000-4000-b000-0000000004b2',
        '00000000-0000-4000-b000-0000000004b3']::uuid[] loop
        perform public.crear_estimacion(
            (select usuario_id from public.proyectos where id = v_p),
            current_setting('verificar.estimacion')::jsonb || jsonb_build_object('proyecto_id', v_p),
            current_setting('verificar.lineas')::jsonb);
    end loop;

    assert (select count(*) from public.estimaciones
            where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 3,
        'FALLO: faltan estimaciones de prueba';
    assert (select count(*) from public.estimacion_partidas ep
            join public.estimaciones e on e.id = ep.estimacion_id
            where e.proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 3,
        'FALLO: faltan líneas de estimación de prueba';
end;
$$;


-- 3. No borran: lector, editor y quien no pertenece
-- RLS no lanza error: el DELETE no alcanza ninguna fila.

set local role authenticated;

do $$
declare
    v_borradas integer;
    v_sub text;
begin
    foreach v_sub in array array[
        '00000000-0000-4000-a000-0000000004a3',   -- C, lector de P1
        '00000000-0000-4000-a000-0000000004a2',   -- B, editor de P1
        '00000000-0000-4000-a000-0000000004a4'    -- D, sin proyectos
    ] loop
        perform set_config('request.jwt.claims', json_build_object('sub', v_sub, 'role', 'authenticated')::text, true);

        delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b1';
        get diagnostics v_borradas = row_count;
        assert v_borradas = 0, 'FALLO: ' || v_sub || ' pudo borrar P1';
    end loop;

    -- B edita P1 (la 003 sigue vigente), pero editar no equivale a poder borrar.
    perform set_config('request.jwt.claims',
        '{"sub":"00000000-0000-4000-a000-0000000004a2","role":"authenticated"}', true);
    update public.proyectos set nombre = 'Verificar 004 · P1 editado'
    where id = '00000000-0000-4000-b000-0000000004b1';
    get diagnostics v_borradas = row_count;
    assert v_borradas = 1, 'FALLO: el editor ya no puede editar P1';

    delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b1';
    get diagnostics v_borradas = row_count;
    assert v_borradas = 0, 'FALLO: el editor pudo borrar P1 tras editarlo';

    -- B es lector en P2.
    delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b2';
    get diagnostics v_borradas = row_count;
    assert v_borradas = 0, 'FALLO: un lector de P2 pudo borrarlo';
end;
$$;

reset role;

do $$
begin
    assert (select count(*) from public.proyectos
            where id::text like '00000000-0000-4000-b000-0000000004b%') = 3,
        'FALLO: se borró un proyecto sin ser propietario';
    assert (select count(*) from public.proyecto_partidas
            where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 3
       and (select count(*) from public.estimaciones
            where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 3
       and (select count(*) from public.historial_proyecto
            where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 3
       and (select count(*) from public.proyecto_miembros
            where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 5,
        'FALLO: cambiaron datos relacionados tras intentos rechazados';
end;
$$;


-- 4. La propietaria borra P1 y se van sus datos relacionados

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000004a1","role":"authenticated"}', true);

do $$
declare
    v_borradas integer;
begin
    delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b1';
    get diagnostics v_borradas = row_count;
    assert v_borradas = 1, 'FALLO: la propietaria no pudo borrar P1';
end;
$$;

reset role;

do $$
declare
    v_p1 constant uuid := '00000000-0000-4000-b000-0000000004b1';
begin
    assert not exists (select 1 from public.proyectos where id = v_p1), 'FALLO: P1 sigue existiendo';
    assert not exists (select 1 from public.proyecto_partidas where proyecto_id = v_p1), 'FALLO: quedan partidas de P1';
    assert not exists (select 1 from public.estimaciones where proyecto_id = v_p1), 'FALLO: quedan estimaciones de P1';
    assert not exists (select 1 from public.proyecto_miembros where proyecto_id = v_p1), 'FALLO: quedan miembros de P1';
    assert not exists (select 1 from public.historial_proyecto where proyecto_id = v_p1), 'FALLO: queda historial de P1';
    assert not exists (
        select 1 from public.estimacion_partidas ep
        where not exists (select 1 from public.estimaciones e where e.id = ep.estimacion_id)
    ), 'FALLO: quedan líneas de estimación huérfanas';

    -- P2 y P3 no cambian.
    assert (select count(*) from public.proyectos where id::text like '00000000-0000-4000-b000-0000000004b%') = 2,
        'FALLO: el borrado de P1 afectó a otro proyecto';
    assert (select count(*) from public.proyecto_partidas where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 2
       and (select count(*) from public.estimaciones where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 2
       and (select count(*) from public.historial_proyecto where proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 2
       and (select count(*) from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000004b2') = 2
       and (select count(*) from public.estimacion_partidas ep
            join public.estimaciones e on e.id = ep.estimacion_id
            where e.proyecto_id::text like '00000000-0000-4000-b000-0000000004b%') = 2,
        'FALLO: el borrado de P1 afectó datos de otro proyecto';
end;
$$;


-- 5. El creador sin fila en proyecto_miembros (respaldo temporal) también borra

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000004a5","role":"authenticated"}', true);

do $$
declare
    v_borradas integer;
begin
    assert not exists (select 1 from public.proyecto_miembros
                       where proyecto_id = '00000000-0000-4000-b000-0000000004b3'),
        'FALLO: P3 debía estar sin filas de miembros';

    delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b3';
    get diagnostics v_borradas = row_count;
    assert v_borradas = 1, 'FALLO: el creador de P3 no pudo borrarlo';
end;
$$;

reset role;

do $$
begin
    assert not exists (select 1 from public.estimaciones
                       where proyecto_id = '00000000-0000-4000-b000-0000000004b3'),
        'FALLO: quedan estimaciones de P3';
end;
$$;


-- 6. Anónimo: no alcanza ninguna fila

set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);

do $$
declare
    v_borradas integer;
begin
    begin
        delete from public.proyectos where id = '00000000-0000-4000-b000-0000000004b2';
        get diagnostics v_borradas = row_count;
        assert v_borradas = 0, 'FALLO: anon borró un proyecto';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;

do $$
begin
    assert exists (select 1 from public.proyectos where id = '00000000-0000-4000-b000-0000000004b2'),
        'FALLO: P2 desapareció';
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
