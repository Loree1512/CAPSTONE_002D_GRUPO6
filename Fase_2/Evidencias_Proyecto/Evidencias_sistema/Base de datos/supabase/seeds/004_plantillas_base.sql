-- Plantillas de presupuesto: las 12 combinaciones de tipo de obra × materialidad, vacías.
-- Sus partidas se configuran desde Administración → Plantillas. Requiere 001_schema_buildcast.sql.

insert into public.plantillas_presupuesto (nombre, tipo_obra, materialidad)
select t.tipo_obra || ' · ' || m.materialidad, t.tipo_obra, m.materialidad
from (values
        ('Vivienda unifamiliar', 1),
        ('Ampliación', 2),
        ('Edificación habitacional', 3)
     ) as t(tipo_obra, orden_tipo)
cross join (values
        ('Albañilería confinada', 1),
        ('Hormigón armado', 2),
        ('Tabiquería de madera', 3),
        ('Estructura metálica', 4)
     ) as m(materialidad, orden_material)
where not exists (
    select 1
    from public.plantillas_presupuesto p
    where p.tipo_obra = t.tipo_obra
      and p.materialidad = m.materialidad
)
order by t.orden_tipo, m.orden_material;
