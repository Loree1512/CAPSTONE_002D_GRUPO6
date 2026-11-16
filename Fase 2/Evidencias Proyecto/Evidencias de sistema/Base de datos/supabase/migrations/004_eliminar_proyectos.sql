-- Solo el propietario puede eliminar el proyecto.
-- Las relaciones dependientes se eliminan en cascada.
create or replace function public.es_propietario_proyecto(p_proyecto_id uuid)
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
          and m.rol = 'propietario'
    ) or exists (
        select 1
        from public.proyectos p
        where p.id = p_proyecto_id
          and p.usuario_id = (select auth.uid())
    );
$$;

revoke execute on function public.es_propietario_proyecto(uuid) from public, anon;
grant execute on function public.es_propietario_proyecto(uuid) to authenticated, service_role;

create policy "proyectos_eliminar_propietario"
    on public.proyectos
    for delete
    to authenticated
    using (
        usuario_id = (select auth.uid())
        or public.es_propietario_proyecto(id)
    );

-- La política es el límite real; el privilegio se asegura por si la base no lo trae.
grant delete on public.proyectos to authenticated;
