-- Verifica la migración 002_roles_permisos_auditoria.sql contra una base real.
--
-- Uso: aplicar antes la 002 y ejecutar este archivo completo en el SQL Editor de
-- Supabase (rol postgres) o con psql. Todo corre dentro de BEGIN … ROLLBACK: crea
-- tres usuarios y tres proyectos de prueba y no deja nada.
--
-- Resultado: si termina sin error, todas las comprobaciones pasaron. La primera que
-- falla corta la ejecución con un mensaje "FALLO: …" (o el error de Postgres).
--
-- Vale mientras no se aplique la 003: el paso 2 espera las políticas RLS de la 001.

begin;

-- Los ASSERT deben estar activos durante toda la prueba.
set local plpgsql.check_asserts = on;


-- 1. Privilegios y definición de funciones -------------------------------------------

do $$
declare
    v_tabla text;
    v_funcion text;
begin
    foreach v_tabla in array array['perfiles', 'proyecto_miembros', 'historial_proyecto'] loop
        assert (select relrowsecurity from pg_class where oid = ('public.' || v_tabla)::regclass),
            'FALLO: RLS desactivado en ' || v_tabla;

        assert not has_table_privilege('anon', 'public.' || v_tabla, 'select, insert, update, delete, truncate, references, trigger'),
            'FALLO: anon tiene privilegios sobre ' || v_tabla;

        assert has_table_privilege('authenticated', 'public.' || v_tabla, 'select'),
            'FALLO: authenticated no puede leer ' || v_tabla;
        assert not has_table_privilege('authenticated', 'public.' || v_tabla, 'insert, update, delete, truncate, references, trigger'),
            'FALLO: authenticated puede escribir en ' || v_tabla;

        assert has_table_privilege('service_role', 'public.' || v_tabla, 'select')
           and has_table_privilege('service_role', 'public.' || v_tabla, 'insert'),
            'FALLO: service_role no puede leer o insertar en ' || v_tabla;
        assert not has_table_privilege('service_role', 'public.' || v_tabla, 'truncate, references, trigger'),
            'FALLO: service_role tiene privilegios de más sobre ' || v_tabla;
    end loop;

    -- perfiles: sin delete. proyecto_miembros: todo. historial_proyecto: solo anexar.
    assert has_table_privilege('service_role', 'public.perfiles', 'update')
       and not has_table_privilege('service_role', 'public.perfiles', 'delete'),
        'FALLO: privilegios de service_role en perfiles';
    assert has_table_privilege('service_role', 'public.proyecto_miembros', 'update')
       and has_table_privilege('service_role', 'public.proyecto_miembros', 'delete'),
        'FALLO: privilegios de service_role en proyecto_miembros';
    assert not has_table_privilege('service_role', 'public.historial_proyecto', 'update, delete'),
        'FALLO: service_role puede modificar historial_proyecto';

    foreach v_funcion in array array[
        'public.rol_en_proyecto(uuid)', 'public.tiene_rol_proyecto(uuid, text[])', 'public.es_administrador()',
        'public.crear_perfil_usuario()', 'public.agregar_propietario_proyecto()',
        'public.proteger_miembros_proyecto()', 'public.bloquear_cambios_historial()'
    ] loop
        assert (select prosecdef from pg_proc where oid = v_funcion::regprocedure),
            'FALLO: no es security definer: ' || v_funcion;
        assert (select proconfig from pg_proc where oid = v_funcion::regprocedure) @> array['search_path=""'],
            'FALLO: sin search_path vacío: ' || v_funcion;
        assert not has_function_privilege('anon', v_funcion, 'execute'),
            'FALLO: anon puede ejecutar ' || v_funcion;
    end loop;

    foreach v_funcion in array array[
        'public.rol_en_proyecto(uuid)', 'public.tiene_rol_proyecto(uuid, text[])', 'public.es_administrador()'
    ] loop
        assert has_function_privilege('authenticated', v_funcion, 'execute')
           and has_function_privilege('service_role', v_funcion, 'execute'),
            'FALLO: falta execute en ' || v_funcion;
    end loop;

    foreach v_funcion in array array[
        'public.crear_perfil_usuario()', 'public.agregar_propietario_proyecto()',
        'public.proteger_miembros_proyecto()', 'public.bloquear_cambios_historial()'
    ] loop
        assert not has_function_privilege('authenticated', v_funcion, 'execute'),
            'FALLO: authenticated puede ejecutar ' || v_funcion;
    end loop;
end;
$$;


