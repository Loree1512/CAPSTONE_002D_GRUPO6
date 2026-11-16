-- Verifica la migración 003_rls_permisos_proyecto.sql contra una base real.

-- Personas: A (crea P1, P3 y P4), B (crea P2; editor en P1 y lector en P3), C (lector en
-- P1 y P4), D (sin proyectos) y ADM (administrador global, sin proyectos).
-- P4 es de A pero sin fila en proyecto_miembros: prueba al creador como propietario.

begin;

-- Los ASSERT deben estar activos durante toda la prueba.
set local plpgsql.check_asserts = on;


-- 1. Privilegios, funciones y políticas

do $$
declare
    v_funcion text;
begin
    -- proyecto_miembros: service_role solo lee; lo demás va por las RPC.
    assert has_table_privilege('service_role', 'public.proyecto_miembros', 'select'),
        'FALLO: service_role no puede leer proyecto_miembros';
    assert not has_table_privilege('service_role', 'public.proyecto_miembros', 'insert, update, delete, truncate'),
        'FALLO: service_role todavía puede escribir proyecto_miembros';
    assert not has_table_privilege('authenticated', 'public.proyecto_miembros', 'insert, update, delete, truncate'),
        'FALLO: authenticated puede escribir proyecto_miembros';
    assert not has_table_privilege('anon', 'public.proyecto_miembros', 'select, insert, update, delete, truncate'),
        'FALLO: anon tiene privilegios sobre proyecto_miembros';

    -- proyectos: authenticated edita solo los datos del proyecto, nunca usuario_id.
    assert not has_table_privilege('authenticated', 'public.proyectos', 'update'),
        'FALLO: authenticated conserva update sobre toda la tabla proyectos';
    assert has_column_privilege('authenticated', 'public.proyectos', 'nombre', 'update')
       and has_column_privilege('authenticated', 'public.proyectos', 'estado', 'update')
       and has_column_privilege('authenticated', 'public.proyectos', 'plantilla_id', 'update'),
        'FALLO: authenticated no puede editar los datos del proyecto';
    assert not has_column_privilege('authenticated', 'public.proyectos', 'usuario_id', 'update')
       and not has_column_privilege('authenticated', 'public.proyectos', 'id', 'update'),
        'FALLO: authenticated puede cambiar usuario_id o id de un proyecto';

    -- Funciones security definer con search_path vacío.
    foreach v_funcion in array array[
        'public.puede_leer_proyecto(uuid)', 'public.puede_editar_proyecto(uuid)',
        'public.comprobar_propietario_proyecto(uuid, uuid)',
        'public.agregar_miembro_proyecto(uuid, uuid, text, text)',
        'public.cambiar_rol_miembro_proyecto(uuid, uuid, uuid, text)',
        'public.quitar_miembro_proyecto(uuid, uuid, uuid)'
    ] loop
        assert (select prosecdef from pg_proc where oid = v_funcion::regprocedure),
            'FALLO: no es security definer: ' || v_funcion;
        assert (select proconfig from pg_proc where oid = v_funcion::regprocedure) @> array['search_path=""'],
            'FALLO: sin search_path vacío: ' || v_funcion;
        assert not has_function_privilege('anon', v_funcion, 'execute'),
            'FALLO: anon puede ejecutar ' || v_funcion;
    end loop;

    -- Las RPC de miembros y crear_estimacion: solo service_role.
    foreach v_funcion in array array[
        'public.agregar_miembro_proyecto(uuid, uuid, text, text)',
        'public.cambiar_rol_miembro_proyecto(uuid, uuid, uuid, text)',
        'public.quitar_miembro_proyecto(uuid, uuid, uuid)',
        'public.crear_estimacion(uuid, jsonb, jsonb)'
    ] loop
        assert has_function_privilege('service_role', v_funcion, 'execute'),
            'FALLO: service_role no puede ejecutar ' || v_funcion;
        assert not has_function_privilege('authenticated', v_funcion, 'execute')
           and not has_function_privilege('anon', v_funcion, 'execute'),
            'FALLO: un usuario puede ejecutar ' || v_funcion;
    end loop;

    assert not has_function_privilege('service_role', 'public.comprobar_propietario_proyecto(uuid, uuid)', 'execute')
       and not has_function_privilege('authenticated', 'public.comprobar_propietario_proyecto(uuid, uuid)', 'execute'),
        'FALLO: comprobar_propietario_proyecto debe ser interna';

    assert has_function_privilege('authenticated', 'public.puede_leer_proyecto(uuid)', 'execute')
       and has_function_privilege('authenticated', 'public.puede_editar_proyecto(uuid)', 'execute'),
        'FALLO: authenticated no puede evaluar las políticas';

    -- Políticas por tabla.
    assert (select array_agg(policyname::text order by policyname::text collate "C") from pg_policies
            where schemaname = 'public' and tablename = 'proyectos')
        = array['proyectos_actualizar_editores', 'proyectos_insertar_propios', 'proyectos_seleccionar_miembros'],
        'FALLO: políticas de proyectos';

    assert (select array_agg(policyname::text order by policyname::text collate "C") from pg_policies
            where schemaname = 'public' and tablename = 'proyecto_partidas')
        = array['proyecto_partidas_actualizar_editores', 'proyecto_partidas_eliminar_editores',
                'proyecto_partidas_insertar_editores', 'proyecto_partidas_seleccionar_miembros'],
        'FALLO: políticas de proyecto_partidas';

    assert (select array_agg(policyname::text order by policyname::text collate "C") from pg_policies
            where schemaname = 'public'
              and tablename in ('estimaciones', 'estimacion_partidas', 'proyecto_miembros', 'historial_proyecto'))
        = array['estimacion_partidas_seleccionar_miembros', 'estimaciones_seleccionar_miembros',
                'historial_proyecto_seleccionar_miembros', 'proyecto_miembros_seleccionar_miembros'],
        'FALLO: políticas de estimaciones, miembros o historial';

    -- Ninguna política de proyectos depende del rol global.
    assert not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename in ('proyectos', 'proyecto_partidas', 'estimaciones', 'estimacion_partidas',
                            'proyecto_miembros', 'historial_proyecto')
          and (coalesce(qual, '') || coalesce(with_check, '')) like '%es_administrador%'
    ), 'FALLO: una política da acceso por ser administrador global';

    assert to_regclass('public.perfiles_email_normalizado_idx') is not null,
        'FALLO: falta el índice de correo normalizado';
    assert not (select indisunique from pg_index where indexrelid = 'public.perfiles_email_normalizado_idx'::regclass),
        'FALLO: el índice de correo no debe ser único';
