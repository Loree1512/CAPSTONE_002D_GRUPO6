-- Roles globales, permisos por proyecto y auditoría: estructura.
-- Solo agrega tablas, funciones auxiliares, triggers y backfill.


-- 1. Perfiles

-- Un perfil por usuario de Auth. Sin perfil, el usuario se trata como profesional.
create table public.perfiles (
    id uuid primary key
        references auth.users(id) on delete cascade,

    email text,
    nombre text,

    rol_global text not null default 'profesional'
        check (rol_global in ('administrador', 'profesional')),

    fecha_creacion timestamptz not null default now(),
    fecha_actualizacion timestamptz not null default now()
);

create trigger perfiles_actualizar_fecha
    before update on public.perfiles
    for each row
    execute function public.actualizar_fecha_actualizacion();

alter table public.perfiles enable row level security;

-- Cada usuario lee solo su perfil. Nadie cambia su propio rol.
create policy "perfiles_seleccionar_propio"
    on public.perfiles
    for select
    to authenticated
    using ((select auth.uid()) = id);

-- Privilegios explícitos: no dependen de los que Supabase da por defecto.
revoke all on public.perfiles from public, anon, authenticated, service_role;
grant select on public.perfiles to authenticated;
grant select, insert, update on public.perfiles to service_role;

-- Crea el perfil al registrarse y mantiene el correo al día.
create or replace function public.crear_perfil_usuario()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.perfiles (id, email)
    values (new.id, new.email)
    on conflict (id) do update set email = excluded.email;
    return new;
exception when others then
-- Un fallo aquí no debe impedir el registro.
    raise warning 'No se pudo crear el perfil de %: %', new.id, sqlerrm;
    return new;
end;
$$;

create trigger buildcast_crear_perfil_usuario
    after insert or update of email on auth.users
    for each row
    execute function public.crear_perfil_usuario();


-- 2. Miembros del proyecto

create table public.proyecto_miembros (
    id uuid primary key default gen_random_uuid(),

    proyecto_id uuid not null
        references public.proyectos(id) on delete cascade,

    usuario_id uuid not null
        references auth.users(id) on delete cascade,

    rol text not null
        check (rol in ('propietario', 'editor', 'lector')),

    -- Quién lo agregó.
    agregado_por uuid references auth.users(id) on delete set null,

    fecha_creacion timestamptz not null default now(),
    fecha_actualizacion timestamptz not null default now(),

    unique (proyecto_id, usuario_id)
);

-- Un solo propietario por proyecto.
create unique index proyecto_miembros_unico_propietario_idx
    on public.proyecto_miembros (proyecto_id)
    where rol = 'propietario';

-- Proyectos de un usuario (lo consultan las funciones de permisos).
create index proyecto_miembros_usuario_idx
    on public.proyecto_miembros (usuario_id, proyecto_id);

create trigger proyecto_miembros_actualizar_fecha
    before update on public.proyecto_miembros
    for each row
    execute function public.actualizar_fecha_actualizacion();

-- Una fila no cambia de proyecto ni de usuario, y el propietario no se degrada ni se
-- quita. Sí se borra en cascada al eliminar el proyecto o la cuenta.
-- security definer: ve proyectos y cuentas sea cual sea el rol que escribe.
create or replace function public.proteger_miembros_proyecto()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'UPDATE' then
        if new.proyecto_id is distinct from old.proyecto_id
           or new.usuario_id is distinct from old.usuario_id then
            raise exception 'Un miembro no cambia de proyecto ni de usuario.'
                using errcode = '55000';
        end if;
        if old.rol = 'propietario' and new.rol <> 'propietario' then
            raise exception 'El propietario del proyecto no puede cambiar de permiso.'
                using errcode = '55000';
        end if;
        return new;
    end if;

    -- En un borrado en cascada el proyecto o la cuenta ya no existen.
    if old.rol = 'propietario'
       and exists (select 1 from public.proyectos where id = old.proyecto_id)
       and exists (select 1 from auth.users where id = old.usuario_id) then
        raise exception 'El propietario del proyecto no se puede quitar.'
            using errcode = '55000';
    end if;
    return old;
end;
$$;

create trigger proyecto_miembros_proteger
    before update or delete on public.proyecto_miembros
    for each row
    execute function public.proteger_miembros_proyecto();

-- El creador del proyecto queda como propietario, se cree por donde se cree.
create or replace function public.agregar_propietario_proyecto()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.usuario_id is not null then
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol, agregado_por)
        values (new.id, new.usuario_id, 'propietario', new.usuario_id)
        on conflict (proyecto_id, usuario_id) do nothing;
    end if;
    return new;
end;
$$;

create trigger proyectos_agregar_propietario
    after insert on public.proyectos
    for each row
    execute function public.agregar_propietario_proyecto();


-- 3. Funciones de permisos
-- security definer: leen perfiles y miembros sin pasar por RLS, así las políticas que
-- las usen no se llaman entre sí (sin recursión). Solo responden sobre auth.uid().

