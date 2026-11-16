-- 1. Administradores principales

create table public.administradores_principales (
    perfil_id uuid primary key
        references public.perfiles(id) on delete restrict,

    fecha_creacion timestamptz not null default now()
);

create or replace function public.proteger_administradores_principales()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'INSERT' then
        -- Altas simultáneas no pasan juntas el tope de tres.
        lock table public.administradores_principales in share row exclusive mode;

        if not exists (
            select 1 from public.perfiles p
            where p.id = new.perfil_id and p.rol_global = 'administrador'
        ) then
            raise exception 'Un administrador principal debe tener rol administrador.'
                using errcode = '55000';
        end if;

        if (select count(*) from public.administradores_principales) >= 3 then
            raise exception 'El grupo de administradores principales ya tiene tres integrantes.'
                using errcode = '55000';
        end if;

        return new;
    end if;

    raise exception 'El grupo de administradores principales no se modifica en esta versión.'
        using errcode = '55000';
end;
$$;

create trigger administradores_principales_proteger
    before insert or update or delete on public.administradores_principales
    for each row
    execute function public.proteger_administradores_principales();

create trigger administradores_principales_sin_truncate
    before truncate on public.administradores_principales
    for each statement
    execute function public.proteger_administradores_principales();

alter table public.administradores_principales enable row level security;

-- Cada usuario sabe si él mismo es principal (GET /autenticacion/yo).
create policy "administradores_principales_seleccionar_propio"
    on public.administradores_principales
    for select
    to authenticated
    using ((select auth.uid()) = perfil_id);

revoke all on public.administradores_principales from public, anon, authenticated, service_role;
grant select on public.administradores_principales to authenticated, service_role;


-- 2. Perfiles: un principal no se degrada ni se borra

create or replace function public.proteger_perfil_principal()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'DELETE' then
        if exists (select 1 from public.administradores_principales a where a.perfil_id = old.id) then
            raise exception 'Un administrador principal no se puede eliminar.'
                using errcode = '55000';
        end if;
        return old;
    end if;

    if not exists (select 1 from public.administradores_principales a where a.perfil_id = old.id) then
        return new;
    end if;

    if new.rol_global is distinct from 'administrador' or new.id is distinct from old.id then
        raise exception 'Un administrador principal no puede dejar de ser administrador.'
            using errcode = '55000';
    end if;

    return new;
end;
$$;

create trigger perfiles_proteger_principal
    before update or delete on public.perfiles
    for each row
    execute function public.proteger_perfil_principal();

-- El rol global ya no lo escribe el backend: solo la aprobación 3/3 (o SQL del dueño).
revoke insert, update on public.perfiles from service_role;
grant update (email, nombre) on public.perfiles to service_role;


-- 3. Solicitudes y aprobaciones

create table public.solicitudes_administrador (
    id uuid primary key default gen_random_uuid(),

    -- Usuario que se propone como administrador.
    usuario_id uuid not null
        references public.perfiles(id) on delete cascade,

    solicitado_por uuid
        references auth.users(id) on delete set null,

    estado text not null default 'pendiente'
        check (estado in ('pendiente', 'aprobada')),

    fecha_creacion timestamptz not null default now(),
    fecha_resolucion timestamptz,

    check ((estado = 'pendiente') = (fecha_resolucion is null))
);

-- Una sola solicitud activa por usuario.
create unique index solicitudes_administrador_pendiente_unica_idx
    on public.solicitudes_administrador (usuario_id)
    where estado = 'pendiente';

create table public.aprobaciones_administrador (
    id uuid primary key default gen_random_uuid(),

    solicitud_id uuid not null
        references public.solicitudes_administrador(id) on delete cascade,

    -- Solo un principal aprueba.
    administrador_id uuid not null
        references public.administradores_principales(perfil_id) on delete restrict,

    fecha timestamptz not null default now(),

    -- Nadie aprueba dos veces la misma solicitud.
    unique (solicitud_id, administrador_id)
);

alter table public.solicitudes_administrador enable row level security;
alter table public.aprobaciones_administrador enable row level security;

-- Sin políticas: se leen desde FastAPI con service role, tras validar al administrador.
revoke all on public.solicitudes_administrador from public, anon, authenticated, service_role;
revoke all on public.aprobaciones_administrador from public, anon, authenticated, service_role;
grant select on public.solicitudes_administrador to service_role;
grant select on public.aprobaciones_administrador to service_role;


-- 4. Auditoría administrativa
-- Acciones que no pertenecen a un proyecto. Solo se anexa.

