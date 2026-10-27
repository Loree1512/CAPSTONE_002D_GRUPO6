-- Catálogo base: 12 categorías y 58 partidas (catalogoBase.ts). Requiere 001_schema_buildcast.sql.
-- Se puede ejecutar varias veces; falla si un código ya existe con otros datos.

begin;

insert into public.categorias_partida (codigo, nombre, orden)
values
    ('01', 'Obras preliminares', 1),
    ('02', 'Movimiento de tierras', 2),
    ('03', 'Fundaciones', 3),
    ('04', 'Obra gruesa y estructura', 4),
    ('05', 'Techumbre', 5),
    ('06', 'Terminaciones', 6),
    ('07', 'Puertas y ventanas', 7),
    ('08', 'Instalación sanitaria', 8),
    ('09', 'Instalación eléctrica', 9),
    ('10', 'Instalación de gas', 10),
    ('11', 'Obras exteriores', 11),
    ('12', 'Aseo y entrega', 12)
on conflict (codigo) do nothing;

create temp table _catalogo_base (
    categoria_codigo text not null,
    codigo text primary key,
    nombre text not null,
    unidad text not null
) on commit drop;

insert into _catalogo_base (categoria_codigo, codigo, nombre, unidad)
values
    ('01', '01.01', 'Instalación de faenas', 'gl'),
    ('01', '01.02', 'Cierre provisorio de obra', 'ml'),
    ('01', '01.03', 'Trazado y niveles', 'm2'),
    ('01', '01.04', 'Empalme provisorio de agua y electricidad', 'gl'),
    ('02', '02.01', 'Escarpe y despeje de terreno', 'm2'),
    ('02', '02.02', 'Excavación para fundaciones', 'm3'),
    ('02', '02.03', 'Relleno compactado', 'm3'),
    ('02', '02.04', 'Retiro de excedentes', 'm3'),
    ('03', '03.01', 'Emplantillado', 'm3'),
    ('03', '03.02', 'Hormigón de cimientos', 'm3'),
    ('03', '03.03', 'Sobrecimiento', 'm3'),
    ('03', '03.04', 'Enfierradura de fundaciones', 'kg'),
    ('03', '03.05', 'Moldaje de fundaciones', 'm2'),
    ('03', '03.06', 'Polietileno y aislación de humedad', 'm2'),
    ('04', '04.01', 'Radier', 'm2'),
    ('04', '04.02', 'Albañilería de ladrillo', 'm2'),
    ('04', '04.03', 'Pilares y cadenas de hormigón armado', 'm3'),
    ('04', '04.04', 'Enfierradura de estructura', 'kg'),
    ('04', '04.05', 'Moldaje de estructura', 'm2'),
    ('04', '04.06', 'Losa de hormigón armado', 'm2'),
    ('04', '04.07', 'Tabiquería estructural', 'm2'),
    ('04', '04.08', 'Escalera', 'un'),
    ('05', '05.01', 'Estructura de cubierta', 'm2'),
    ('05', '05.02', 'Cubierta', 'm2'),
    ('05', '05.03', 'Hojalatería y canales', 'ml'),
    ('05', '05.04', 'Aislación térmica de cubierta', 'm2'),
    ('05', '05.05', 'Cielo interior', 'm2'),
    ('06', '06.01', 'Estuco interior', 'm2'),
    ('06', '06.02', 'Estuco o revestimiento exterior', 'm2'),
    ('06', '06.03', 'Tabiquería no estructural y revestimiento', 'm2'),
    ('06', '06.04', 'Pavimento cerámico', 'm2'),
    ('06', '06.05', 'Piso flotante o similar', 'm2'),
    ('06', '06.06', 'Revestimiento cerámico de muros', 'm2'),
    ('06', '06.07', 'Pintura interior', 'm2'),
    ('06', '06.08', 'Pintura exterior', 'm2'),
    ('06', '06.09', 'Muebles de cocina', 'ml'),
    ('06', '06.10', 'Closets y muebles fijos', 'ml'),
    ('07', '07.01', 'Ventanas', 'm2'),
    ('07', '07.02', 'Puerta de acceso', 'un'),
    ('07', '07.03', 'Puertas interiores', 'un'),
    ('07', '07.04', 'Quincallería', 'un'),
    ('08', '08.01', 'Red de agua fría y caliente', 'pto'),
    ('08', '08.02', 'Red de alcantarillado', 'pto'),
    ('08', '08.03', 'Artefactos sanitarios y grifería', 'un'),
    ('08', '08.04', 'Sistema de agua caliente', 'un'),
    ('08', '08.05', 'Cámaras y arranque domiciliario', 'un'),
    ('09', '09.01', 'Empalme eléctrico', 'gl'),
    ('09', '09.02', 'Tablero general', 'un'),
    ('09', '09.03', 'Centros y enchufes', 'pto'),
    ('09', '09.04', 'Artefactos de iluminación', 'un'),
    ('09', '09.05', 'Certificación SEC TE1', 'gl'),
    ('10', '10.01', 'Red interior de gas', 'ml'),
    ('10', '10.02', 'Certificación SEC de gas', 'gl'),
    ('11', '11.01', 'Radier exterior y terrazas', 'm2'),
    ('11', '11.02', 'Cierre perimetral', 'ml'),
    ('11', '11.03', 'Paisajismo y áreas verdes', 'm2'),
    ('12', '12.01', 'Aseo final de obra', 'm2'),
    ('12', '12.02', 'Retiro de escombros', 'gl');

do $$
declare
    v_faltantes text;
begin
    select string_agg(distinct b.categoria_codigo, ', ')
    into v_faltantes
    from _catalogo_base b
    left join public.categorias_partida c on c.codigo = b.categoria_codigo
    where c.id is null;

    if v_faltantes is not null then
        raise exception 'Faltan categorías (%): revisa categorias_partida.', v_faltantes;
    end if;
end;
$$;

insert into public.partidas (categoria_id, codigo, nombre, unidad, es_base, vigente)
select c.id, b.codigo, b.nombre, b.unidad, true, true
from _catalogo_base b
join public.categorias_partida c on c.codigo = b.categoria_codigo
on conflict (codigo) do nothing;

-- Un código base ocupado por otra partida dejaría precios mal asignados.
do $$
declare
    v_conflictos text;
begin
    select string_agg(p.codigo, ', ' order by p.codigo)
    into v_conflictos
    from public.partidas p
    join _catalogo_base b on b.codigo = p.codigo
    join public.categorias_partida c on c.id = p.categoria_id
    where p.nombre <> b.nombre
       or p.unidad <> b.unidad
       or c.codigo <> b.categoria_codigo
       or not p.es_base;

    if v_conflictos is not null then
        raise exception 'Estas partidas ya existen con otros datos: %. Revísalas antes de sembrar.', v_conflictos;
    end if;
end;
$$;

commit;
