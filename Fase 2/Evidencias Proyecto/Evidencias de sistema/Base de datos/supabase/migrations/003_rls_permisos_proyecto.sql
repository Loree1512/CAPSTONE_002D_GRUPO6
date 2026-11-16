-- Permisos por proyecto en la base: RLS por membresía y cambios de miembros con historial.
--
-- Propietario y editor leen y escriben; lector solo lee; quien no pertenece al proyecto no
-- ve nada.
-- Requiere 002_roles_permisos_auditoria.sql.

-- 1. Funciones de acceso
-- security definer: leen proyectos y miembros sin pasar por RLS, así las políticas que
-- las usan no se llaman entre sí. Solo responden sobre auth.uid().


-- Pertenece al proyecto: cualquier rol, o es su creador.
create or replace function public.puede_leer_proyecto(p_proyecto_id uuid)
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
    ) or exists (
        select 1
        from public.proyectos p
        where p.id = p_proyecto_id
          and p.usuario_id = (select auth.uid())
    );
$$;

-- Propietario o editor, o es su creador.
create or replace function public.puede_editar_proyecto(p_proyecto_id uuid)
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
          and m.rol in ('propietario', 'editor')
    ) or exists (
        select 1
        from public.proyectos p
        where p.id = p_proyecto_id
          and p.usuario_id = (select auth.uid())
    );
$$;

revoke execute on function public.puede_leer_proyecto(uuid) from public, anon;
revoke execute on function public.puede_editar_proyecto(uuid) from public, anon;

grant execute on function public.puede_leer_proyecto(uuid) to authenticated, service_role;
grant execute on function public.puede_editar_proyecto(uuid) to authenticated, service_role;


-- 2. RLS de proyectos

drop policy "proyectos_seleccionar_propios" on public.proyectos;
drop policy "proyectos_actualizar_propios" on public.proyectos;

-- usuario_id se compara directo: la fila recién insertada se ve sin esperar a su membresía.
create policy "proyectos_seleccionar_miembros"
    on public.proyectos
    for select
    to authenticated
    using (
        usuario_id = (select auth.uid())
        or public.puede_leer_proyecto(id)
    );

-- "proyectos_insertar_propios" no cambia: cada uno crea proyectos a su nombre.

create policy "proyectos_actualizar_editores"
    on public.proyectos
    for update
    to authenticated
    using (
        usuario_id = (select auth.uid())
        or public.puede_editar_proyecto(id)
    )
    with check (
        usuario_id = (select auth.uid())
        or public.puede_editar_proyecto(id)
    );

-- Solo se editan los datos del proyecto. usuario_id queda fuera: un editor no puede
-- ponerse como creador (y con eso, como propietario).
revoke update on public.proyectos from authenticated;
grant update (
    nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos,
    estandar_terminaciones, estado, plantilla_id
) on public.proyectos to authenticated;


-- 3. RLS de partidas del proyecto

drop policy "proyecto_partidas_seleccionar_propias" on public.proyecto_partidas;
drop policy "proyecto_partidas_insertar_propias" on public.proyecto_partidas;
drop policy "proyecto_partidas_actualizar_propias" on public.proyecto_partidas;
drop policy "proyecto_partidas_eliminar_propias" on public.proyecto_partidas;

create policy "proyecto_partidas_seleccionar_miembros"
    on public.proyecto_partidas
    for select
    to authenticated
    using (public.puede_leer_proyecto(proyecto_id));

create policy "proyecto_partidas_insertar_editores"
    on public.proyecto_partidas
    for insert
    to authenticated
    with check (public.puede_editar_proyecto(proyecto_id));

create policy "proyecto_partidas_actualizar_editores"
    on public.proyecto_partidas
    for update
    to authenticated
    using (public.puede_editar_proyecto(proyecto_id))
    with check (public.puede_editar_proyecto(proyecto_id));

create policy "proyecto_partidas_eliminar_editores"
    on public.proyecto_partidas
    for delete
    to authenticated
    using (public.puede_editar_proyecto(proyecto_id));


-- 4. RLS de estimaciones
-- Siguen sin políticas de escritura: las guarda crear_estimacion con service role.

drop policy "estimaciones_seleccionar_propias" on public.estimaciones;
drop policy "estimacion_partidas_seleccionar_propias" on public.estimacion_partidas;

create policy "estimaciones_seleccionar_miembros"
    on public.estimaciones
    for select
    to authenticated
    using (public.puede_leer_proyecto(proyecto_id));