end;
$$;


-- 2. Datos de prueba 

insert into auth.users (id, instance_id, aud, role, email)
values
    ('00000000-0000-4000-a000-0000000003a1', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-003-a@buildcast.test'),
    ('00000000-0000-4000-a000-0000000003a2', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-003-b@buildcast.test'),
    ('00000000-0000-4000-a000-0000000003a3', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-003-c@buildcast.test'),
    ('00000000-0000-4000-a000-0000000003a4', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-003-d@buildcast.test'),
    ('00000000-0000-4000-a000-0000000003a5', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'verificar-003-adm@buildcast.test');

-- ADM es administrador global. El correo de B queda con mayúsculas y espacios en el perfil.
update public.perfiles set rol_global = 'administrador' where id = '00000000-0000-4000-a000-0000000003a5';
update public.perfiles set email = '  Verificar-003-B@BuildCast.TEST ' where id = '00000000-0000-4000-a000-0000000003a2';

-- Catálogo mínimo propio: no depende de los seeds.
insert into public.categorias_partida (id, codigo, nombre, orden)
values (990003, 'V3', 'Verificar 003', 990003);

insert into public.partidas (id, categoria_id, codigo, nombre, unidad)
values ('00000000-0000-4000-c000-0000000003c1', 990003, 'V3.01', 'Verificar 003 · partida', 'gl');

insert into public.versiones_precios (id, version)
values ('00000000-0000-4000-c000-0000000003c2', 'verificar-003');

insert into public.plantillas_presupuesto (id, nombre, tipo_obra, materialidad, vigente)
values ('00000000-0000-4000-c000-0000000003c3', 'Verificar 003', 'Verificar 003', 'Verificar 003', false);

insert into public.proyectos
    (id, usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
values
    ('00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-a000-0000000003a1', 'Verificar 003 · P1', 'Quilpué', 'Verificar 003', 'Verificar 003', 48, 1, 'economico'),
    ('00000000-0000-4000-b000-0000000003b2', '00000000-0000-4000-a000-0000000003a2', 'Verificar 003 · P2', 'Quilpué', 'Verificar 003', 'Verificar 003', 48, 1, 'economico'),
    ('00000000-0000-4000-b000-0000000003b3', '00000000-0000-4000-a000-0000000003a1', 'Verificar 003 · P3', 'Quilpué', 'Verificar 003', 'Verificar 003', 48, 1, 'economico'),
    -- P4 nace sin creador y se le asigna después: queda sin fila en proyecto_miembros.
    ('00000000-0000-4000-b000-0000000003b4', null, 'Verificar 003 · P4', 'Quilpué', 'Verificar 003', 'Verificar 003', 48, 1, 'economico');

update public.proyectos set usuario_id = '00000000-0000-4000-a000-0000000003a1'
where id = '00000000-0000-4000-b000-0000000003b4';

insert into public.proyecto_partidas (id, proyecto_id, categoria_id, nombre, unidad, cantidad, precio_unitario_override, origen, orden)
values
    ('00000000-0000-4000-d000-0000000003d1', '00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · uno', 'gl', 1, 1000, 'manual', 1),
    ('00000000-0000-4000-d000-0000000003d2', '00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · dos', 'gl', 1, 2000, 'manual', 2),
    ('00000000-0000-4000-d000-0000000003d3', '00000000-0000-4000-b000-0000000003b3', 990003, 'P3 · uno', 'gl', 1, 1000, 'manual', 1),
    ('00000000-0000-4000-d000-0000000003d4', '00000000-0000-4000-b000-0000000003b2', 990003, 'P2 · uno', 'gl', 1, 1000, 'manual', 1);

-- Una estimación y una línea válidas, para reutilizar en las llamadas a crear_estimacion.
select set_config('verificar.estimacion', $json${
    "version_precio_id": "00000000-0000-4000-c000-0000000003c2", "version_precio": "verificar-003",
    "comuna": "Quilpué", "tipo_obra": "Verificar 003", "materialidad": "Verificar 003",
    "superficie_m2": 48, "numero_pisos": 1, "estandar_terminaciones": "economico",
    "parametros_snapshot": {}, "version_motor": "verificar-003",
    "aplicar_factores": false, "factor_comuna": 1, "factor_pisos": 1, "factor_ajuste": 1,
    "costo_directo_base": 1000, "costo_directo": 1000, "gastos_generales_pct": 10, "gastos_generales": 100,
    "utilidad_pct": 10, "utilidad": 100, "costo_total": 1200, "costo_m2": 25,
    "partidas_calculadas": 1, "partidas_sin_precio": 0, "partidas_sin_cantidad": 0,
    "firma_partidas": "verificar-003", "completa": true
}$json$, true);

select set_config('verificar.lineas', $json$[{
    "orden": 1, "origen": "manual", "nombre_partida": "P1 · uno", "unidad": "gl",
    "categoria_id": 990003, "categoria_codigo": "V3", "categoria_nombre": "Verificar 003", "categoria_orden": 990003,
    "estado": "calculada", "cantidad": 1, "precio_unitario_override": 1000, "precio_unitario_usado": 1000,
    "factor_aplicado": 1, "subtotal_base": 1000, "subtotal": 1000
}]$json$, true);

do $$
begin
    -- El trigger de la 002 dejó propietarios en P1, P2 y P3; P4 no tiene filas.
    assert (select count(*) from public.proyecto_miembros
            where proyecto_id in ('00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-b000-0000000003b2',
                                  '00000000-0000-4000-b000-0000000003b3')
              and rol = 'propietario') = 3,
        'FALLO: los proyectos de prueba no tienen propietario';
    assert not exists (select 1 from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b4'),
        'FALLO: P4 debía quedar sin filas de miembros';
end;
$$;


-- 3. Miembros: solo con las RPC, como service role

set local role service_role;

do $$
declare
    v_respuesta jsonb;
begin
    -- La tabla ya no se escribe directamente.
    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-a000-0000000003a2', 'editor');
        raise exception 'FALLO: service_role insertó un miembro sin RPC';
    exception when insufficient_privilege then null;
    end;

    begin
        update public.proyecto_miembros set rol = 'editor'
        where proyecto_id = '00000000-0000-4000-b000-0000000003b1';
        raise exception 'FALLO: service_role cambió un permiso sin RPC';
    exception when insufficient_privilege then null;
    end;

    begin
        delete from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b1';
        raise exception 'FALLO: service_role quitó un miembro sin RPC';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.comprobar_propietario_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1');
        raise exception 'FALLO: service_role ejecutó la comprobación interna';
    exception when insufficient_privilege then null;
    end;

    -- A agrega a B como editor de P1. El correo se escribe distinto a como está en el perfil.
    v_respuesta := public.agregar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        'VERIFICAR-003-b@buildcast.test  ', 'editor');
    assert v_respuesta ->> 'usuario_id' = '00000000-0000-4000-a000-0000000003a2'
       and v_respuesta ->> 'rol' = 'editor'
       and v_respuesta ->> 'email' = '  Verificar-003-B@BuildCast.TEST '
       and v_respuesta ? 'nombre' and v_respuesta ->> 'fecha_creacion' is not null,
        'FALLO: respuesta de agregar_miembro_proyecto: ' || v_respuesta::text;

    assert (select rol || '/' || agregado_por::text from public.proyecto_miembros
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1'
              and usuario_id = '00000000-0000-4000-a000-0000000003a2')
        = 'editor/00000000-0000-4000-a000-0000000003a1',
        'FALLO: la fila del miembro agregado';

    -- El evento quedó en la misma operación.
    assert (select count(*) from public.historial_proyecto
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1'
              and accion = 'miembro_agregado' and entidad = 'miembro' and origen = 'rpc'
              and entidad_id = '00000000-0000-4000-a000-0000000003a2'
              and usuario_id = '00000000-0000-4000-a000-0000000003a1'
              and usuario_email = 'verificar-003-a@buildcast.test'
              and valores_anteriores is null
              and valores_nuevos ->> 'rol' = 'editor'
              and valores_nuevos ->> 'usuario_id' = '00000000-0000-4000-a000-0000000003a2') = 1,
        'FALLO: evento miembro_agregado';

    -- C lector en P1; B lector en P3 (otro rol en otro proyecto).
    perform public.agregar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        'verificar-003-c@buildcast.test', 'lector');
    perform public.agregar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b3',
        'verificar-003-b@buildcast.test', 'lector');

    -- A administra P4 como creador, aunque no tenga fila de miembro.
    perform public.agregar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b4',
        'verificar-003-c@buildcast.test', 'lector');

    -- Quien no es propietario no administra miembros.
    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a2', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: un editor agregó un miembro';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.quitar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a3', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a2');
        raise exception 'FALLO: un lector quitó un miembro';
    exception when insufficient_privilege then null;
    end;

    -- Quien no pertenece al proyecto, tampoco: ni D ni el administrador global.
    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a4', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: un ajeno agregó un miembro';
    exception when no_data_found then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a5', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-adm@buildcast.test', 'editor');
        raise exception 'FALLO: el administrador global se agregó a un proyecto ajeno';
    exception when no_data_found then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            null, '00000000-0000-4000-b000-0000000003b1', 'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: se aceptó un solicitante nulo';
    exception when no_data_found then null;
    end;

    -- Solo editor o lector.
    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'propietario');
        raise exception 'FALLO: se agregó un segundo propietario';
    exception when invalid_parameter_value then null;
    end;

    begin
        perform public.cambiar_rol_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a2', 'propietario');
        raise exception 'FALLO: se convirtió a un miembro en propietario';
    exception when invalid_parameter_value then null;
    end;

    -- Correo sin cuenta; el guion bajo no es comodín.
    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar_003_d@buildcast.test', 'lector');
        raise exception 'FALLO: se encontró un correo que no existe';
    exception when no_data_found then null;
    end;

    -- Ya es miembro, o es el propietario (con fila en P1, sin fila en P4).
    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-b@buildcast.test', 'lector');
        raise exception 'FALLO: se agregó dos veces al mismo usuario';
    exception when unique_violation then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-a@buildcast.test', 'lector');
        raise exception 'FALLO: el propietario se agregó a sí mismo';
    exception when unique_violation then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b4',
            'verificar-003-a@buildcast.test', 'lector');
        raise exception 'FALLO: el creador sin fila se agregó como lector';
    exception when unique_violation then null;
    end;

    -- El propietario no cambia de permiso ni se quita (con fila en P1, sin fila en P4).
    begin
        perform public.cambiar_rol_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a1', 'editor');
        raise exception 'FALLO: el propietario cambió de permiso';
    exception when object_not_in_prerequisite_state then null;
    end;

    begin
        perform public.quitar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a1');
        raise exception 'FALLO: se quitó al propietario';
    exception when object_not_in_prerequisite_state then null;
    end;

    begin
        perform public.quitar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b4',
            '00000000-0000-4000-a000-0000000003a1');
        raise exception 'FALLO: se quitó al creador sin fila';
    exception when object_not_in_prerequisite_state then null;
    end;

    -- Quien no es miembro de ese proyecto (D en P1; C sí está en P1 pero no en P3).
    begin
        perform public.cambiar_rol_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a4', 'editor');
        raise exception 'FALLO: se cambió el permiso de quien no es miembro';
    exception when no_data_found then null;
    end;

    begin
        perform public.quitar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b3',
            '00000000-0000-4000-a000-0000000003a3');
        raise exception 'FALLO: se quitó a un miembro de otro proyecto';
    exception when no_data_found then null;
    end;

    -- Cambiar permiso: lector → editor → lector, con su evento cada vez.
    v_respuesta := public.cambiar_rol_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        '00000000-0000-4000-a000-0000000003a3', 'editor');
    assert v_respuesta ->> 'rol' = 'editor' and v_respuesta ->> 'email' = 'verificar-003-c@buildcast.test',
        'FALLO: respuesta de cambiar_rol_miembro_proyecto: ' || v_respuesta::text;

    perform public.cambiar_rol_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        '00000000-0000-4000-a000-0000000003a3', 'lector');

    -- Dejar el mismo permiso no cambia nada ni deja evento.
    v_respuesta := public.cambiar_rol_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        '00000000-0000-4000-a000-0000000003a3', 'lector');
    assert v_respuesta ->> 'rol' = 'lector', 'FALLO: cambiar al mismo permiso';

    assert (select array_agg((valores_anteriores ->> 'rol') || '>' || (valores_nuevos ->> 'rol') order by fecha, id)
            from public.historial_proyecto
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1'
              and accion = 'miembro_rol_cambiado' and origen = 'rpc'
              and entidad_id = '00000000-0000-4000-a000-0000000003a3') @> array['lector>editor', 'editor>lector']
       and (select count(*) from public.historial_proyecto
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1' and accion = 'miembro_rol_cambiado') = 2,
        'FALLO: eventos miembro_rol_cambiado';

    -- Quitar: D entra y sale de P1.
    perform public.agregar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        'verificar-003-d@buildcast.test', 'lector');
    perform public.quitar_miembro_proyecto(
        '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
        '00000000-0000-4000-a000-0000000003a4');

    assert not exists (select 1 from public.proyecto_miembros
                       where proyecto_id = '00000000-0000-4000-b000-0000000003b1'
                         and usuario_id = '00000000-0000-4000-a000-0000000003a4'),
        'FALLO: el miembro quitado sigue en el proyecto';

    assert (select count(*) from public.historial_proyecto
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1'
              and accion = 'miembro_eliminado' and entidad = 'miembro' and origen = 'rpc'
              and entidad_id = '00000000-0000-4000-a000-0000000003a4'
              and valores_nuevos is null
              and valores_anteriores ->> 'rol' = 'lector'
              and valores_anteriores ->> 'email' = 'verificar-003-d@buildcast.test') = 1,
        'FALLO: evento miembro_eliminado';

    -- Un evento por cambio en P1: 3 altas (B, C, D), 2 cambios y 1 baja.
    assert (select count(*) from public.historial_proyecto
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 6,
        'FALLO: el historial de P1 no tiene un evento por cambio';

    -- Estado final de P1: A propietario, B editor, C lector.
    assert (select array_agg(rol order by rol) from public.proyecto_miembros
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = array['editor', 'lector', 'propietario'],
        'FALLO: miembros finales de P1';
end;
$$;

reset role;


-- 4. Si falla el historial, tampoco queda el cambio ----------------------------------------------
-- Un trigger temporal hace fallar cualquier alta en historial_proyecto. El error aborta
-- la llamada completa a la RPC: es lo mismo que ocurre con una petición del backend.

create function public.verificar_003_fallar_historial()
returns trigger
language plpgsql
as $$
begin
    raise exception 'fallo deliberado del historial' using errcode = 'BC003';
end;
$$;

create trigger verificar_003_fallar_historial
    before insert on public.historial_proyecto
    for each row
    execute function public.verificar_003_fallar_historial();

set local role service_role;

do $$
declare
    v_miembros text;
    v_eventos bigint;
begin
    select string_agg(usuario_id::text || '=' || rol, ',' order by usuario_id)
    into v_miembros
    from public.proyecto_miembros
    where proyecto_id = '00000000-0000-4000-b000-0000000003b1';

    select count(*) into v_eventos from public.historial_proyecto;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: se agregó un miembro sin historial';
    exception when sqlstate 'BC003' then null;
    end;

    begin
        perform public.cambiar_rol_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a2', 'lector');
        raise exception 'FALLO: se cambió un permiso sin historial';
    exception when sqlstate 'BC003' then null;
    end;

    begin
        perform public.quitar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            '00000000-0000-4000-a000-0000000003a3');
        raise exception 'FALLO: se quitó un miembro sin historial';
    exception when sqlstate 'BC003' then null;
    end;

    assert (select string_agg(usuario_id::text || '=' || rol, ',' order by usuario_id)
            from public.proyecto_miembros
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = v_miembros,
        'FALLO: la membresía cambió aunque falló el historial';
    assert (select count(*) from public.historial_proyecto) = v_eventos,
        'FALLO: quedó un evento de una operación fallida';
end;
$$;

reset role;

drop trigger verificar_003_fallar_historial on public.historial_proyecto;
drop function public.verificar_003_fallar_historial();


-- 5. Estimaciones con service role (como el backend) ---------------------------------------------

set local role service_role;

do $$
declare
    v_estimacion jsonb := current_setting('verificar.estimacion')::jsonb;
    v_lineas jsonb := current_setting('verificar.lineas')::jsonb;
    v_p1 jsonb := v_estimacion || '{"proyecto_id": "00000000-0000-4000-b000-0000000003b1"}';
    v_creada public.estimaciones;
begin
    -- Propietario y editor generan; la estimación queda a nombre de quien la generó.
    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000003a1', v_p1, v_lineas);
    assert v_creada.usuario_id = '00000000-0000-4000-a000-0000000003a1', 'FALLO: estimación del propietario';

    v_creada := public.crear_estimacion('00000000-0000-4000-a000-0000000003a2', v_p1, v_lineas);
    assert v_creada.usuario_id = '00000000-0000-4000-a000-0000000003a2'
       and v_creada.proyecto_id = '00000000-0000-4000-b000-0000000003b1',
        'FALLO: estimación del editor';
    assert (select count(*) from public.estimacion_partidas where estimacion_id = v_creada.id) = 1,
        'FALLO: líneas de la estimación del editor';

    -- El creador sin fila de miembro también.
    perform public.crear_estimacion(
        '00000000-0000-4000-a000-0000000003a1',
        v_estimacion || '{"proyecto_id": "00000000-0000-4000-b000-0000000003b4"}', v_lineas);

    -- Un lector no genera.
    begin
        perform public.crear_estimacion('00000000-0000-4000-a000-0000000003a3', v_p1, v_lineas);
        raise exception 'FALLO: un lector generó una estimación';
    exception when insufficient_privilege then null;
    end;

    -- B es lector en P3: tampoco ahí, aunque sea editor en P1.
    begin
        perform public.crear_estimacion(
            '00000000-0000-4000-a000-0000000003a2',
            v_estimacion || '{"proyecto_id": "00000000-0000-4000-b000-0000000003b3"}', v_lineas);
        raise exception 'FALLO: B generó una estimación donde es lector';
    exception when insufficient_privilege then null;
    end;

    -- Quien no pertenece, el administrador global, sin usuario o proyecto inexistente: no existe.
    begin
        perform public.crear_estimacion('00000000-0000-4000-a000-0000000003a4', v_p1, v_lineas);
        raise exception 'FALLO: un ajeno generó una estimación';
    exception when no_data_found then null;
    end;

    begin
        perform public.crear_estimacion('00000000-0000-4000-a000-0000000003a5', v_p1, v_lineas);
        raise exception 'FALLO: el administrador global generó una estimación en un proyecto ajeno';
    exception when no_data_found then null;
    end;

    begin
        perform public.crear_estimacion(null, v_p1, v_lineas);
        raise exception 'FALLO: se generó una estimación sin usuario';
    exception when no_data_found then null;
    end;

    begin
        perform public.crear_estimacion(
            '00000000-0000-4000-a000-0000000003a1',
            v_estimacion || '{"proyecto_id": "00000000-0000-4000-b000-0000000003bf"}', v_lineas);
        raise exception 'FALLO: se generó una estimación en un proyecto inexistente';
    exception when no_data_found then null;
    end;

    assert (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2,
        'FALLO: estimaciones guardadas en P1';
end;
$$;

reset role;


-- 6. A: propietario de P1 y P3, creador de P4 ------------------------------------------------------

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000003a1","role":"authenticated"}', true);

do $$
declare
    v_n bigint;
begin
    assert (select array_agg(nombre order by nombre) from public.proyectos where nombre like 'Verificar 003 · P%')
        = array['Verificar 003 · P1', 'Verificar 003 · P3', 'Verificar 003 · P4'],
        'FALLO: proyectos visibles para A';

    assert public.puede_editar_proyecto('00000000-0000-4000-b000-0000000003b1')
       and public.puede_editar_proyecto('00000000-0000-4000-b000-0000000003b4')
       and not public.puede_leer_proyecto('00000000-0000-4000-b000-0000000003b2'),
        'FALLO: permisos de A';

    -- Edita el proyecto y sus partidas.
    update public.proyectos set nombre = 'Verificar 003 · P1' where id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el propietario no pudo editar su proyecto';

    insert into public.proyecto_partidas (id, proyecto_id, categoria_id, nombre, unidad, origen, orden)
    values ('00000000-0000-4000-d000-0000000003d5', '00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · tres', 'gl', 'manual', 3);
    update public.proyecto_partidas set cantidad = 5 where id = '00000000-0000-4000-d000-0000000003d5';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el propietario no pudo editar una partida';
    delete from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d5';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el propietario no pudo eliminar una partida';

    -- P4: el creador sin fila trabaja igual y ve a sus miembros.
    update public.proyectos set comuna = 'Viña del Mar' where id = '00000000-0000-4000-b000-0000000003b4';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el creador sin fila no pudo editar su proyecto';

    insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, origen, orden)
    values ('00000000-0000-4000-b000-0000000003b4', 990003, 'P4 · uno', 'gl', 'manual', 1);

    assert (select count(*) from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b4') = 1
       and (select count(*) from public.historial_proyecto where proyecto_id = '00000000-0000-4000-b000-0000000003b4') = 1
       and (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000003b4') = 1,
        'FALLO: el creador sin fila no ve miembros, historial o estimaciones de su proyecto';

    -- Ve estimaciones, líneas, miembros e historial de P1.
    assert (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2
       and (select count(*) from public.estimacion_partidas ep
            join public.estimaciones e on e.id = ep.estimacion_id
            where e.proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2
       and (select count(*) from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 3
       and (select count(*) from public.historial_proyecto where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 6,
        'FALLO: lecturas del propietario en P1';

    -- Nada de P2.
    assert not exists (select 1 from public.proyecto_partidas where proyecto_id = '00000000-0000-4000-b000-0000000003b2')
       and not exists (select 1 from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b2'),
        'FALLO: A ve datos de un proyecto ajeno';

    -- Ni el propietario escribe miembros ni llama a las RPC de servicio con su token.
    begin
        insert into public.proyecto_miembros (proyecto_id, usuario_id, rol)
        values ('00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-a000-0000000003a4', 'lector');
        raise exception 'FALLO: un usuario escribió proyecto_miembros';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: un usuario ejecutó agregar_miembro_proyecto';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.crear_estimacion(
            '00000000-0000-4000-a000-0000000003a1',
            current_setting('verificar.estimacion')::jsonb || '{"proyecto_id": "00000000-0000-4000-b000-0000000003b1"}',
            current_setting('verificar.lineas')::jsonb);
        raise exception 'FALLO: un usuario ejecutó crear_estimacion';
    exception when insufficient_privilege then null;
    end;
end;
$$;

-- Crear un proyecto con plantilla sigue funcionando y deja a A como propietario.
select public.crear_proyecto_con_plantilla(
    '{"usuario_id": "00000000-0000-4000-a000-0000000003a1", "nombre": "Verificar 003 · nuevo", "comuna": "Quilpué",
      "tipo_obra": "Verificar 003", "materialidad": "Verificar 003", "superficie_m2": 48, "numero_pisos": 1,
      "estandar_terminaciones": "economico"}'::jsonb,
    '00000000-0000-4000-c000-0000000003c3',
    '[{"partida_id": "00000000-0000-4000-c000-0000000003c1", "categoria_id": 990003, "nombre": "Plantilla · uno",
       "unidad": "gl", "cantidad": 1, "orden": 1}]'::jsonb
);

do $$
begin
    assert (select count(*) from public.proyectos p
            join public.proyecto_miembros m on m.proyecto_id = p.id and m.usuario_id = p.usuario_id
            join public.proyecto_partidas pp on pp.proyecto_id = p.id
            where p.nombre = 'Verificar 003 · nuevo' and m.rol = 'propietario' and pp.origen = 'plantilla') = 1,
        'FALLO: crear_proyecto_con_plantilla con las políticas nuevas';

    -- Nadie crea un proyecto a nombre de otro.
    begin
        insert into public.proyectos
            (usuario_id, nombre, comuna, tipo_obra, materialidad, superficie_m2, numero_pisos, estandar_terminaciones)
        values ('00000000-0000-4000-a000-0000000003a2', 'Verificar 003 · ajeno', 'Quilpué', 'x', 'x', 1, 1, 'economico');
        raise exception 'FALLO: se creó un proyecto a nombre de otro';
    exception when insufficient_privilege then null;
    end;
end;
$$;


-- 7. B: editor en P1, propietario de P2, lector en P3 -------------------------------------------------

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000003a2","role":"authenticated"}', true);

do $$
declare
    v_n bigint;
    v_ids uuid[];
begin
    assert (select array_agg(nombre order by nombre) from public.proyectos where nombre like 'Verificar 003 · P%')
        = array['Verificar 003 · P1', 'Verificar 003 · P2', 'Verificar 003 · P3'],
        'FALLO: proyectos visibles para B';

    -- Un rol distinto en cada proyecto.
    assert public.rol_en_proyecto('00000000-0000-4000-b000-0000000003b1') = 'editor'
       and public.rol_en_proyecto('00000000-0000-4000-b000-0000000003b2') = 'propietario'
       and public.rol_en_proyecto('00000000-0000-4000-b000-0000000003b3') = 'lector'
       and public.puede_editar_proyecto('00000000-0000-4000-b000-0000000003b1')
       and public.puede_leer_proyecto('00000000-0000-4000-b000-0000000003b3')
       and not public.puede_editar_proyecto('00000000-0000-4000-b000-0000000003b3'),
        'FALLO: roles de B';

    -- P1 (editor): edita proyecto y partidas, ve estimaciones.
    update public.proyectos set comuna = 'Villa Alemana' where id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el editor no pudo editar el proyecto';

    insert into public.proyecto_partidas (id, proyecto_id, categoria_id, nombre, unidad, origen, orden)
    values ('00000000-0000-4000-d000-0000000003d6', '00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · editor', 'gl', 'manual', 3);
    update public.proyecto_partidas set cantidad = 9 where id = '00000000-0000-4000-d000-0000000003d1';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el editor no pudo editar una partida';
    delete from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d6';
    get diagnostics v_n = row_count;
    assert v_n = 1, 'FALLO: el editor no pudo eliminar una partida';

    assert (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2
       and (select count(*) from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 3,
        'FALLO: lecturas del editor en P1';

    -- Reordena y aplica plantilla en P1.
    select array_agg(id order by orden desc) into v_ids
    from public.proyecto_partidas where proyecto_id = '00000000-0000-4000-b000-0000000003b1';
    perform public.ordenar_partidas_proyecto('00000000-0000-4000-b000-0000000003b1', v_ids);
    assert (select orden from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d2') = 1
       and (select orden from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d1') = 2,
        'FALLO: el editor no pudo reordenar';

    perform public.aplicar_plantilla_proyecto(
        '00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-c000-0000000003c3',
        '[{"partida_id": "00000000-0000-4000-c000-0000000003c1", "categoria_id": 990003, "nombre": "Plantilla · uno",
           "unidad": "gl", "cantidad": 1, "orden": 1}]'::jsonb,
        true);
    assert (select array_agg(origen) from public.proyecto_partidas
            where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = array['plantilla']
       and (select plantilla_id from public.proyectos where id = '00000000-0000-4000-b000-0000000003b1')
           = '00000000-0000-4000-c000-0000000003c3',
        'FALLO: el editor no pudo aplicar la plantilla';

    -- No se apropia del proyecto.
    begin
        update public.proyectos set usuario_id = '00000000-0000-4000-a000-0000000003a2'
        where id = '00000000-0000-4000-b000-0000000003b1';
        raise exception 'FALLO: un editor se puso como creador del proyecto';
    exception when insufficient_privilege then null;
    end;

    -- P3 (lector): lee, pero nada de lo que intenta cambia.
    assert (select count(*) from public.proyecto_partidas where proyecto_id = '00000000-0000-4000-b000-0000000003b3') = 1,
        'FALLO: el lector no ve las partidas';

    update public.proyectos set nombre = 'cambiado' where id = '00000000-0000-4000-b000-0000000003b3';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector editó el proyecto';

    update public.proyecto_partidas set cantidad = 99 where id = '00000000-0000-4000-d000-0000000003d3';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector editó una partida';

    delete from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d3';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector eliminó una partida';

    begin
        insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, origen, orden)
        values ('00000000-0000-4000-b000-0000000003b3', 990003, 'P3 · lector', 'gl', 'manual', 2);
        raise exception 'FALLO: un lector agregó una partida';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.ordenar_partidas_proyecto(
            '00000000-0000-4000-b000-0000000003b3', array['00000000-0000-4000-d000-0000000003d3'::uuid]);
        raise exception 'FALLO: un lector reordenó las partidas';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.aplicar_plantilla_proyecto(
            '00000000-0000-4000-b000-0000000003b3', '00000000-0000-4000-c000-0000000003c3', '[]'::jsonb, true);
        raise exception 'FALLO: un lector aplicó una plantilla';
    exception when insufficient_privilege then null;
    end;

    assert (select nombre from public.proyectos where id = '00000000-0000-4000-b000-0000000003b3') = 'Verificar 003 · P3'
       and (select cantidad from public.proyecto_partidas where id = '00000000-0000-4000-d000-0000000003d3') = 1,
        'FALLO: el proyecto donde B es lector cambió';

    -- P4 no existe para B.
    assert not exists (select 1 from public.proyectos where id = '00000000-0000-4000-b000-0000000003b4'),
        'FALLO: B ve un proyecto del que no es miembro';
end;
$$;


-- 8. C: lector en P1 y P4 ----------------------------------------------------------------------------

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000003a3","role":"authenticated"}', true);

do $$
declare
    v_n bigint;
    v_partida uuid;
begin
    assert (select array_agg(nombre order by nombre) from public.proyectos where nombre like 'Verificar 003 · P%')
        = array['Verificar 003 · P1', 'Verificar 003 · P4'],
        'FALLO: proyectos visibles para C';

    -- Lee todo lo del proyecto.
    select id into v_partida from public.proyecto_partidas
    where proyecto_id = '00000000-0000-4000-b000-0000000003b1' limit 1;
    assert v_partida is not null, 'FALLO: el lector no ve las partidas';

    assert (select count(*) from public.estimaciones where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2
       and (select count(*) from public.estimacion_partidas ep
            join public.estimaciones e on e.id = ep.estimacion_id
            where e.proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 2
       and (select count(*) from public.proyecto_miembros where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 3
       and (select count(*) from public.historial_proyecto where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 6,
        'FALLO: lecturas del lector en P1';

    -- No modifica nada.
    update public.proyectos set nombre = 'cambiado' where id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector editó el proyecto';

    update public.proyecto_partidas set cantidad = 99 where id = v_partida;
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector editó una partida';

    delete from public.proyecto_partidas where id = v_partida;
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un lector eliminó una partida';

    begin
        insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, origen, orden)
        values ('00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · lector', 'gl', 'manual', 9);
        raise exception 'FALLO: un lector agregó una partida';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.ordenar_partidas_proyecto('00000000-0000-4000-b000-0000000003b1', array[v_partida]);
        raise exception 'FALLO: un lector reordenó las partidas';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.aplicar_plantilla_proyecto(
            '00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-c000-0000000003c3', '[]'::jsonb, true);
        raise exception 'FALLO: un lector aplicó una plantilla';
    exception when insufficient_privilege then null;
    end;

    assert (select count(*) from public.proyecto_partidas where proyecto_id = '00000000-0000-4000-b000-0000000003b1') = 1,
        'FALLO: las partidas de P1 cambiaron con un lector';
end;
$$;


-- 9. D (sin proyectos) y ADM (administrador global sin membresía) -----------------------------------

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000003a4","role":"authenticated"}', true);

do $$
declare
    v_n bigint;
begin
    assert not public.es_administrador(), 'FALLO: D es administrador';

    assert not exists (select 1 from public.proyectos where nombre like 'Verificar 003%')
       and not exists (select 1 from public.proyecto_partidas where categoria_id = 990003)
       and not exists (select 1 from public.estimaciones where version_precio = 'verificar-003')
       and not exists (select 1 from public.estimacion_partidas where categoria_id = 990003)
       and not exists (select 1 from public.proyecto_miembros)
       and not exists (select 1 from public.historial_proyecto),
        'FALLO: quien no pertenece a ningún proyecto ve datos de proyectos';

    assert not public.puede_leer_proyecto('00000000-0000-4000-b000-0000000003b1')
       and public.rol_en_proyecto('00000000-0000-4000-b000-0000000003b1') is null,
        'FALLO: D tiene acceso a P1';

    update public.proyectos set nombre = 'cambiado' where id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un ajeno editó un proyecto';

    update public.proyecto_partidas set cantidad = 99 where proyecto_id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: un ajeno editó partidas';

    begin
        insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, origen, orden)
        values ('00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · ajeno', 'gl', 'manual', 9);
        raise exception 'FALLO: un ajeno agregó una partida';
    exception when insufficient_privilege then null;
    end;

    -- Para quien no pertenece, el proyecto no existe.
    begin
        perform public.aplicar_plantilla_proyecto(
            '00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-c000-0000000003c3', '[]'::jsonb, true);
        raise exception 'FALLO: un ajeno aplicó una plantilla';
    exception when no_data_found then null;
    end;

    begin
        perform public.ordenar_partidas_proyecto('00000000-0000-4000-b000-0000000003b1', array[]::uuid[]);
        raise exception 'FALLO: un ajeno reordenó partidas';
    exception when no_data_found then null;
    end;
end;
$$;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-a000-0000000003a5","role":"authenticated"}', true);

do $$
declare
    v_n bigint;
begin
    -- Es administrador global…
    assert public.es_administrador(), 'FALLO: ADM no es administrador';

    -- …y aun así no ve ni toca proyectos de los que no es miembro.
    assert not exists (select 1 from public.proyectos where nombre like 'Verificar 003%')
       and not exists (select 1 from public.proyecto_partidas where categoria_id = 990003)
       and not exists (select 1 from public.estimaciones where version_precio = 'verificar-003')
       and not exists (select 1 from public.estimacion_partidas where categoria_id = 990003)
       and not exists (select 1 from public.proyecto_miembros)
       and not exists (select 1 from public.historial_proyecto),
        'FALLO: el administrador global ve proyectos sin ser miembro';

    assert not public.puede_leer_proyecto('00000000-0000-4000-b000-0000000003b1')
       and not public.puede_editar_proyecto('00000000-0000-4000-b000-0000000003b1'),
        'FALLO: el administrador global tiene acceso a P1';

    update public.proyectos set nombre = 'cambiado' where id = '00000000-0000-4000-b000-0000000003b1';
    get diagnostics v_n = row_count;
    assert v_n = 0, 'FALLO: el administrador global editó un proyecto ajeno';

    begin
        insert into public.proyecto_partidas (proyecto_id, categoria_id, nombre, unidad, origen, orden)
        values ('00000000-0000-4000-b000-0000000003b1', 990003, 'P1 · adm', 'gl', 'manual', 9);
        raise exception 'FALLO: el administrador global agregó una partida en un proyecto ajeno';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.aplicar_plantilla_proyecto(
            '00000000-0000-4000-b000-0000000003b1', '00000000-0000-4000-c000-0000000003c3', '[]'::jsonb, true);
        raise exception 'FALLO: el administrador global aplicó una plantilla en un proyecto ajeno';
    exception when no_data_found then null;
    end;
end;
$$;

reset role;


-- 10. Sin sesión (anon) -----------------------------------------------------------------------------

set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);

do $$
begin
    begin
        perform 1 from public.proyecto_miembros;
        raise exception 'FALLO: anon lee proyecto_miembros';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.puede_leer_proyecto('00000000-0000-4000-b000-0000000003b1');
        raise exception 'FALLO: anon ejecuta puede_leer_proyecto';
    exception when insufficient_privilege then null;
    end;

    begin
        perform public.agregar_miembro_proyecto(
            '00000000-0000-4000-a000-0000000003a1', '00000000-0000-4000-b000-0000000003b1',
            'verificar-003-d@buildcast.test', 'lector');
        raise exception 'FALLO: anon ejecuta agregar_miembro_proyecto';
    exception when insufficient_privilege then null;
    end;
end;
$$;

reset role;


-- Nada de lo anterior queda en la base.
rollback;
