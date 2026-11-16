-- Verifica la migración 005_administracion_usuarios.sql contra una base real.
-- Funciona con el grupo de principales vacío (crea tres de prueba) o ya configurado

begin;

set local plpgsql.check_asserts = on;


-- 1. Estructura y privilegios

do $$
declare
    v_tabla text;
    v_funcion text;
begin
    foreach v_tabla in array array['administradores_principales', 'solicitudes_administrador',
                                   'aprobaciones_administrador', 'auditoria_administracion'] loop
        assert (select relrowsecurity from pg_class where oid = ('public.' || v_tabla)::regclass),
            'FALLO: RLS desactivada en ' || v_tabla;
        assert has_table_privilege('service_role', 'public.' || v_tabla, 'select'),
            'FALLO: service_role no lee ' || v_tabla;
        assert not has_table_privilege('service_role', 'public.' || v_tabla, 'insert, update, delete, truncate'),
            'FALLO: service_role escribe directo en ' || v_tabla;
        assert not has_table_privilege('anon', 'public.' || v_tabla, 'select, insert, update, delete'),
            'FALLO: anon tiene acceso a ' || v_tabla;
    end loop;

    -- authenticated solo ve su propia fila de principales; lo demás, nada.
    assert has_table_privilege('authenticated', 'public.administradores_principales', 'select'),
        'FALLO: authenticated no puede consultar si es principal';
    foreach v_tabla in array array['solicitudes_administrador', 'aprobaciones_administrador',
                                   'auditoria_administracion'] loop
        assert not has_table_privilege('authenticated', 'public.' || v_tabla, 'select, insert, update, delete'),
            'FALLO: authenticated tiene acceso a ' || v_tabla;
    end loop;

    -- El backend ya no escribe el rol global.
    assert not has_column_privilege('service_role', 'public.perfiles', 'rol_global', 'update'),
        'FALLO: service_role puede cambiar rol_global';
    assert has_column_privilege('service_role', 'public.perfiles', 'nombre', 'update'),
        'FALLO: service_role no puede actualizar el nombre';
    assert not has_table_privilege('service_role', 'public.perfiles', 'insert'),
        'FALLO: service_role inserta perfiles';

    foreach v_funcion in array array[
        'public.registrar_usuario_creado(uuid, uuid, text, text)',
        'public.solicitar_administrador(uuid, uuid)',
        'public.aprobar_solicitud_administrador(uuid, uuid)'
    ] loop
        assert (select prosecdef from pg_proc where oid = v_funcion::regprocedure),
            'FALLO: ' || v_funcion || ' no es security definer';
        assert (select proconfig from pg_proc where oid = v_funcion::regprocedure) @> array['search_path=""'],
            'FALLO: ' || v_funcion || ' sin search_path vacío';
        assert has_function_privilege('service_role', v_funcion, 'execute')
           and not has_function_privilege('authenticated', v_funcion, 'execute')
           and not has_function_privilege('anon', v_funcion, 'execute'),
            'FALLO: privilegios de ' || v_funcion;
    end loop;

    foreach v_funcion in array array[
        'public.registrar_auditoria_administracion(text, uuid, uuid, text, uuid, jsonb)',
        'public.exigir_administrador_global(uuid)'
    ] loop
        assert not has_function_privilege('service_role', v_funcion, 'execute')
           and not has_function_privilege('authenticated', v_funcion, 'execute'),
            'FALLO: ' || v_funcion || ' se puede ejecutar a mano';
    end loop;
end;
$$;


-- 2. Datos de prueba
-- p1, p2, p3: principales de prueba (solo si el grupo está vacío).
-- n: administrador no principal. u, v: profesionales. x: cuenta recién invitada.

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000005b1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-n@buildcast.test'),
    ('00000000-0000-4000-a000-0000000005c1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-u@buildcast.test'),
    ('00000000-0000-4000-a000-0000000005c2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-v@buildcast.test'),
    ('00000000-0000-4000-a000-0000000005c3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-x@buildcast.test');

update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000005b1';

create temporary table _principales (orden integer primary key, id uuid not null) on commit drop;

do $$
declare
    v_actuales integer := (select count(*) from public.administradores_principales);