create policy "estimacion_partidas_seleccionar_miembros"
    on public.estimacion_partidas
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.estimaciones e
            where e.id = estimacion_partidas.estimacion_id
              and public.puede_leer_proyecto(e.proyecto_id)
        )
    );


-- 5. RLS de miembros e historial
-- Igual que en la 002, pero el creador sin fila propia también los ve.

drop policy "proyecto_miembros_seleccionar_miembros" on public.proyecto_miembros;
drop policy "historial_proyecto_seleccionar_miembros" on public.historial_proyecto;

create policy "proyecto_miembros_seleccionar_miembros"
    on public.proyecto_miembros
    for select
    to authenticated
    using (public.puede_leer_proyecto(proyecto_id));

create policy "historial_proyecto_seleccionar_miembros"
    on public.historial_proyecto
    for select
    to authenticated
    using (public.puede_leer_proyecto(proyecto_id));


-- 6. RPC de partidas del proyecto
-- Mismo cuerpo que en la 001, con el permiso comprobado al entrar: un lector recibe un
-- error claro en vez de "no encontrado" (aplicar) o de no cambiar nada (ordenar).
-- Con service role (sin auth.uid()) se comportan como antes.

create or replace function public.aplicar_plantilla_proyecto(
    p_proyecto_id uuid,
    p_plantilla_id uuid,
    p_partidas jsonb,
    p_reemplazar boolean default false
)
returns setof public.proyecto_partidas
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if (select auth.uid()) is not null then
        if not public.puede_leer_proyecto(p_proyecto_id) then
            raise exception 'Proyecto no encontrado'
                using errcode = 'P0002';
        end if;
        if not public.puede_editar_proyecto(p_proyecto_id) then
            raise exception 'Tu permiso en este proyecto no permite realizar esta acción.'
                using errcode = '42501';
        end if;
    end if;

    -- RLS oculta los proyectos ajenos.
    perform 1 from public.proyectos where id = p_proyecto_id for update;
    if not found then
        raise exception 'Proyecto no encontrado'
            using errcode = 'P0002';
    end if;

    if jsonb_typeof(p_partidas) is distinct from 'array' then
        raise exception 'Las partidas de la plantilla deben ser una lista.'
            using errcode = '22023';
    end if;

    if not p_reemplazar and exists (
        select 1 from public.proyecto_partidas where proyecto_id = p_proyecto_id
    ) then
        raise exception 'El proyecto ya tiene partidas. Confirma si quieres reemplazarlas.'
            using errcode = '55000';
    end if;

    delete from public.proyecto_partidas where proyecto_id = p_proyecto_id;

    insert into public.proyecto_partidas (
        proyecto_id, partida_id, categoria_id, nombre, unidad,
        cantidad, precio_unitario_override, origen, orden, observacion
    )
    select
        p_proyecto_id, r.partida_id, r.categoria_id, r.nombre, r.unidad,
        r.cantidad, null, 'plantilla', r.orden, null
    from jsonb_populate_recordset(null::public.proyecto_partidas, p_partidas) r;

    update public.proyectos
    set plantilla_id = p_plantilla_id
    where id = p_proyecto_id;

    return query
        select * from public.proyecto_partidas
        where proyecto_id = p_proyecto_id
        order by orden;
end;
$$;

create or replace function public.ordenar_partidas_proyecto(
    p_proyecto_id uuid,
    p_ids uuid[]
)
returns setof public.proyecto_partidas
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if (select auth.uid()) is not null then
        if not public.puede_leer_proyecto(p_proyecto_id) then
            raise exception 'Proyecto no encontrado'
                using errcode = 'P0002';
        end if;
        if not public.puede_editar_proyecto(p_proyecto_id) then
            raise exception 'Tu permiso en este proyecto no permite realizar esta acción.'
                using errcode = '42501';
        end if;
    end if;

    perform 1 from public.proyectos where id = p_proyecto_id;
    if not found then
        raise exception 'Proyecto no encontrado'
            using errcode = 'P0002';
    end if;

    if coalesce(array_length(p_ids, 1), 0) <> (select count(distinct x) from unnest(p_ids) x)
       or (select count(*) from public.proyecto_partidas where proyecto_id = p_proyecto_id)
          <> coalesce(array_length(p_ids, 1), 0)
       or exists (
           select 1 from unnest(p_ids) x
           where not exists (
               select 1 from public.proyecto_partidas pp
               where pp.id = x and pp.proyecto_id = p_proyecto_id
           )
       ) then
        raise exception 'El nuevo orden debe incluir todas las partidas del proyecto.'
            using errcode = '22023';
    end if;

    update public.proyecto_partidas pp
    set orden = o.n
    from unnest(p_ids) with ordinality as o(id, n)
    where pp.id = o.id
      and pp.proyecto_id = p_proyecto_id
      and pp.orden is distinct from o.n;

    return query
        select * from public.proyecto_partidas
        where proyecto_id = p_proyecto_id
        order by orden;