-- 2. La 002 no cambió las políticas de la 001 ------------------------------------------

do $$
begin
    assert (select array_agg(policyname::text order by policyname) from pg_policies
            where schemaname = 'public' and tablename = 'proyectos')
        = array['proyectos_actualizar_propios', 'proyectos_insertar_propios', 'proyectos_seleccionar_propios'],
        'FALLO: cambiaron las políticas de proyectos';

    assert (select array_agg(policyname::text order by policyname) from pg_policies
            where schemaname = 'public' and tablename = 'proyecto_partidas')
        = array['proyecto_partidas_actualizar_propias', 'proyecto_partidas_eliminar_propias',
                'proyecto_partidas_insertar_propias', 'proyecto_partidas_seleccionar_propias'],
        'FALLO: cambiaron las políticas de proyecto_partidas';

    assert (select array_agg(policyname::text order by policyname) from pg_policies
            where schemaname = 'public' and tablename in ('estimaciones', 'estimacion_partidas'))
        = array['estimacion_partidas_seleccionar_propias', 'estimaciones_seleccionar_propias'],
        'FALLO: cambiaron las políticas de estimaciones';
end;
$$;


-- 3. Backfill sobre los datos reales -----------------------------------------------------

do $$
declare
    v_perfiles bigint;
    v_miembros bigint;
begin
    assert not exists (
        select 1 from auth.users u
        where not exists (select 1 from public.perfiles p where p.id = u.id)
    ), 'FALLO: hay usuarios sin perfil';

    assert not exists (
        select 1 from public.proyectos p
        where p.usuario_id is not null
          and not exists (
              select 1 from public.proyecto_miembros m
              where m.proyecto_id = p.id and m.usuario_id = p.usuario_id and m.rol = 'propietario'
          )
    ), 'FALLO: hay proyectos cuyo creador no es propietario';

    -- Repetir el backfill no duplica.
    select count(*) into v_perfiles from public.perfiles;
    select count(*) into v_miembros from public.proyecto_miembros;

    insert into public.perfiles (id, email)
    select u.id, u.email from auth.users u
    on conflict (id) do nothing;

    insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
    select p.id, p.usuario_id, 'propietario' from public.proyectos p
    where p.usuario_id is not null
    on conflict (proyecto_id, usuario_id) do nothing;

    assert (select count(*) from public.perfiles) = v_perfiles
       and (select count(*) from public.proyecto_miembros) = v_miembros,
        'FALLO: el backfill no es repetible';
end;
$$;


-- 4. Datos de prueba ---------------------------------------------------------------------
-- Usuarios A, B y C (…a1, …a2, …a3). Proyectos P1 (de A), P2 (de B) y P3 (de A, creado
-- con su token).

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000000a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-002-a@buildcast.test'),
    ('00000000-0000-4000-a000-0000000000a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-002-b@buildcast.test'),
    ('00000000-0000-4000-a000-0000000000a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-002-c@buildcast.test');

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000000b1', '00000000-0000-4000-a000-0000000000a1', 'Verificar 002 · P1', 'Quilpué', 'Ampliación', 'Estructura metálica', 48, 1, 'economico'),
    ('00000000-0000-4000-b000-0000000000b2', '00000000-0000-4000-a000-0000000000a2', 'Verificar 002 · P2', 'Quilpué', 'Ampliación', 'Estructura metálica', 48, 1, 'economico');


-- 5. Perfil automático -------------------------------------------------------------------

do $$
begin
    assert (select count(*) from public.perfiles
            where id in ('00000000-0000-4000-a000-0000000000a1', '00000000-0000-4000-a000-0000000000a2',
                         '00000000-0000-4000-a000-0000000000a3')
              and rol_global = 'profesional'
              and email like 'verificar-002-%@buildcast.test') = 3,
        'FALLO: el registro no creó los perfiles como profesional';

    update auth.users set email = 'verificar-002-c2@buildcast.test'
    where id = '00000000-0000-4000-a000-0000000000a3';

    assert (select email from public.perfiles where id = '00000000-0000-4000-a000-0000000000a3')
        = 'verificar-002-c2@buildcast.test',
        'FALLO: el perfil no siguió el cambio de correo';
end;
$$;


-- 6. Propietario automático ----------------------------------------------------------------

-- A crea P3 con su token: la política de la 001 lo permite y el trigger lo hace propietario
-- aunque authenticated no pueda escribir en proyecto_miembros.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a1","role":"authenticated"}', true);

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000000b3', '00000000-0000-4000-a000-0000000000a1', 'Verificar 002 · P3', 'Quilpué', 'Ampliación', 'Estructura metálica', 48, 1, 'economico');

