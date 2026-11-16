-- 007: auditoría de invitaciones renovadas.
-- Requiere la 005. El enlace nuevo lo genera Supabase Auth desde el backend; aquí solo
-- queda el registro de quién lo renovó. Nunca se guarda la URL, el OTP ni el token.

create or replace function public.registrar_invitacion_renovada(
    p_actor_id uuid,
    p_usuario_id uuid,
    p_modo text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_email text;
begin
    perform public.exigir_administrador_global(p_actor_id);

    select p.email into v_email
    from public.perfiles p
    where p.id = p_usuario_id;

    if not found then
        raise exception 'El usuario no existe.'
            using errcode = 'P0002';
    end if;

    if p_modo is null or p_modo not in ('enlace', 'correo') then
        raise exception 'Modo de invitación desconocido.'
            using errcode = '22023';
    end if;

    perform public.registrar_auditoria_administracion(
        'invitacion_renovada', p_actor_id, p_usuario_id, 'perfil', p_usuario_id,
        jsonb_build_object('email', v_email, 'modo', p_modo)
    );
end;
$$;

revoke execute on function public.registrar_invitacion_renovada(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.registrar_invitacion_renovada(uuid, uuid, text) to service_role;