end;
$$;

-- crear_proyecto_con_plantilla no cambia: inserta el proyecto a nombre de quien llama
-- y aplica la plantilla con la función de arriba.


-- 7. RPC: guardar una estimación (solo service role)
-- Mismo cuerpo que en la 001; cambia quién puede: propietario o editor, o el creador.

create or replace function public.crear_estimacion(
    p_usuario_id uuid,
    p_estimacion jsonb,
    p_partidas jsonb
)
returns public.estimaciones
language plpgsql
set search_path = ''
as $$
declare
    v_proyecto_id uuid := (p_estimacion ->> 'proyecto_id')::uuid;
    v_existe boolean;
    v_creador uuid;
    v_rol text;
    v_estimacion public.estimaciones;
begin
    select true, p.usuario_id into v_existe, v_creador
    from public.proyectos p
    where p.id = v_proyecto_id;

    select m.rol into v_rol
    from public.proyecto_miembros m
    where m.proyecto_id = v_proyecto_id
      and m.usuario_id = p_usuario_id;

    -- Sin proyecto, sin usuario o sin pertenecer a él: no se revela que existe.
    if v_existe is not true
       or p_usuario_id is null
       or (v_rol is null and v_creador is distinct from p_usuario_id) then
        raise exception 'El proyecto no existe.'
            using errcode = 'P0002';
    end if;

    if v_creador is distinct from p_usuario_id and v_rol not in ('propietario', 'editor') then
        raise exception 'Tu permiso en este proyecto no permite generar estimaciones.'
            using errcode = '42501';
    end if;

    if jsonb_typeof(p_partidas) is distinct from 'array' then
        raise exception 'Las partidas de la estimación deben ser una lista.'
            using errcode = '22023';
    end if;

    insert into public.estimaciones (
        proyecto_id, usuario_id,
        version_precio_id, version_precio, fuente_version_precio,
        comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones,
        parametros_snapshot, version_motor,
        aplicar_factores, factor_comuna, factor_pisos, factor_ajuste,
        costo_directo_base, costo_directo, gastos_generales_pct, gastos_generales,
        utilidad_pct, utilidad, costo_total, costo_m2,
        partidas_calculadas, partidas_sin_precio, partidas_sin_cantidad,
        firma_partidas, completa
    )
    select
        v_proyecto_id, p_usuario_id,
        r.version_precio_id, r.version_precio, r.fuente_version_precio,
        r.comuna, r.tipo_obra, r.materialidad, r.superficie_m2, r.numero_pisos, r.estandar_terminaciones,
        r.parametros_snapshot, r.version_motor,
        r.aplicar_factores, r.factor_comuna, r.factor_pisos, r.factor_ajuste,
        r.costo_directo_base, r.costo_directo, r.gastos_generales_pct, r.gastos_generales,
        r.utilidad_pct, r.utilidad, r.costo_total, r.costo_m2,
        r.partidas_calculadas, r.partidas_sin_precio, r.partidas_sin_cantidad,
        r.firma_partidas, r.completa
    from jsonb_populate_record(null::public.estimaciones, p_estimacion) r
    returning * into v_estimacion;

    insert into public.estimacion_partidas (
        estimacion_id, proyecto_partida_id, partida_id, orden, origen,
        codigo_partida, nombre_partida, unidad, observacion,
        categoria_id, categoria_codigo, categoria_nombre, categoria_orden,
        estado, cantidad,
        precio_unitario_banco, precio_unitario_override, precio_unitario_usado, fuente_precio,
        factor_aplicado, subtotal_base, subtotal
    )
    select
        v_estimacion.id, r.proyecto_partida_id, r.partida_id, r.orden, r.origen,
        r.codigo_partida, r.nombre_partida, r.unidad, r.observacion,
        r.categoria_id, r.categoria_codigo, r.categoria_nombre, r.categoria_orden,
        r.estado, r.cantidad,
        r.precio_unitario_banco, r.precio_unitario_override, r.precio_unitario_usado, r.fuente_precio,
        r.factor_aplicado, r.subtotal_base, r.subtotal
    from jsonb_populate_recordset(null::public.estimacion_partidas, p_partidas) r;

    return v_estimacion;
end;
$$;