reset role;

do $$
begin
    assert (select count(*) from public.proyecto_miembros m
            join public.proyectos p on p.id = m.proyecto_id
            where p.id in ('00000000-0000-4000-b000-0000000000b1', '00000000-0000-4000-b000-0000000000b2',
                           '00000000-0000-4000-b000-0000000000b3')
              and m.usuario_id = p.usuario_id
              and m.agregado_por = p.usuario_id
              and m.rol = 'propietario') = 3,
        'FALLO: el creador no quedó como propietario';
end;
$$;


-- 7. Miembros con service role (como el backend) ----------------------------------------------

set local role service_role;

-- B editor y C lector en P1.
insert into public.proyecto_miembros (proyecto_id, usuario_id, rol, agregado_por)
values
    ('00000000-0000-4000-b000-0000000000b1', '00000000-0000-4000-a000-0000000000a2', 'editor', '00000000-0000-4000-a000-0000000000a1'),
    ('00000000-0000-4000-b000-0000000000b1', '00000000-0000-4000-a000-0000000000a3', 'lector', '00000000-0000-4000-a000-0000000000a1');

do $$
begin
    -- Un solo propietario por proyecto.
    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000000b2', '00000000-0000-4000-a000-0000000000a3', 'propietario');
        raise exception 'FALLO: se aceptó un segundo propietario';
    exception when unique_violation then null;
    end;

    -- Un usuario, una sola fila por proyecto.
    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000000b1', '00000000-0000-4000-a000-0000000000a2', 'lector');
        raise exception 'FALLO: se aceptó un miembro duplicado';
    exception when unique_violation then null;
    end;

    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000000b2', '00000000-0000-4000-a000-0000000000a3', 'administrador');
        raise exception 'FALLO: se aceptó un rol de proyecto inválido';
    exception when check_violation then null;
    end;

    -- El propietario no se degrada ni se quita.
    begin
        update public.proyecto_miembros set rol = 'editor'
        where proyecto_id = '00000000-0000-4000-b000-0000000000b1' and rol = 'propietario';
        raise exception 'FALLO: se degradó al propietario';
    exception when object_not_in_prerequisite_state then null;
    end;

    begin
        delete from public.proyecto_miembros
        where proyecto_id = '00000000-0000-4000-b000-0000000000b1' and rol = 'propietario';
        raise exception 'FALLO: se quitó al propietario';
    exception when object_not_in_prerequisite_state then null;
    end;

    -- Una fila no cambia de usuario.
    begin
        update public.proyecto_miembros set usuario_id = '00000000-0000-4000-a000-0000000000a3'
        where proyecto_id = '00000000-0000-4000-b000-0000000000b2' and rol = 'propietario';
        raise exception 'FALLO: una fila de miembro cambió de usuario';
    exception when object_not_in_prerequisite_state then null;
    end;

    -- Los demás sí cambian de permiso (y vuelven a como estaban).
    update public.proyecto_miembros set rol = 'lector'
    where proyecto_id = '00000000-0000-4000-b000-0000000000b1' and usuario_id = '00000000-0000-4000-a000-0000000000a2';
    update public.proyecto_miembros set rol = 'editor'
    where proyecto_id = '00000000-0000-4000-b000-0000000000b1' and usuario_id = '00000000-0000-4000-a000-0000000000a2';

    -- service_role no borra perfiles ni toca el historial.
    begin
        delete from public.perfiles where id = '00000000-0000-4000-a000-0000000000a3';
        raise exception 'FALLO: service_role borró un perfil';
    exception when insufficient_privilege then null;
    end;
end;
$$;

-- Un evento de historial, como lo escribirá el backend.
insert into public.historial_proyecto
    (id, proyecto_id, usuario_id, usuario_email, accion, entidad, entidad_id, valores_nuevos)
values
    ('00000000-0000-4000-c000-0000000000c1', '00000000-0000-4000-b000-0000000000b1',
     '00000000-0000-4000-a000-0000000000a1', 'verificar-002-a@buildcast.test',
     'miembro_agregado', 'miembro', '00000000-0000-4000-a000-0000000000a2', '{"rol": "editor"}');