begin
    if v_actuales = 0 then
        insert into auth.users (id, instance_id, aud, role, email)
        values
            ('00000000-0000-4000-a000-0000000005a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-p1@buildcast.test'),
            ('00000000-0000-4000-a000-0000000005a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-p2@buildcast.test'),
            ('00000000-0000-4000-a000-0000000005a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-005-p3@buildcast.test');
        update public.perfiles set rol_global = 'administrador'
        where id in ('00000000-0000-4000-a000-0000000005a1', '00000000-0000-4000-a000-0000000005a2',
                     '00000000-0000-4000-a000-0000000005a3');
        insert into public.administradores_principales (perfil_id)
        values ('00000000-0000-4000-a000-0000000005a1'),
               ('00000000-0000-4000-a000-0000000005a2'),
               ('00000000-0000-4000-a000-0000000005a3');
    elsif v_actuales <> 3 then
        raise exception 'FALLO: el grupo de principales tiene % integrantes; deben ser 0 (sin configurar) o 3', v_actuales;
    end if;

    insert into _principales (orden, id)
    select row_number() over (order by a.fecha_creacion, a.perfil_id), a.perfil_id
    from public.administradores_principales a;
end;
$$;


-- 3. Grupo de tres administradores principales

do $$
declare
    v_p1 uuid := (select id from _principales where orden = 1);
begin
    assert (select count(*) from public.administradores_principales) = 3,
        'FALLO: el grupo no tiene tres integrantes';
    assert not exists (
        select 1 from public.administradores_principales a
        join public.perfiles p on p.id = a.perfil_id
        where p.rol_global <> 'administrador'
    ), 'FALLO: hay un principal sin rol administrador';

    -- Un cuarto no entra, aunque sea administrador.
    begin
        insert into public.administradores_principales (perfil_id) values ('00000000-0000-4000-a000-0000000005b1');
        raise exception 'FALLO: entró un cuarto principal';
    exception when sqlstate '55000' then null;
    end;

    -- Un profesional tampoco.
    begin
        insert into public.administradores_principales (perfil_id) values ('00000000-0000-4000-a000-0000000005c1');
        raise exception 'FALLO: entró un profesional como principal';
    exception when sqlstate '55000' then null;
    end;

    -- No se quita ni se cambia a nadie del grupo.
    begin
        delete from public.administradores_principales where perfil_id = v_p1;
        raise exception 'FALLO: se quitó un principal';
    exception when sqlstate '55000' then null;
    end;
    begin
        update public.administradores_principales set perfil_id = '00000000-0000-4000-a000-0000000005b1' where perfil_id = v_p1;
        raise exception 'FALLO: se reemplazó un principal';
    exception when sqlstate '55000' then null;
    end;
    begin
        truncate public.administradores_principales cascade;
        raise exception 'FALLO: se vació el grupo de principales';
    exception when sqlstate '55000' then null;
    end;

    -- Un principal no se degrada ni se elimina.
    begin
        update public.perfiles set rol_global = 'profesional' where id = v_p1;
        raise exception 'FALLO: se degradó a un principal';
    exception when sqlstate '55000' then null;
    end;
    begin
        delete from public.perfiles where id = v_p1;
        raise exception 'FALLO: se borró el perfil de un principal';
    exception when sqlstate '55000' then null;
    end;
    begin
        delete from auth.users where id = v_p1;
        raise exception 'FALLO: se borró la cuenta de un principal';
    exception when sqlstate '55000' or foreign_key_violation then null;
    end;

    -- Cambiar su nombre o correo sí se puede.
    update public.perfiles set nombre = nombre where id = v_p1;

    assert (select count(*) from public.administradores_principales) = 3,
        'FALLO: el grupo cambió';
end;
$$;


-- 4. Usuario normal sin privilegios

do $$
begin
    -- Un profesional no solicita ni aprueba.
    begin
        perform public.solicitar_administrador('00000000-0000-4000-a000-0000000005c1', '00000000-0000-4000-a000-0000000005c2');
        raise exception 'FALLO: un profesional creó una solicitud';
    exception when sqlstate '42501' then null;
    end;
    begin
        perform public.registrar_usuario_creado('00000000-0000-4000-a000-0000000005c1',
                                                '00000000-0000-4000-a000-0000000005c3', 'X', 'enlace');
        raise exception 'FALLO: un profesional registró un usuario';
    exception when sqlstate '42501' then null;
    end;