create table public.auditoria_administracion (
    id uuid primary key default gen_random_uuid(),

    -- usuario_creado, solicitud_administrador_creada, administrador_aprobado,
    -- usuario_promovido_administrador…
    accion text not null
        check (btrim(accion) <> ''),

    -- Sin FK: el registro sobrevive al borrado de las cuentas.
    actor_id uuid,
    actor_email text,
    usuario_objetivo_id uuid,

    entidad text not null
        check (btrim(entidad) <> ''),
    entidad_id uuid,

    detalle jsonb,

    origen text not null default 'rpc'
        check (origen in ('api', 'rpc', 'trigger')),

    fecha timestamptz not null default now()
);

create index auditoria_administracion_fecha_idx
    on public.auditoria_administracion (fecha desc);

create or replace function public.bloquear_cambios_auditoria()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    raise exception 'La auditoría administrativa no se modifica ni se elimina.'
        using errcode = '55000';
end;
$$;

create trigger auditoria_administracion_inmutable
    before update or delete on public.auditoria_administracion
    for each row
    execute function public.bloquear_cambios_auditoria();

create trigger auditoria_administracion_sin_truncate
    before truncate on public.auditoria_administracion
    for each statement
    execute function public.bloquear_cambios_auditoria();

alter table public.auditoria_administracion enable row level security;

revoke all on public.auditoria_administracion from public, anon, authenticated, service_role;
grant select on public.auditoria_administracion to service_role;


-- 5. RPC (solo service role)
-- p_actor_id viene del token ya validado por el backend; cada función vuelve a
-- comprobar su rol. El cambio y su auditoría van en la misma transacción.

create or replace function public.registrar_auditoria_administracion(
    p_accion text,
    p_actor_id uuid,
    p_usuario_objetivo_id uuid,
    p_entidad text,
    p_entidad_id uuid,
    p_detalle jsonb
)
returns void
language sql
security definer
set search_path = ''
as $$
    insert into public.auditoria_administracion (
        accion, actor_id, actor_email, usuario_objetivo_id, entidad, entidad_id, detalle, origen
    )
    values (
        p_accion, p_actor_id,
        (select p.email from public.perfiles p where p.id = p_actor_id),
        p_usuario_objetivo_id, p_entidad, p_entidad_id, p_detalle, 'rpc'
    );
$$;

create or replace function public.exigir_administrador_global(p_actor_id uuid)
returns void
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if p_actor_id is null or not exists (
        select 1 from public.perfiles p
        where p.id = p_actor_id and p.rol_global = 'administrador'
    ) then
        raise exception 'Solo un administrador puede realizar esta acción.'
            using errcode = '42501';
    end if;
end;
$$;

-- Después de crear la cuenta en Supabase Auth: nombre del perfil y auditoría.
create or replace function public.registrar_usuario_creado(
    p_actor_id uuid,
    p_usuario_id uuid,
    p_nombre text,
    p_modo text
)
returns public.perfiles
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_perfil public.perfiles;
begin
    perform public.exigir_administrador_global(p_actor_id);

    if not exists (select 1 from auth.users u where u.id = p_usuario_id) then
        raise exception 'El usuario no existe.'
            using errcode = 'P0002';
    end if;

    -- El trigger de auth.users ya creó el perfil; si falló, se crea aquí. El rol no se toca.
    insert into public.perfiles (id, email, nombre)
    select u.id, u.email, nullif(btrim(p_nombre), '')
    from auth.users u
    where u.id = p_usuario_id
    on conflict (id) do update
        set nombre = excluded.nombre,
            email = excluded.email
    returning * into v_perfil;

    -- Nunca se guarda el enlace de invitación.
    perform public.registrar_auditoria_administracion(
        'usuario_creado', p_actor_id, p_usuario_id, 'perfil', p_usuario_id,
        jsonb_build_object('email', v_perfil.email, 'nombre', v_perfil.nombre,
                           'rol_global', v_perfil.rol_global, 'modo', p_modo)
    );

    return v_perfil;
end;
$$;

create or replace function public.solicitar_administrador(
    p_actor_id uuid,
    p_usuario_id uuid
)
returns public.solicitudes_administrador
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_perfil public.perfiles;
    v_solicitud public.solicitudes_administrador;