revoke execute on function public.crear_estimacion(uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.crear_estimacion(uuid, jsonb, jsonb) to service_role;


-- 8. Correo de perfiles
-- Los miembros se agregan por correo sin distinguir mayúsculas ni espacios.

create index perfiles_email_normalizado_idx
    on public.perfiles (lower(btrim(email)));


-- 9. RPC de miembros (solo service role)
-- Cada una cambia la membresía y anexa su evento al historial en la misma transacción:
-- si falla el registro, tampoco queda el cambio.
-- p_solicitante_id viene del token ya validado por el backend. Cada función vuelve a
-- comprobar que es propietario.

-- Devuelve el creador del proyecto. P0002 si el solicitante no pertenece al proyecto;
-- 42501 si pertenece pero no es propietario.
create or replace function public.comprobar_propietario_proyecto(
    p_solicitante_id uuid,
    p_proyecto_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_existe boolean;
    v_creador uuid;
    v_rol text;
begin
    select true, p.usuario_id into v_existe, v_creador
    from public.proyectos p
    where p.id = p_proyecto_id;

    select m.rol into v_rol
    from public.proyecto_miembros m
    where m.proyecto_id = p_proyecto_id
      and m.usuario_id = p_solicitante_id;

    if v_existe is not true
       or p_solicitante_id is null
       or (v_rol is null and v_creador is distinct from p_solicitante_id) then
        raise exception 'Proyecto no encontrado'
            using errcode = 'P0002';
    end if;

    if v_creador is distinct from p_solicitante_id and v_rol is distinct from 'propietario' then
        raise exception 'Solo el propietario administra los miembros del proyecto.'
            using errcode = '42501';
    end if;

    return v_creador;
end;
$$;

create or replace function public.agregar_miembro_proyecto(
    p_solicitante_id uuid,
    p_proyecto_id uuid,
    p_email text,
    p_rol text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_creador uuid;
    v_perfil public.perfiles;
    v_miembro public.proyecto_miembros;
begin
    v_creador := public.comprobar_propietario_proyecto(p_solicitante_id, p_proyecto_id);

    if p_rol is null or p_rol not in ('editor', 'lector') then
        raise exception 'El permiso debe ser editor o lector.'
            using errcode = '22023';
    end if;

    -- Correo exacto, sin distinguir mayúsculas ni espacios sobrantes.
    select * into v_perfil
    from public.perfiles p
    where lower(btrim(p.email)) = lower(btrim(p_email))
    order by p.fecha_creacion, p.id
    limit 1;

    if not found then
        raise exception 'No hay un usuario registrado con ese correo.'
            using errcode = 'P0002';
    end if;

    if v_perfil.id = v_creador or exists (
        select 1
        from public.proyecto_miembros m
        where m.proyecto_id = p_proyecto_id
          and m.usuario_id = v_perfil.id
    ) then
        raise exception 'El usuario ya es miembro del proyecto.'
            using errcode = '23505';
    end if;

    -- Dos altas simultáneas: el unique (proyecto_id, usuario_id) lanza 23505.
    insert into public.proyecto_miembros (proyecto_id, usuario_id, rol, agregado_por)
    values (p_proyecto_id, v_perfil.id, p_rol, p_solicitante_id)
    returning * into v_miembro;

    insert into public.historial_proyecto (
        proyecto_id, usuario_id, usuario_email,
        accion, entidad, entidad_id, valores_nuevos, origen
    )
    values (
        p_proyecto_id, p_solicitante_id,
        (select s.email from public.perfiles s where s.id = p_solicitante_id),
        'miembro_agregado', 'miembro', v_perfil.id,
        jsonb_build_object('usuario_id', v_perfil.id, 'email', v_perfil.email, 'rol', p_rol),
        'rpc'
    );

    return jsonb_build_object(
        'usuario_id', v_miembro.usuario_id,
        'email', v_perfil.email,
        'nombre', v_perfil.nombre,
        'rol', v_miembro.rol,
        'fecha_creacion', v_miembro.fecha_creacion
    );
end;
$$;

create or replace function public.cambiar_rol_miembro_proyecto(
    p_solicitante_id uuid,
    p_proyecto_id uuid,
    p_usuario_id uuid,
    p_rol text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_creador uuid;
    v_perfil public.perfiles;
    v_miembro public.proyecto_miembros;
    v_es_miembro boolean;
    v_rol_anterior text;
begin
    v_creador := public.comprobar_propietario_proyecto(p_solicitante_id, p_proyecto_id);

    if p_rol is null or p_rol not in ('editor', 'lector') then
        raise exception 'El permiso debe ser editor o lector.'
            using errcode = '22023';
    end if;

    select * into v_miembro
    from public.proyecto_miembros m
    where m.proyecto_id = p_proyecto_id
      and m.usuario_id = p_usuario_id
    for update;
    v_es_miembro := found;

    -- El creador es propietario aunque le falte la fila.
    if p_usuario_id = v_creador or (v_es_miembro and v_miembro.rol = 'propietario') then
        raise exception 'El propietario del proyecto no puede cambiar de permiso.'
            using errcode = '55000';
    end if;

    if not v_es_miembro then
        raise exception 'El usuario no es miembro del proyecto.'
            using errcode = 'P0002';
    end if;

    select * into v_perfil from public.perfiles p where p.id = p_usuario_id;

    -- Mismo permiso: no hay cambio ni evento.
    if v_miembro.rol <> p_rol then
        v_rol_anterior := v_miembro.rol;

        update public.proyecto_miembros m
        set rol = p_rol
        where m.id = v_miembro.id
        returning * into v_miembro;

        insert into public.historial_proyecto (
            proyecto_id, usuario_id, usuario_email,
            accion, entidad, entidad_id, valores_anteriores, valores_nuevos, origen
        )
        values (
            p_proyecto_id, p_solicitante_id,
            (select s.email from public.perfiles s where s.id = p_solicitante_id),
            'miembro_rol_cambiado', 'miembro', p_usuario_id,
            jsonb_build_object('rol', v_rol_anterior),
            jsonb_build_object('rol', p_rol, 'email', v_perfil.email),
            'rpc'
        );
    end if;

    return jsonb_build_object(
        'usuario_id', v_miembro.usuario_id,
        'email', v_perfil.email,
        'nombre', v_perfil.nombre,
        'rol', v_miembro.rol,
        'fecha_creacion', v_miembro.fecha_creacion
    );
end;
$$;

create or replace function public.quitar_miembro_proyecto(
    p_solicitante_id uuid,
    p_proyecto_id uuid,
    p_usuario_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_creador uuid;
    v_miembro public.proyecto_miembros;
    v_es_miembro boolean;
begin
    v_creador := public.comprobar_propietario_proyecto(p_solicitante_id, p_proyecto_id);

    select * into v_miembro
    from public.proyecto_miembros m
    where m.proyecto_id = p_proyecto_id
      and m.usuario_id = p_usuario_id
    for update;
    v_es_miembro := found;

    -- El creador es propietario aunque le falte la fila.
    if p_usuario_id = v_creador or (v_es_miembro and v_miembro.rol = 'propietario') then
        raise exception 'El propietario del proyecto no se puede quitar.'
            using errcode = '55000';
    end if;

    if not v_es_miembro then
        raise exception 'El usuario no es miembro del proyecto.'
            using errcode = 'P0002';
    end if;

    delete from public.proyecto_miembros m where m.id = v_miembro.id;

    insert into public.historial_proyecto (
        proyecto_id, usuario_id, usuario_email,
        accion, entidad, entidad_id, valores_anteriores, origen
    )
    values (
        p_proyecto_id, p_solicitante_id,
        (select s.email from public.perfiles s where s.id = p_solicitante_id),
        'miembro_eliminado', 'miembro', p_usuario_id,
        jsonb_build_object(
            'usuario_id', p_usuario_id,
            'email', (select p.email from public.perfiles p where p.id = p_usuario_id),
            'rol', v_miembro.rol
        ),
        'rpc'
    );
end;
$$;

-- La comprobación es interna: solo la usan las tres funciones de arriba.
revoke execute on function public.comprobar_propietario_proyecto(uuid, uuid) from public, anon, authenticated, service_role;

revoke execute on function public.agregar_miembro_proyecto(uuid, uuid, text, text) from public, anon, authenticated;
revoke execute on function public.cambiar_rol_miembro_proyecto(uuid, uuid, uuid, text) from public, anon, authenticated;
revoke execute on function public.quitar_miembro_proyecto(uuid, uuid, uuid) from public, anon, authenticated;

grant execute on function public.agregar_miembro_proyecto(uuid, uuid, text, text) to service_role;
grant execute on function public.cambiar_rol_miembro_proyecto(uuid, uuid, uuid, text) to service_role;
grant execute on function public.quitar_miembro_proyecto(uuid, uuid, uuid) to service_role;


-- 10. Miembros: solo por las RPC
revoke insert, update, delete on public.proyecto_miembros from service_role;


-- PostgREST vuelve a leer el esquema (funciones nuevas).
notify pgrst, 'reload schema';
