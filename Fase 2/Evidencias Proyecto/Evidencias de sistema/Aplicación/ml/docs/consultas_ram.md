# Consultas pendientes para RAM Arquitectura y Construcción (HU-13)

Preparadas el 2026-10-29 a partir de la revisión de los 17 presupuestos. Los ids de caso (R01–R17) corresponden a `ml/data/processed/presupuestos_reales.csv`. Al enviar las consultas, identificar cada caso por su obra y fecha; no usar los ids internos ni compartir este archivo con terceros.

## A. Plazos reales (prioridad máxima)

1. **Fechas reales de inicio y término** de cada obra que se haya ejecutado, en especial las cotizadas entre noviembre de 2025 y mayo de 2026: R02, R03, R04, R05, R06, R09, R11, R13, R14, R15, R16, R17. También R01 a R17 si alguna más se ejecutó. Si hubo interrupciones (lluvia, materiales, cambios del cliente), indicar cuántos días.
2. ¿Qué obras **no se ejecutaron** o cambiaron de alcance respecto del presupuesto?
3. **Plazo ofertado o acordado** de los casos que dicen "a acordar" o no lo indican:
   - R01: ampliación de vivienda en Villa Alemana, 19-05-2026;
   - R12: remodelación de baño en Reñaca, 24-09-2026;
   - R15: mantención de vivienda en Mantagua, 31-03-2026.
4. Cuando el presupuesto dice "plazo de entrega N días" o "N semanas", ¿son **días corridos o hábiles**? BuildCast los usa como corridos.
5. R08 (local comercial, La Ligua): el plazo dice "hasta 5 semanas como máximo". ¿Cuál fue o es el plazo esperado?

## B. Variables del proyecto

6. **Número de pisos** construidos o intervenidos y **estándar de terminaciones** (económico / medio / alto) de los casos de edificación: R01, R08, R11, R17. Si es posible, también del resto.
7. **Superficie intervenida (m²)** de los casos que no la informan: R02, R04, R05, R07, R09, R10, R12, R13, R14, R15, R16. Confirmar además las superficies aproximadas de R01 (~50 m²), R11 (~30 m²) y R17 (50 m², deducida de la partida de piso).
8. ¿Cómo clasifica RAM el estándar de terminaciones? ¿Qué materiales o partidas lo definen?

## C. Costos e IVA

9. **R07** (restauración de cabaña, Laguna Verde): ¿el total de $3.100.000 incluye IVA o es neto?
10. **R08** (local comercial, La Ligua):
    - El IVA impreso ($2.228.395) no es el 19% del neto ($9.500.000, que daría $1.805.000); coincide con el 19% del total. ¿Cuál fue el monto facturado?
    - El documento dice "incluye mano de obra sin materiales", pero tiene una partida de materiales de $5.000.000. ¿El cliente compró los materiales?
    - ¿Gastos generales y utilidad en 0% es correcto?
11. En general, ¿los presupuestos con "IVA $0" se emiten sin IVA (por ejemplo, con boleta) o el IVA se agrega aparte?
12. R10 (reparación de vivienda, Villa Alemana): ¿gastos generales y utilidad en 0% es correcto?

## D. Fechas, comunas y revisiones

13. **R07**: ¿cuál es la fecha del presupuesto y la comuna exacta de la cabaña? (Se asumió Valparaíso por Laguna Verde.)
14. **R17** (alteración de dormitorios y espacios comunes, Valparaíso): la fecha está escrita "10/011/2025". ¿Es el 10 de noviembre de 2025?
15. Fechas que admiten dos lecturas, que se tomaron como día/mes; confirmar:
    - R02: 09/02/2026, 9 de febrero;
    - R06: 05/02/2026, 5 de febrero;
    - R09: 09/03/2026, 9 de marzo.
16. **Revisiones distintas entre el nombre de archivo y el documento.** ¿Cuál es la revisión final y si existen otras revisiones con distinto plazo o costo?
    - R03: archivo REV-A, documento REV-01;
    - R06: archivo REV-01, documento REV-04;
    - R09: archivo REV-A, documento REV-01;
    - R11: archivo REV-A1, documento REV-01;
    - R13: archivo REV0, documento REV-02;
    - R14: archivo rev A, documento REV-01;
    - R15: archivo rev A2, documento REV-02;
    - R16: archivo REV-A, documento REV-01.
17. **Títulos de plantilla:** R05 (muro divisorio, Recreo) y R06 (radier, Mantagua) dicen "PRESUPUESTO PROYECTO COBERTIZO ESTACIONAMIENTO". Confirmar que es solo un error de plantilla.

## E. Otros

18. ¿Hay más presupuestos o registros de obras (aunque sean informales: planillas, mensajes, facturas con fechas) que permitan reconstruir plazos ejecutados?
19. ¿Cuántas personas trabajaron en cada obra, aproximadamente? (El tamaño de la cuadrilla explica gran parte del plazo; serviría para una variable futura.)

## F. Casos que deciden el modelo de plazo (agregadas el 2026-11-01)

20. **R05** (muro divisor de madera, Recreo, 15-11-2025, ~14,6 UF): el plazo dice 2 semanas (14 días). ¿Es el plazo real habitual para un trabajo de ese tamaño, o es una errata? ¿Hubo algo que lo alargara, como espera de materiales o coordinación con el cliente? Es el caso que más se aleja de la relación entre costo y plazo, y por sí solo fija el extremo superior del intervalo que muestra BuildCast.
21. **R08** (local comercial, La Ligua, 24-09-2026): el documento dice "hasta 5 semanas como máximo". ¿Cuál fue o es el plazo real o esperado? Amplía la consulta 5. Hoy se usa 35 días como cota, y ese valor decide la comparación entre los dos métodos evaluados (regla por costo frente a regresión).
