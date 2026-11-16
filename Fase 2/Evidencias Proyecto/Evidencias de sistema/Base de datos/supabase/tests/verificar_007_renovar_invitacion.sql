-- Verifica la migración 007_renovar_invitacion.sql contra una base real (después de la 005).
-- Termina en rollback: no deja datos.

begin;

set local plpgsql.check_asserts = on;


-- 1. Privilegios

do $$
declare
    v_funcion text := 'public.registrar_invitacion_renovada(uuid, uuid, text)';
begin
    assert (select prosecdef from pg_proc where oid = v_funcion::regprocedure),
        'FALLO: registrar_invitacion_renovada no es security definer';
    assert (select proconfig from pg_proc where oid = v_funcion::regprocedure) @> array['search_path=""'],
        'FALLO: registrar_invitacion_renovada sin search_path vacío';
    assert has_function_privilege('service_role', v_funcion, 'execute')
       and not has_function_privilege('authenticated', v_funcion, 'execute')
       and not has_function_privilege('anon', v_funcion, 'execute'),
        'FALLO: privilegios de registrar_invitacion_renovada';
end;
$$;


-- 2. Datos de prueba: a administrador, u profesional, x invitado.

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000007a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-007-a@buildcast.test'),
    ('00000000-0000-4000-a000-0000000007c1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-007-u@buildcast.test'),
    ('00000000-0000-4000-a000-0000000007c2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-007-x@buildcast.test');

update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000007a1';


-- 3. Reglas

do $$
declare
    v_a uuid := '00000000-0000-4000-a000-0000000007a1';
    v_u uuid := '00000000-0000-4000-a000-0000000007c1';
    v_x uuid := '00000000-0000-4000-a000-0000000007c2';
    v_perfiles integer := (select count(*) from public.perfiles);
begin
    -- Un profesional no renueva.
    begin
        perform public.registrar_invitacion_renovada(v_u, v_x, 'enlace');
        raise exception 'FALLO: un profesional registró una renovación';
    exception when sqlstate '42501' then null;
    end;

    -- Usuario inexistente.
    begin
        perform public.registrar_invitacion_renovada(v_a, gen_random_uuid(), 'enlace');
        raise exception 'FALLO: se auditó un usuario inexistente';
    exception when sqlstate 'P0002' then null;
    end;

    -- Modo desconocido.
    begin
        perform public.registrar_invitacion_renovada(v_a, v_x, 'sms');
        raise exception 'FALLO: se aceptó un modo desconocido';
    exception when sqlstate '22023' then null;
    end;

    -- Dos renovaciones seguidas: dos registros, sin perfiles nuevos ni cambio de rol.
    perform public.registrar_invitacion_renovada(v_a, v_x, 'enlace');
    perform public.registrar_invitacion_renovada(v_a, v_x, 'correo');

    assert (select count(*) from public.auditoria_administracion
            where accion = 'invitacion_renovada' and usuario_objetivo_id = v_x and actor_id = v_a) = 2,
        'FALLO: las renovaciones no quedaron auditadas';
    assert not exists (
        select 1 from public.auditoria_administracion
        where accion = 'invitacion_renovada' and usuario_objetivo_id = v_x
          and (detalle ? 'enlace' or detalle ? 'token' or detalle ? 'otp' or detalle::text ilike '%verify%')
    ), 'FALLO: la auditoría guarda el enlace o el token';
    assert (select count(*) from public.perfiles) = v_perfiles,
        'FALLO: la renovación creó perfiles';
    assert (select rol_global from public.perfiles where id = v_x) = 'profesional',
        'FALLO: la renovación cambió el rol';
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