end;
$$;

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000005c1","role":"authenticated"}', true);

do $$
begin
    -- No ve a los principales ni el perfil de otros.
    assert (select count(*) from public.administradores_principales) = 0,
        'FALLO: un profesional ve el grupo de principales';
    assert (select count(*) from public.perfiles) = 1,
        'FALLO: un profesional ve perfiles ajenos';

    begin
        perform 1 from public.solicitudes_administrador;
        raise exception 'FALLO: un profesional lee solicitudes';
    exception when insufficient_privilege then null;
    end;
    begin
        perform 1 from public.auditoria_administracion;
        raise exception 'FALLO: un profesional lee la auditoría';
    exception when insufficient_privilege then null;
    end;
    begin
        perform public.solicitar_administrador('00000000-0000-4000-a000-0000000005c1', '00000000-0000-4000-a000-0000000005c1');
        raise exception 'FALLO: authenticated ejecuta solicitar_administrador';
    exception when insufficient_privilege then null;
    end;
    begin
        update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000005c1';
        raise exception 'FALLO: un profesional se promovió a sí mismo';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;

-- service_role tampoco cambia el rol directamente.
set local role service_role;

do $$
begin
    begin
        update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000005c1';
        raise exception 'FALLO: service_role promovió sin aprobaciones';
    exception when insufficient_privilege then null;
    end;
    begin
        insert into public.aprobaciones_administrador (solicitud_id, administrador_id)
        values (gen_random_uuid(), '00000000-0000-4000-a000-0000000005b1');
        raise exception 'FALLO: service_role insertó una aprobación directa';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;


-- 5. Flujo 3/3

do $$
declare
    v_p1 uuid := (select id from _principales where orden = 1);
    v_p2 uuid := (select id from _principales where orden = 2);
    v_p3 uuid := (select id from _principales where orden = 3);
    v_u uuid := '00000000-0000-4000-a000-0000000005c1';
    v_n uuid := '00000000-0000-4000-a000-0000000005b1';
    v_solicitud public.solicitudes_administrador;
    v_resultado public.solicitudes_administrador;
