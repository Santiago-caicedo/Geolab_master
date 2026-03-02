"""
Script para crear las 8 áreas del Sistema de Calidad.
Ejecutar con: python manage.py shell < crear_areas_calidad.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from calidad.models import AreaCalidad

areas = [
    (1, 'Gestión Directiva', 'bi-briefcase'),
    (2, 'Gestión Comercial', 'bi-cart'),
    (3, 'Gestión de Compras', 'bi-bag'),
    (4, 'Gestión Humana', 'bi-people'),
    (5, 'Gestión de Mantenimiento', 'bi-wrench'),
    (6, 'Gestión Técnica', 'bi-clipboard2-check'),
    (7, 'Gestión SST', 'bi-shield-check'),
    (8, 'Gestión Vial', 'bi-truck'),
]

creadas = 0
for num, nombre, icono in areas:
    _, created = AreaCalidad.objects.get_or_create(
        numero=num,
        defaults={'nombre': nombre, 'icono': icono}
    )
    estado = 'CREADA' if created else 'ya existia'
    creadas += int(created)
    print(f'  {num}. {nombre} -> {estado}')

print(f'\nListo: {creadas} areas nuevas, {len(areas) - creadas} ya existian.')