-- Rol del usuario actual en el proyecto; null si no es miembro.
create or replace function public.rol_en_proyecto(p_proyecto_id uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select m.rol
    from public.proyecto_miembros m
    where m.proyecto_id = p_proyecto_id
      and m.usuario_id = (select auth.uid());
$$;

create or replace function public.tiene_rol_proyecto(p_proyecto_id uuid, p_roles text[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.proyecto_miembros m
        where m.proyecto_id = p_proyecto_id
          and m.usuario_id = (select auth.uid())
          and m.rol = any (p_roles)
    );
$$;

create or replace function public.es_administrador()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.perfiles p
        where p.id = (select auth.uid())
          and p.rol_global = 'administrador'
    );
$$;

revoke execute on function public.rol_en_proyecto(uuid) from public, anon;
revoke execute on function public.tiene_rol_proyecto(uuid, text[]) from public, anon;
revoke execute on function public.es_administrador() from public, anon;
revoke execute on function public.crear_perfil_usuario() from public, anon, authenticated;
revoke execute on function public.agregar_propietario_proyecto() from public, anon, authenticated;
revoke execute on function public.proteger_miembros_proyecto() from public, anon, authenticated;

grant execute on function public.rol_en_proyecto(uuid) to authenticated, service_role;
grant execute on function public.tiene_rol_proyecto(uuid, text[]) to authenticated, service_role;
grant execute on function public.es_administrador() to authenticated, service_role;

alter table public.proyecto_miembros enable row level security;

-- Los miembros de un proyecto ven quiénes lo integran.
create policy "proyecto_miembros_seleccionar_miembros"
    on public.proyecto_miembros
    for select
    to authenticated
    using (public.rol_en_proyecto(proyecto_id) is not null);

revoke all on public.proyecto_miembros from public, anon, authenticated, service_role;
grant select on public.proyecto_miembros to authenticated;
grant select, insert, update, delete on public.proyecto_miembros to service_role;


-- 4. Historial del proyecto

-- Registro de solo anexar. Acción y entidad son texto libre para sumar eventos (o
-- triggers) más adelante sin cambiar la tabla.
create table public.historial_proyecto (
    id uuid primary key default gen_random_uuid(),

    proyecto_id uuid not null
        references public.proyectos(id) on delete cascade,

    -- Quién hizo la acción. Sin FK: el registro sobrevive al borrado de la cuenta.
    usuario_id uuid,
    usuario_email text,

    -- proyecto_creado, partida_agregada, estimacion_generada, miembro_agregado…
    accion text not null
        check (btrim(accion) <> ''),

    -- proyecto, proyecto_partida, estimacion, miembro.
    entidad text not null
        check (btrim(entidad) <> ''),
    entidad_id uuid,

    valores_anteriores jsonb,
    valores_nuevos jsonb,

    -- Quién escribió el registro.
    origen text not null default 'api'
        check (origen in ('api', 'rpc', 'trigger')),

    fecha timestamptz not null default now()
);

-- Historial de un proyecto, más reciente primero.
create index historial_proyecto_proyecto_fecha_idx
    on public.historial_proyecto (proyecto_id, fecha desc);

-- Ni cambios ni bajas, tampoco con service role. Solo se va en cascada con su proyecto.
-- security definer: ve el proyecto sea cual sea el rol que escribe.
create or replace function public.bloquear_cambios_historial()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'DELETE'
       and not exists (select 1 from public.proyectos where id = old.proyecto_id) then
        return old;
    end if;

    raise exception 'El historial del proyecto no se modifica ni se elimina.'
        using errcode = '55000';
end;
$$;

revoke execute on function public.bloquear_cambios_historial() from public, anon, authenticated;

create trigger historial_proyecto_inmutable
    before update or delete on public.historial_proyecto
    for each row
    execute function public.bloquear_cambios_historial();

alter table public.historial_proyecto enable row level security;

create policy "historial_proyecto_seleccionar_miembros"
    on public.historial_proyecto
    for select
    to authenticated
    using (public.rol_en_proyecto(proyecto_id) is not null);

revoke all on public.historial_proyecto from public, anon, authenticated, service_role;
grant select on public.historial_proyecto to authenticated;
grant select, insert on public.historial_proyecto to service_role;


-- 5. Datos existentes
-- Se puede repetir sin duplicar. No se crea historial retroactivo.

insert into public.perfiles (id, email)
select u.id, u.email
from auth.users u
on conflict (id) do nothing;

-- Proyectos sin usuario_id (cuenta eliminada) quedan sin propietario.
insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
select p.id, p.usuario_id, 'propietario'
from public.proyectos p
where p.usuario_id is not null
on conflict (proyecto_id, usuario_id) do nothing;


-- PostgREST vuelve a leer el esquema (tablas y funciones nuevas).
notify pgrst, 'reload schema';