begin
    -- Un administrador no principal puede solicitar.
    v_solicitud := public.solicitar_administrador(v_n, v_u);
    assert v_solicitud.estado = 'pendiente' and v_solicitud.solicitado_por = v_n,
        'FALLO: la solicitud no quedó pendiente';

    -- Sin solicitudes activas duplicadas.
    begin
        perform public.solicitar_administrador(v_p1, v_u);
        raise exception 'FALLO: se duplicó la solicitud activa';
    exception when unique_violation then null;
    end;

    -- No se solicita para quien ya es administrador.
    begin
        perform public.solicitar_administrador(v_p1, v_n);
        raise exception 'FALLO: solicitud para un administrador';
    exception when sqlstate '55000' then null;
    end;

    -- Un no principal no aprueba, aunque sea administrador.
    begin
        perform public.aprobar_solicitud_administrador(v_n, v_solicitud.id);
        raise exception 'FALLO: aprobó un administrador no principal';
    exception when sqlstate '42501' then null;
    end;

    -- El objetivo no se aprueba a sí mismo.
    begin
        perform public.aprobar_solicitud_administrador(v_u, v_solicitud.id);
        raise exception 'FALLO: el objetivo se aprobó a sí mismo';
    exception when sqlstate '42501' then null;
    end;

    -- 1/3
    v_resultado := public.aprobar_solicitud_administrador(v_p1, v_solicitud.id);
    assert v_resultado.estado = 'pendiente', 'FALLO: 1/3 completó la solicitud';
    assert (select rol_global from public.perfiles where id = v_u) = 'profesional', 'FALLO: 1/3 promovió';

    -- Aprobación duplicada.
    begin
        perform public.aprobar_solicitud_administrador(v_p1, v_solicitud.id);
        raise exception 'FALLO: un principal aprobó dos veces';
    exception when unique_violation then null;
    end;

    -- 2/3
    v_resultado := public.aprobar_solicitud_administrador(v_p2, v_solicitud.id);
    assert v_resultado.estado = 'pendiente', 'FALLO: 2/3 completó la solicitud';
    assert (select rol_global from public.perfiles where id = v_u) = 'profesional', 'FALLO: 2/3 promovió';
    assert (select count(*) from public.aprobaciones_administrador where solicitud_id = v_solicitud.id) = 2,
        'FALLO: no hay dos aprobaciones';

    -- 3/3
    v_resultado := public.aprobar_solicitud_administrador(v_p3, v_solicitud.id);
    assert v_resultado.estado = 'aprobada' and v_resultado.fecha_resolucion is not null,
        'FALLO: 3/3 no completó la solicitud';
    assert (select rol_global from public.perfiles where id = v_u) = 'administrador', 'FALLO: 3/3 no promovió';

    -- Completada: no recibe más aprobaciones.
    begin
        perform public.aprobar_solicitud_administrador(v_p3, v_solicitud.id);
        raise exception 'FALLO: una solicitud completada recibió otra aprobación';
    exception when sqlstate '55000' then null;
    end;

    -- El nuevo administrador no es principal: no aprueba y el grupo sigue en tres.
    assert not exists (select 1 from public.administradores_principales where perfil_id = v_u),
        'FALLO: el promovido quedó como principal';
    assert (select count(*) from public.administradores_principales) = 3, 'FALLO: el grupo cambió';

    v_solicitud := public.solicitar_administrador(v_p1, '00000000-0000-4000-a000-0000000005c2');
    begin
        perform public.aprobar_solicitud_administrador(v_u, v_solicitud.id);
        raise exception 'FALLO: un administrador nuevo aprobó';
    exception when sqlstate '42501' then null;
    end;

    -- Quien solicita y es principal también aprueba.
    v_resultado := public.aprobar_solicitud_administrador(v_p1, v_solicitud.id);
    assert v_resultado.estado = 'pendiente', 'FALLO: 1/3 completó la segunda solicitud';

    -- Auditoría: una promoción exactamente.
    assert (select count(*) from public.auditoria_administracion
            where accion = 'usuario_promovido_administrador' and usuario_objetivo_id = v_u) = 1,
        'FALLO: la promoción no quedó registrada una sola vez';
    assert (select count(*) from public.auditoria_administracion
            where accion = 'administrador_aprobado' and usuario_objetivo_id = v_u) = 3,
        'FALLO: no hay tres aprobaciones auditadas';
    assert (select count(*) from public.auditoria_administracion
            where accion = 'solicitud_administrador_creada' and usuario_objetivo_id = v_u) = 1,
        'FALLO: la solicitud no quedó auditada';
end;
$$;


-- 6. Usuario creado y auditoría inmutable

do $$
declare
    v_perfil public.perfiles;
begin
    v_perfil := public.registrar_usuario_creado(
        (select id from _principales where orden = 1),
        '00000000-0000-4000-a000-0000000005c3', '  Nora Pérez ', 'enlace');
    assert v_perfil.nombre = 'Nora Pérez' and v_perfil.rol_global = 'profesional',
        'FALLO: el usuario creado no quedó como profesional con nombre';

    assert exists (
        select 1 from public.auditoria_administracion
        where accion = 'usuario_creado' and usuario_objetivo_id = '00000000-0000-4000-a000-0000000005c3'
          and detalle ->> 'modo' = 'enlace' and not (detalle ? 'enlace')
    ), 'FALLO: usuario_creado sin auditar o con el enlace guardado';

    begin
        update public.auditoria_administracion set accion = 'otra' where usuario_objetivo_id = '00000000-0000-4000-a000-0000000005c3';
        raise exception 'FALLO: se modificó la auditoría';
    exception when sqlstate '55000' then null;
    end;
    begin
        delete from public.auditoria_administracion where usuario_objetivo_id = '00000000-0000-4000-a000-0000000005c3';
        raise exception 'FALLO: se borró la auditoría';
    exception when sqlstate '55000' then null;
    end;
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
