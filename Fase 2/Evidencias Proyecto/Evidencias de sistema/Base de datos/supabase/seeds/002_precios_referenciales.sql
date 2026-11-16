-- Versión referencial 2026-T3-REF con los precios de preciosReferenciales.ts.
-- No provienen de RAM. Requiere 001_catalogo_base.sql.
--
-- Los rendimientos 0.0 (09.05, 10.02) quedan en null, porque la base exige valores > 0.
-- No sobrescribe una versión existente y solo la publica si no hay otra vigente.

begin;

create temp table _precios_referenciales (
    codigo text primary key,
    precio_unitario numeric not null,
    rendimiento_mo numeric
) on commit drop;

insert into _precios_referenciales (codigo, precio_unitario, rendimiento_mo)
values
    ('01.01', 1800000, 16),
    ('01.02', 12000, 0.5),
    ('01.03', 1200, 0.08),
    ('01.04', 650000, 8),
    ('02.01', 900, 0.05),
    ('02.02', 7500, 1.2),
    ('02.03', 14000, 0.8),
    ('02.04', 11000, 0.15),
    ('03.01', 78000, 2),
    ('03.02', 95000, 5),
    ('03.03', 98000, 6.5),
    ('03.04', 1350, 0.06),
    ('03.05', 9500, 1.1),
    ('03.06', 1400, 0.05),
    ('04.01', 16500, 0.9),
    ('04.02', 28000, 1.8),
    ('04.03', 105000, 9),
    ('04.04', 1350, 0.07),
    ('04.05', 11000, 1.4),
    ('04.06', 52000, 3.2),
    ('04.07', 22000, 1.2),
    ('04.08', 850000, 40),
    ('05.01', 19000, 1.1),
    ('05.02', 14500, 0.6),
    ('05.03', 9800, 0.35),
    ('05.04', 6200, 0.25),
    ('05.05', 11500, 0.7),
    ('06.01', 6800, 0.9),
    ('06.02', 8900, 1.1),
    ('06.03', 15500, 1),
    ('06.04', 12000, 0.8),
    ('06.05', 14000, 0.45),
    ('06.06', 13500, 0.9),
    ('06.07', 3200, 0.3),
    ('06.08', 4100, 0.35),
    ('06.09', 285000, 3),
    ('06.10', 195000, 2.5),
    ('07.01', 165000, 1.2),
    ('07.02', 320000, 4),
    ('07.03', 95000, 2.5),
    ('07.04', 28000, 0.5),
    ('08.01', 62000, 3.5),
    ('08.02', 78000, 4),
    ('08.03', 185000, 3),
    ('08.04', 420000, 6),
    ('08.05', 380000, 8),
    ('09.01', 750000, 6),
    ('09.02', 260000, 5),
    ('09.03', 26000, 1.2),
    ('09.04', 32000, 0.6),
    ('09.05', 280000, null),  -- rendimiento 0.0 en TypeScript
    ('10.01', 22000, 1),
    ('10.02', 180000, null),  -- rendimiento 0.0 en TypeScript
    ('11.01', 18000, 1),
    ('11.02', 42000, 1.6),
    ('11.03', 12000, 0.5),
    ('12.01', 900, 0.15),
    ('12.02', 450000, 6);

do $$
declare
    c_version constant text := '2026-T3-REF';
    c_fuente constant text := 'Referencial de mercado · Región de Valparaíso · no proviene de RAM';
    c_fuente_precio constant text := 'Referencial de mercado 2026-T3';
    v_version public.versiones_precios;
    v_faltantes text;
begin
    select string_agg(b.codigo, ', ' order by b.codigo)
    into v_faltantes
    from _precios_referenciales b
    left join public.partidas p on p.codigo = b.codigo
    where p.id is null;

    if v_faltantes is not null then
        raise exception 'Faltan partidas (%): ejecuta 001_catalogo_base.sql.', v_faltantes;
    end if;

    select * into v_version
    from public.versiones_precios
    where version = c_version;

    if found then
        if v_version.fuente is distinct from c_fuente then
            raise exception 'Ya existe la versión % con fuente "%": no la creó esta semilla y no se modifica.',
                c_version, coalesce(v_version.fuente, 'sin fuente');
        end if;

        raise notice 'La versión % ya existe: se conservan sus precios.', c_version;
    else
        insert into public.versiones_precios (version, trimestre, fuente)
        values (c_version, '2026-T3', c_fuente)
        returning * into v_version;

        insert into public.precios_partida
            (partida_id, version_precio_id, precio_unitario, rendimiento_mo, fuente)
        select p.id, v_version.id, b.precio_unitario, b.rendimiento_mo, c_fuente_precio
        from _precios_referenciales b
        join public.partidas p on p.codigo = b.codigo;
    end if;

    -- Sin versión vigente el motor no puede estimar.
    if not exists (select 1 from public.versiones_precios where vigente) then
        update public.versiones_precios
        set vigente = true
        where id = v_version.id;
    end if;
end;
$$;

commit;
