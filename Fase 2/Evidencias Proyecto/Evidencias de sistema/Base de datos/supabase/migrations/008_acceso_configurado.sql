-- 1. Columna

alter table public.perfiles
    add column acceso_configurado_at timestamptz;

comment on column public.perfiles.acceso_configurado_at is
    'Cuándo la persona definió su contraseña. Null: invitación pendiente.';

-- Quienes ya existían siguen activos: nadie queda bloqueado por esta migración.
update public.perfiles
set acceso_configurado_at = coalesce(fecha_creacion, now())
where acceso_configurado_at is null;

insert into public.perfiles (id, email, acceso_configurado_at)
select u.id, u.email, now()
from auth.users u
on conflict (id) do nothing;

-- 2. Perfil de cuentas nuevas
-- Con contraseña desde el alta (registro público): activo. Invitada (sin contraseña):
-- pendiente hasta que la cree.

create or replace function public.crear_perfil_usuario()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.perfiles (id, email, acceso_configurado_at)
    values (
        new.id,
        new.email,
        case
            when tg_op = 'INSERT' and new.invited_at is null and coalesce(new.encrypted_password, '') <> ''
            then now()
        end
    )
    on conflict (id) do update set email = excluded.email;
    return new;
exception when others then
-- Un fallo aquí no debe impedir el registro.
    raise warning 'No se pudo crear el perfil de %: %', new.id, sqlerrm;
    return new;
end;
$$;


-- 3. Completar la invitación
-- El backend la llama después de que Supabase Auth guardó la contraseña. Solo pasa de
-- pendiente a activo, nunca al revés; repetirla no cambia la fecha.

create or replace function public.completar_acceso(p_usuario_id uuid)
returns timestamptz
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_email text;
    v_fecha timestamptz;
begin
    select u.email into v_email
    from auth.users u
    where u.id = p_usuario_id;

    if not found then
        raise exception 'El usuario no existe.'
            using errcode = 'P0002';
    end if;

    insert into public.perfiles (id, email)
    values (p_usuario_id, v_email)
    on conflict (id) do nothing;

    update public.perfiles
    set acceso_configurado_at = now()
    where id = p_usuario_id
      and acceso_configurado_at is null
    returning acceso_configurado_at into v_fecha;

    if v_fecha is not null then
        -- Nunca se guarda la contraseña ni el token de la sesión.
        perform public.registrar_auditoria_administracion(
            'acceso_configurado', p_usuario_id, p_usuario_id, 'perfil', p_usuario_id,
            jsonb_build_object('email', v_email)
        );
        return v_fecha;
    end if;

    select p.acceso_configurado_at into v_fecha
    from public.perfiles p
    where p.id = p_usuario_id;
    return v_fecha;
end;
$$;

revoke execute on function public.completar_acceso(uuid) from public, anon, authenticated;
grant execute on function public.completar_acceso(uuid) to service_role;