do $$
begin
    assert (select origen from public.historial_proyecto where id = '00000000-0000-4000-c000-0000000000c1') = 'api',
        'FALLO: origen por defecto del historial';

    begin
        update public.historial_proyecto set accion = 'otra' where id = '00000000-0000-4000-c000-0000000000c1';
        raise exception 'FALLO: service_role modificó el historial';
    exception when insufficient_privilege then null;
    end;

    begin
        delete from public.historial_proyecto where id = '00000000-0000-4000-c000-0000000000c1';
        raise exception 'FALLO: service_role borró el historial';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;

-- Tampoco con el dueño de la tabla: lo impide el trigger.
do $$
begin
    begin
        update public.historial_proyecto set accion = 'otra' where id = '00000000-0000-4000-c000-0000000000c1';
        raise exception 'FALLO: se modificó el historial';
    exception when object_not_in_prerequisite_state then null;
    end;

    begin
        delete from public.historial_proyecto where id = '00000000-0000-4000-c000-0000000000c1';
        raise exception 'FALLO: se borró el historial';
    exception when object_not_in_prerequisite_state then null;
    end;

    begin
        insert into public.historial_proyecto (proyecto_id, accion, entidad, origen)
        values ('00000000-0000-4000-b000-0000000000b1', 'x', 'proyecto', 'manual');
        raise exception 'FALLO: se aceptó un origen inválido';
    exception when check_violation then null;
    end;
end;
$$;


-- 8. RLS y funciones con el token de A (propietario de P1 y P3) ----------------------------------

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a1","role":"authenticated"}', true);

do $$
begin
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b1') = 'propietario',
        'FALLO: rol de A en P1';
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b2') is null,
        'FALLO: A no es miembro de P2';
    assert public.tiene_rol_proyecto('00000000-0000-4000-b000-0000000000b1', array['propietario', 'editor']),
        'FALLO: tiene_rol_proyecto de A en P1';
    assert not public.tiene_rol_proyecto('00000000-0000-4000-b000-0000000000b1', array['lector']),
        'FALLO: tiene_rol_proyecto no distingue roles';
    assert not public.tiene_rol_proyecto('00000000-0000-4000-b000-0000000000b2', array['propietario', 'editor', 'lector']),
        'FALLO: tiene_rol_proyecto de A en P2';
    assert not public.es_administrador(),
        'FALLO: A es administrador sin haber sido promovido';

    -- Solo su perfil.
    assert (select array_agg(id) from public.perfiles) = array['00000000-0000-4000-a000-0000000000a1'::uuid],
        'FALLO: A ve perfiles ajenos (o no ve el suyo)';

    -- Miembros de sus proyectos (3 en P1, 1 en P3), no los de P2.
    assert (select count(*) from public.proyecto_miembros) = 4
       and not exists (select 1 from public.proyecto_miembros
                       where proyecto_id = '00000000-0000-4000-b000-0000000000b2'),
        'FALLO: miembros visibles para A';

    assert (select count(*) from public.historial_proyecto) = 1,
        'FALLO: A no ve el historial de su proyecto';

    -- Nada de esto se escribe con el token del usuario.
    begin
        update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000000a1';
        raise exception 'FALLO: un usuario cambió su propio rol';
    exception when insufficient_privilege then null;
    end;

    begin
        insert into public.perfiles (id) values ('00000000-0000-4000-a000-0000000000a9');
        raise exception 'FALLO: authenticated insertó un perfil';
    exception when insufficient_privilege then null;
    end;

    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000000b2', '00000000-0000-4000-a000-0000000000a1', 'editor');
        raise exception 'FALLO: un usuario se agregó a un proyecto ajeno';
    exception when insufficient_privilege then null;
    end;

    begin
        update public.proyecto_miembros set rol = 'lector' where usuario_id = '00000000-0000-4000-a000-0000000000a2';
        raise exception 'FALLO: authenticated cambió un permiso';
    exception when insufficient_privilege then null;
    end;

    begin
        delete from public.proyecto_miembros where usuario_id = '00000000-0000-4000-a000-0000000000a3';
        raise exception 'FALLO: authenticated quitó un miembro';
    exception when insufficient_privilege then null;
    end;

    begin
        insert into public.historial_proyecto (proyecto_id, accion, entidad)
        values ('00000000-0000-4000-b000-0000000000b1', 'x', 'proyecto');
        raise exception 'FALLO: authenticated escribió en el historial';
    exception when insufficient_privilege then null;
    end;
end;
$$;


-- 9. Con el token de C (lector en P1) y de B (editor en P1, propietario de P2) -------------------

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a3","role":"authenticated"}', true);

