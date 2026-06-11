"""
Clasificador de geometría de especímenes.

Cada dimensión predefinida mapea directamente a una geometría.
El remitente selecciona de un dropdown, eliminando ambigüedad.
"""

GEOMETRIA_CILINDRO = 'cilindro'
GEOMETRIA_CUBO = 'cubo'
GEOMETRIA_PRISMA = 'prisma'

GEOMETRIA_CHOICES = [
    (GEOMETRIA_CILINDRO, 'Cilindro'),
    (GEOMETRIA_CUBO, 'Cubo'),
    (GEOMETRIA_PRISMA, 'Prisma'),
]

# Dimensiones predefinidas de especímenes.
# Cada opción mapea a una geometría específica — sin ambigüedad.
DIMENSION_ESPECIMEN_CHOICES = [
    ('', '-- Seleccionar --'),
    ('3_pulg', '3" (Cilindro)'),
    ('4_pulg', '4" (Cilindro)'),
    ('6_pulg', '6" (Cilindro)'),
    ('50_mm', '50mm (Cubo)'),
    ('15x15_cm', '15x15cm (Viga)'),
]

# Mapeo dimensión → geometría
DIMENSION_A_GEOMETRIA = {
    '3_pulg': GEOMETRIA_CILINDRO,
    '4_pulg': GEOMETRIA_CILINDRO,
    '6_pulg': GEOMETRIA_CILINDRO,
    '50_mm': GEOMETRIA_CUBO,
    '15x15_cm': GEOMETRIA_PRISMA,
}

# Etiquetas legibles para mostrar en tablas/reportes
DIMENSION_DISPLAY = {
    '3_pulg': '3"',
    '4_pulg': '4"',
    '6_pulg': '6"',
    '50_mm': '50mm',
    '15x15_cm': '15×15cm',
}


def clasificar_geometria(dimension_especimen, diametro_longitud=None, unidad_diametro=None):
    """
    Clasifica la geometría del espécimen.

    Usa el campo dimension_especimen (nuevo, predefinido) si existe.
    Fallback a diametro_longitud + unidad_diametro para datos legacy.

    Returns:
        str - tipo de geometría (cilindro, cubo, prisma)
    """
    # Nuevo sistema: lookup directo
    if dimension_especimen:
        return DIMENSION_A_GEOMETRIA.get(dimension_especimen, GEOMETRIA_CILINDRO)

    # Legacy: clasificar por texto libre + unidad (datos existentes)
    valor = (diametro_longitud or '').strip().lower()
    unidad = (unidad_diametro or '').strip().lower()

    if not valor:
        return GEOMETRIA_CILINDRO

    if unidad == 'pulg':
        return GEOMETRIA_CILINDRO

    # Formato AxB
    if 'x' in valor:
        partes = valor.split('x')
        if len(partes) == 2:
            try:
                a = float(partes[0].strip())
                b = float(partes[1].strip())
            except (ValueError, TypeError):
                return GEOMETRIA_CILINDRO

            if unidad == 'cm':
                a_mm, b_mm = a * 10, b * 10
            elif unidad == 'mm':
                a_mm, b_mm = a, b
            else:
                return GEOMETRIA_CILINDRO

            if abs(a_mm - 50) < 5 and abs(b_mm - 50) < 5:
                return GEOMETRIA_CUBO
            if abs(a_mm - 150) < 10 and abs(b_mm - 150) < 10:
                return GEOMETRIA_PRISMA

        return GEOMETRIA_CILINDRO

    # Valor numérico simple
    try:
        num = float(valor)
    except (ValueError, TypeError):
        return GEOMETRIA_CILINDRO

    if unidad == 'cm':
        num_mm = num * 10
    elif unidad == 'mm':
        num_mm = num
    else:
        return GEOMETRIA_CILINDRO

    if abs(num_mm - 50) < 5:
        return GEOMETRIA_CUBO
    if abs(num_mm - 150) < 10:
        return GEOMETRIA_PRISMA

    return GEOMETRIA_CILINDRO