begin
    perform public.exigir_administrador_global(p_actor_id);

    select * into v_perfil from public.perfiles p where p.id = p_usuario_id;
    if not found then
        raise exception 'El usuario no existe.'
            using errcode = 'P0002';
    end if;

    if v_perfil.rol_global = 'administrador' then
        raise exception 'El usuario ya es administrador.'
            using errcode = '55000';
    end if;

    begin
        insert into public.solicitudes_administrador (usuario_id, solicitado_por)
        values (p_usuario_id, p_actor_id)
        returning * into v_solicitud;
    exception when unique_violation then
        raise exception 'Ya hay una solicitud pendiente para este usuario.'
            using errcode = '23505';
    end;

    perform public.registrar_auditoria_administracion(
        'solicitud_administrador_creada', p_actor_id, p_usuario_id,
        'solicitud_administrador', v_solicitud.id,
        jsonb_build_object('email', v_perfil.email)
    );

    return v_solicitud;
end;
$$;

-- Aprueba y, con la tercera aprobación distinta, promueve. Todo en una transacción.
create or replace function public.aprobar_solicitud_administrador(
    p_actor_id uuid,
    p_solicitud_id uuid
)
returns public.solicitudes_administrador
language plpgsql
security definer
set search_path = ''
as $$
declare
    c_requeridas constant integer := 3;
    v_solicitud public.solicitudes_administrador;
    v_aprobaciones integer;
begin
    -- El bloqueo ordena las aprobaciones simultáneas: la tercera se cuenta una sola vez.
    select * into v_solicitud
    from public.solicitudes_administrador s
    where s.id = p_solicitud_id
    for update;

    if not found then
        raise exception 'La solicitud no existe.'
            using errcode = 'P0002';
    end if;

    if v_solicitud.estado <> 'pendiente' then
        raise exception 'La solicitud ya fue completada.'
            using errcode = '55000';
    end if;

    if p_actor_id is null
       or p_actor_id = v_solicitud.usuario_id
       or not exists (select 1 from public.administradores_principales a where a.perfil_id = p_actor_id) then
        raise exception 'Solo los administradores principales aprueban promociones.'
            using errcode = '42501';
    end if;

    if (select count(*) from public.administradores_principales) <> c_requeridas then
        raise exception 'El grupo de administradores principales debe tener tres integrantes.'
            using errcode = '55000';
    end if;

    begin
        insert into public.aprobaciones_administrador (solicitud_id, administrador_id)
        values (p_solicitud_id, p_actor_id);
    exception when unique_violation then
        raise exception 'Ya aprobaste esta solicitud.'
            using errcode = '23505';
    end;

    select count(*) into v_aprobaciones
    from public.aprobaciones_administrador a
    where a.solicitud_id = p_solicitud_id;

    perform public.registrar_auditoria_administracion(
        'administrador_aprobado', p_actor_id, v_solicitud.usuario_id,
        'solicitud_administrador', p_solicitud_id,
        jsonb_build_object('aprobaciones', v_aprobaciones, 'requeridas', c_requeridas)
    );

    if v_aprobaciones >= c_requeridas then
        update public.perfiles
        set rol_global = 'administrador'
        where id = v_solicitud.usuario_id;

        update public.solicitudes_administrador
        set estado = 'aprobada', fecha_resolucion = now()
        where id = p_solicitud_id
        returning * into v_solicitud;

        perform public.registrar_auditoria_administracion(
            'usuario_promovido_administrador', p_actor_id, v_solicitud.usuario_id,
            'perfil', v_solicitud.usuario_id,
            jsonb_build_object('rol_anterior', 'profesional', 'rol_nuevo', 'administrador',
                               'solicitud_id', p_solicitud_id)
        );
    end if;

    return v_solicitud;
end;
$$;

-- Triggers y funciones internas: nadie las ejecuta a mano.
revoke execute on function public.proteger_administradores_principales() from public, anon, authenticated, service_role;
revoke execute on function public.proteger_perfil_principal() from public, anon, authenticated, service_role;
revoke execute on function public.bloquear_cambios_auditoria() from public, anon, authenticated, service_role;
revoke execute on function public.registrar_auditoria_administracion(text, uuid, uuid, text, uuid, jsonb) from public, anon, authenticated, service_role;
revoke execute on function public.exigir_administrador_global(uuid) from public, anon, authenticated, service_role;

revoke execute on function public.registrar_usuario_creado(uuid, uuid, text, text) from public, anon, authenticated;
revoke execute on function public.solicitar_administrador(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.aprobar_solicitud_administrador(uuid, uuid) from public, anon, authenticated;

grant execute on function public.registrar_usuario_creado(uuid, uuid, text, text) to service_role;
grant execute on function public.solicitar_administrador(uuid, uuid) to service_role;
grant execute on function public.aprobar_solicitud_administrador(uuid, uuid) to service_role;


-- PostgREST vuelve a leer el esquema (tablas y funciones nuevas).
notify pgrst, 'reload schema';
