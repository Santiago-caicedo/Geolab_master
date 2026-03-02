"""
Script para crear las 8 areas y 302 carpetas del Sistema de Calidad.
Ejecutar con: python crear_areas_calidad.py
"""
import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from calidad.models import AreaCalidad, Carpeta

# Leer estructura desde JSON
script_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(script_dir, 'estructura_calidad.json')

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

areas_creadas = 0
carpetas_creadas = 0


def crear_carpetas_recursivo(carpetas_data, area, padre=None):
    global carpetas_creadas
    for c in carpetas_data:
        carpeta, created = Carpeta.objects.get_or_create(
            nombre=c['nombre'],
            area=area,
            padre=padre,
            defaults={'orden': c.get('orden', 0)}
        )
        if created:
            carpetas_creadas += 1
        if c.get('hijos'):
            crear_carpetas_recursivo(c['hijos'], area, padre=carpeta)


for area_data in data:
    area, created = AreaCalidad.objects.get_or_create(
        numero=area_data['numero'],
        defaults={
            'nombre': area_data['nombre'],
            'icono': area_data['icono'],
        }
    )
    estado = 'CREADA' if created else 'ya existia'
    areas_creadas += int(created)
    print(f'  {area} -> {estado}')

    crear_carpetas_recursivo(area_data.get('carpetas', []), area)

print(f'\nListo: {areas_creadas} areas, {carpetas_creadas} carpetas creadas.')
