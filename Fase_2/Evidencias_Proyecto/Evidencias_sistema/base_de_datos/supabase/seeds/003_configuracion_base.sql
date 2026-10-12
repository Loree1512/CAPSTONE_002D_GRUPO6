-- Configuración inicial: CONFIGURACION_BASE de configuracion.ts. Requiere 001_schema_buildcast.sql.

insert into public.parametros_calculo (clave, valor, descripcion)
values
    ('valor_hora_hombre', '9000',
        'Valor de la hora hombre, CLP neto. Referencial: el motor no lo usa.'),

    ('gastos_generales_pct', '12',
        'Gastos generales por defecto, % sobre el costo directo.'),

    ('utilidad_pct', '10',
        'Utilidad por defecto, % sobre el costo directo.'),

    ('factores_comuna', '{
        "Viña del Mar": 1.05,
        "Valparaíso": 1.04,
        "Concón": 1.06,
        "Quilpué": 1.00,
        "Villa Alemana": 0.99,
        "Limache": 0.98,
        "Olmué": 1.00,
        "Quillota": 0.98,
        "Casablanca": 1.02
    }',
        'Factor por comuna, opcional por estimación. Comuna sin factor = 1.'),

    ('tramos_pisos', '[
        {"desde": 1, "hasta": 1, "factor": 1.00},
        {"desde": 2, "hasta": 2, "factor": 1.05},
        {"desde": 3, "hasta": 99, "factor": 1.12}
    ]',
        'Factor por número de pisos, opcional por estimación. Se usa el primer tramo que contiene el número de pisos; sin tramo = 1.'),

    ('factores_estandar', '{"economico": 0.85, "medio": 1.00, "alto": 1.28}',
        'Factor por estándar de terminaciones. Reservado: el motor no lo aplica.'),

    ('factores_materialidad', '{
        "Albañilería confinada": 0.94,
        "Hormigón armado": 1.03,
        "Tabiquería de madera": 0.97,
        "Estructura metálica": 1.02
    }',
        'Factor por materialidad. Reservado: el motor no lo aplica.'),

    ('capitulos_estandar', '["06", "07"]',
        'Capítulos a los que se aplicaría el factor de estándar. Reservado.'),

    ('capitulos_materialidad', '["03", "04"]',
        'Capítulos a los que se aplicaría el factor de materialidad. Reservado.')
on conflict (clave) do nothing;
