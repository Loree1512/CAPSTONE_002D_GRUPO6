-- Verifica la migración 008_acceso_configurado.sql contra una base real.
-- Termina en rollback: no deja datos.

begin;

set local plpgsql.check_asserts = on;


-- 1. Estructura y privilegios

do $$
declare
    v_funcion text := 'public.completar_acceso(uuid)';
begin
    assert exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'perfiles' and column_name = 'acceso_configurado_at'
          and is_nullable = 'YES'
    ), 'FALLO: falta perfiles.acceso_configurado_at';

    -- Nadie escribe la columna directo: ni el usuario con su sesión ni el backend.
    assert not has_column_privilege('authenticated', 'public.perfiles', 'acceso_configurado_at', 'update'),
        'FALLO: authenticated puede marcar su acceso';
    assert not has_column_privilege('service_role', 'public.perfiles', 'acceso_configurado_at', 'update'),
        'FALLO: service_role escribe acceso_configurado_at sin la RPC';
    assert has_column_privilege('authenticated', 'public.perfiles', 'acceso_configurado_at', 'select'),
        'FALLO: authenticated no puede leer su estado de acceso';

    assert (select prosecdef from pg_proc where oid = v_funcion::regprocedure),
        'FALLO: completar_acceso no es security definer';
    assert (select proconfig from pg_proc where oid = v_funcion::regprocedure) @> array['search_path=""'],
        'FALLO: completar_acceso sin search_path vacío';
    assert has_function_privilege('service_role', v_funcion, 'execute')
       and not has_function_privilege('authenticated', v_funcion, 'execute')
       and not has_function_privilege('anon', v_funcion, 'execute'),
        'FALLO: privilegios de completar_acceso';

    -- Backfill: los únicos pendientes son cuentas invitadas después de la migración.
    assert not exists (
        select 1 from public.perfiles p
        join auth.users u on u.id = p.id
        where p.acceso_configurado_at is null and u.invited_at is null
    ), 'FALLO: hay perfiles pendientes que no vienen de una invitación';
end;
$$;


-- 2. Cuentas nuevas
-- r: registro público (con contraseña). i: invitada (sin contraseña).

insert into auth.users (id, instance_id, aud, role, email, encrypted_password)
values
    ('00000000-0000-4000-a000-0000000008a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
     'verificar-008-r@buildcast.test', '$2a$10$hashdepruebahashdepruebahashdepruebahashdepruebahas'),
    ('00000000-0000-4000-a000-0000000008a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',
     'verificar-008-i@buildcast.test', '');

do $$
declare
    v_r uuid := '00000000-0000-4000-a000-0000000008a1';
    v_i uuid := '00000000-0000-4000-a000-0000000008a2';
    v_primera timestamptz;
    v_segunda timestamptz;
begin
    assert (select acceso_configurado_at from public.perfiles where id = v_r) is not null,
        'FALLO: el registro con contraseña quedó pendiente';
    assert (select acceso_configurado_at from public.perfiles where id = v_i) is null,
        'FALLO: la cuenta invitada nació activa';

    -- Abrir el enlace: Supabase confirma el correo y pone una contraseña aleatoria. Sigue pendiente.
    update auth.users
    set email_confirmed_at = now(), invited_at = now(), encrypted_password = '$2a$10$aleatoria'
    where id = v_i;
    assert (select acceso_configurado_at from public.perfiles where id = v_i) is null,
        'FALLO: abrir el enlace activó la cuenta';

    -- Cambiar el correo tampoco la activa.
    update auth.users set email = 'verificar-008-i2@buildcast.test' where id = v_i;
    assert (select acceso_configurado_at from public.perfiles where id = v_i) is null,
        'FALLO: actualizar el correo activó la cuenta';

    -- Completar: pasa a activo, una sola vez y con auditoría.
    v_primera := public.completar_acceso(v_i);
    assert v_primera is not null, 'FALLO: completar_acceso no activó la cuenta';
    v_segunda := public.completar_acceso(v_i);
    assert v_segunda = v_primera, 'FALLO: repetir completar_acceso cambió la fecha';
    assert (select count(*) from public.auditoria_administracion
            where accion = 'acceso_configurado' and usuario_objetivo_id = v_i) = 1,
        'FALLO: acceso_configurado sin auditar o duplicado';
    assert not exists (
        select 1 from public.auditoria_administracion
        where accion = 'acceso_configurado' and usuario_objetivo_id = v_i
          and (detalle ? 'password' or detalle ? 'token')
    ), 'FALLO: la auditoría guarda la contraseña o el token';

    begin
        perform public.completar_acceso(gen_random_uuid());
        raise exception 'FALLO: se completó el acceso de un usuario inexistente';
    exception when sqlstate 'P0002' then null;
    end;
end;
$$;


-- Nada de lo anterior queda en la base.
rollback;