do $$
begin
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b1') = 'lector',
        'FALLO: rol de C en P1';
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b3') is null,
        'FALLO: C no es miembro de P3';
    -- Ve a los 3 miembros de P1 y su historial; nada de P2 ni P3.
    assert (select count(*) from public.proyecto_miembros) = 3,
        'FALLO: miembros visibles para C';
    assert (select count(*) from public.historial_proyecto) = 1,
        'FALLO: un miembro lector no ve el historial';
end;
$$;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a2","role":"authenticated"}', true);

do $$
begin
    -- Un mismo usuario con distinto permiso en cada proyecto.
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b1') = 'editor'
       and public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b2') = 'propietario',
        'FALLO: roles de B';
    assert (select count(*) from public.proyecto_miembros) = 4,
        'FALLO: miembros visibles para B';
end;
$$;

reset role;


-- 10. Sin sesión (anon) ----------------------------------------------------------------------

set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);

do $$
begin
    begin
        perform 1 from public.perfiles;
        raise exception 'FALLO: anon lee perfiles';
    exception when insufficient_privilege then null;
    end;

    begin
        perform 1 from public.proyecto_miembros;
        raise exception 'FALLO: anon lee proyecto_miembros';
    exception when insufficient_privilege then null;
    end;

    begin
        perform 1 from public.historial_proyecto;
        raise exception 'FALLO: anon lee historial_proyecto';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.es_administrador();
        raise exception 'FALLO: anon ejecuta es_administrador';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b1');
        raise exception 'FALLO: anon ejecuta rol_en_proyecto';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;


-- 11. Promoción a administrador (manual, en la base) ----------------------------------------------

update public.perfiles set rol_global = 'administrador'
where id = '00000000-0000-4000-a000-0000000000a1';

do $$
begin
    begin
        update public.perfiles set rol_global = 'superusuario' where id = '00000000-0000-4000-a000-0000000000a2';
        raise exception 'FALLO: se aceptó un rol global inválido';
    exception when check_violation then null;
    end;
end;
$$;

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a1","role":"authenticated"}', true);

do $$
begin
    assert public.es_administrador(), 'FALLO: A no es administrador tras la promoción';
    -- Ser administrador no da acceso a proyectos ajenos.
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000000b2') is null
       and not exists (select 1 from public.proyecto_miembros
                       where proyecto_id = '00000000-0000-4000-b000-0000000000b2'),
        'FALLO: el administrador ve un proyecto del que no es miembro';
end;
$$;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000000a2","role":"authenticated"}', true);

do $$
begin
    assert not public.es_administrador(), 'FALLO: B es administrador';
end;
$$;

reset role;


-- 12. Borrados en cascada -------------------------------------------------------------------------

do $$
begin
    -- Quitar a un miembro que no es propietario.
    delete from public.proyecto_miembros
    where proyecto_id = '00000000-0000-4000-b000-0000000000b1' and usuario_id = '00000000-0000-4000-a000-0000000000a3';

    -- Borrar el proyecto se lleva miembros (incluido el propietario) e historial.
    delete from public.proyectos where id = '00000000-0000-4000-b000-0000000000b1';

    assert not exists (select 1 from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000000b1'),
        'FALLO: quedaron miembros de un proyecto borrado';
    assert not exists (select 1 from public.historial_proyecto where proyecto_id = '00000000-0000-4000-b000-0000000000b1'),
        'FALLO: quedó historial de un proyecto borrado';

    -- Borrar la cuenta de B (propietario de P2): se van su perfil y su membresía;
    -- el proyecto queda, sin creador ni propietario.
    delete from auth.users where id = '00000000-0000-4000-a000-0000000000a2';

    assert not exists (select 1 from public.perfiles where id = '00000000-0000-4000-a000-0000000000a2'),
        'FALLO: quedó el perfil de una cuenta borrada';
    assert not exists (select 1 from public.proyecto_miembros where usuario_id = '00000000-0000-4000-a000-0000000000a2'),
        'FALLO: quedó la membresía de una cuenta borrada';
    assert (select usuario_id is null from public.proyectos where id = '00000000-0000-4000-b000-0000000000b2'),
        'FALLO: el proyecto de una cuenta borrada no quedó sin usuario_id';

    -- A sigue siendo propietario de P3.
    assert (select rol from public.proyecto_miembros
            where proyecto_id = '00000000-0000-4000-b000-0000000000b3'
              and usuario_id = '00000000-0000-4000-a000-0000000000a1') = 'propietario',
        'FALLO: A perdió su proyecto';
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
