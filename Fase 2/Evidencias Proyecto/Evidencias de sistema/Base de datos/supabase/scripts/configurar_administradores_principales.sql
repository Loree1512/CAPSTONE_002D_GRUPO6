-- Configura los tres administradores principales.
-- Ejecutar una vez después de la migración 005.

begin;

do $$
declare
    -- (correo, nombre visible)
    v_principales text[][] := array[
        array['correo-principal-1@ejemplo.cl', 'Nombre 1'],
        array['correo-principal-2@ejemplo.cl', 'Nombre 2'],
        array['correo-principal-3@ejemplo.cl', 'Nombre 3']
    ];
    v_fila text[];
    v_id uuid;
begin
    foreach v_fila slice 1 in array v_principales loop
        select u.id into v_id
        from auth.users u
        where lower(btrim(u.email)) = lower(btrim(v_fila[1]));

        if v_id is null then
            raise exception 'No existe una cuenta con el correo %', v_fila[1];
        end if;

        insert into public.perfiles (id, email, nombre, rol_global)
        select u.id, u.email, v_fila[2], 'administrador'
        from auth.users u
        where u.id = v_id
        on conflict (id) do update
            set nombre = excluded.nombre,
                rol_global = 'administrador';

        -- Sin on conflict: el trigger corre antes y contaría el tope igual.
        if not exists (select 1 from public.administradores_principales a where a.perfil_id = v_id) then
            insert into public.administradores_principales (perfil_id) values (v_id);
        end if;
    end loop;

    if (select count(*) from public.administradores_principales) <> 3 then
        raise exception 'El grupo quedó con % integrantes; deben ser 3.',
            (select count(*) from public.administradores_principales);
    end if;
end;
$$;

-- Revisión: deben aparecer exactamente tres filas, todas con rol administrador.
select p.nombre, p.email, p.rol_global, a.fecha_creacion
from public.administradores_principales a
join public.perfiles p on p.id = a.perfil_id
order by p.nombre;

commit;
