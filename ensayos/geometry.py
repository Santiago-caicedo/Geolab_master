"""
Clasificador de geometría de especímenes.

Cada dimensión predefinida mapea directamente a una geometría.
El remitente selecciona de un dropdown, eliminando ambigüedad.
"""

GEOMETRIA_CILINDRO = 'cilindro'
GEOMETRIA_CUBO = 'cubo'
GEOMETRIA_PRISMA = 'prisma'
GEOMETRIA_ACERO = 'acero'   # varilla / malla electrosoldada (no genera hoja de trabajo)

GEOMETRIA_CHOICES = [
    (GEOMETRIA_CILINDRO, 'Cilindro'),
    (GEOMETRIA_CUBO, 'Cubo'),
    (GEOMETRIA_PRISMA, 'Prisma'),
    (GEOMETRIA_ACERO, 'Acero (varilla/malla)'),
]

# Dimensiones de especímenes de concreto (cilindro / cubo / viga).
DIMENSION_CONCRETO_CHOICES = [
    ('3_pulg', '3" (Cilindro)'),
    ('4_pulg', '4" (Cilindro)'),
    ('6_pulg', '6" (Cilindro)'),
    ('50_mm', '50mm (Cubo)'),
    ('15x15_cm', '15x15cm (Viga)'),
]

# Diámetros de acero (varilla / malla electrosoldada).
DIMENSION_ACERO_CHOICES = [
    ('1_4_pulg', '1/4"'),
    ('3_8_pulg', '3/8"'),
    ('1_2_pulg', '1/2"'),
    ('5_8_pulg', '5/8"'),
    ('3_4_pulg', '3/4"'),
    ('7_8_pulg', '7/8"'),
    ('1_pulg', '1"'),
    ('1_1_4_pulg', '1 1/4"'),
]

# Choices completas del campo. El formulario muestra el subconjunto correcto
# (concreto vs acero) según el tipo de muestra elegido (vía JS).
DIMENSION_ESPECIMEN_CHOICES = (
    [('', '-- Seleccionar --')] + DIMENSION_CONCRETO_CHOICES + DIMENSION_ACERO_CHOICES
)

# Mapeo dimensión → geometría
DIMENSION_A_GEOMETRIA = {
    '3_pulg': GEOMETRIA_CILINDRO,
    '4_pulg': GEOMETRIA_CILINDRO,
    '6_pulg': GEOMETRIA_CILINDRO,
    '50_mm': GEOMETRIA_CUBO,
    '15x15_cm': GEOMETRIA_PRISMA,
    '1_4_pulg': GEOMETRIA_ACERO,
    '3_8_pulg': GEOMETRIA_ACERO,
    '1_2_pulg': GEOMETRIA_ACERO,
    '5_8_pulg': GEOMETRIA_ACERO,
    '3_4_pulg': GEOMETRIA_ACERO,
    '7_8_pulg': GEOMETRIA_ACERO,
    '1_pulg': GEOMETRIA_ACERO,
    '1_1_4_pulg': GEOMETRIA_ACERO,
}

# Etiquetas legibles para mostrar en tablas/reportes
DIMENSION_DISPLAY = {
    '3_pulg': '3"',
    '4_pulg': '4"',
    '6_pulg': '6"',
    '50_mm': '50mm',
    '15x15_cm': '15×15cm',
    '1_4_pulg': '1/4"',
    '3_8_pulg': '3/8"',
    '1_2_pulg': '1/2"',
    '5_8_pulg': '5/8"',
    '3_4_pulg': '3/4"',
    '7_8_pulg': '7/8"',
    '1_pulg': '1"',
    '1_1_4_pulg': '1 1/4"',
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
