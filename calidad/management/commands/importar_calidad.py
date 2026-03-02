import os
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.files import File

from calidad.models import AreaCalidad, Carpeta, Documento


# Iconos por defecto para cada área
ICONOS_AREAS = {
    1: 'bi-briefcase',       # Gestión Directiva
    2: 'bi-cart',             # Gestión Comercial
    3: 'bi-bag',              # Gestión de Compras
    4: 'bi-people',           # Gestión Humana
    5: 'bi-wrench',           # Gestión de Mantenimiento
    6: 'bi-clipboard2-check', # Gestión Técnica
    7: 'bi-shield-check',     # Gestión SST
    8: 'bi-truck',            # Gestión Vial
}


class Command(BaseCommand):
    help = 'Importa la estructura de carpetas del Sistema de Calidad desde el filesystem.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ruta',
            type=str,
            default='datos_calidad',
            help='Ruta a la carpeta raíz de datos de Calidad (relativa al proyecto o absoluta).'
        )
        parser.add_argument(
            '--con-archivos',
            action='store_true',
            default=False,
            help='Si se incluye, importa también los archivos (no solo carpetas).'
        )

    def handle(self, *args, **options):
        ruta_base = Path(options['ruta'])
        if not ruta_base.is_absolute():
            from django.conf import settings
            ruta_base = Path(settings.BASE_DIR) / ruta_base

        con_archivos = options['con_archivos']

        if not ruta_base.exists():
            self.stderr.write(self.style.ERROR(f'No se encontró la carpeta: {ruta_base}'))
            return

        self.stdout.write(f'Importando desde: {ruta_base}')
        self.stdout.write(f'Modo: {"con archivos" if con_archivos else "solo estructura"}')

        areas_creadas = 0
        carpetas_creadas = 0
        archivos_importados = 0

        # Recorrer subdirectorios de primer nivel (las 8 áreas)
        for item in sorted(ruta_base.iterdir()):
            if not item.is_dir():
                continue

            # Parsear "1. Gestión Directiva" → numero=1, nombre="Gestión Directiva"
            match = re.match(r'^(\d+)\.\s*(.+)$', item.name)
            if not match:
                self.stdout.write(self.style.WARNING(f'  Ignorando (no matchea patrón): {item.name}'))
                continue

            numero = int(match.group(1))
            nombre = match.group(2).strip()
            # Normalizar tildes inconsistentes del filesystem
            nombre = nombre.replace('ò', 'ó').replace('è', 'é')

            icono = ICONOS_AREAS.get(numero, 'bi-folder')

            area, created = AreaCalidad.objects.get_or_create(
                numero=numero,
                defaults={'nombre': nombre, 'icono': icono}
            )
            if created:
                areas_creadas += 1
                self.stdout.write(self.style.SUCCESS(f'  Área creada: {area}'))
            else:
                self.stdout.write(f'  Área existente: {area}')

            # Importar subcarpetas recursivamente
            c, a = self._importar_carpeta_recursiva(
                item, area, padre=None, con_archivos=con_archivos
            )
            carpetas_creadas += c
            archivos_importados += a

        self.stdout.write(self.style.SUCCESS(
            f'\nResumen: {areas_creadas} áreas, {carpetas_creadas} carpetas'
            + (f', {archivos_importados} archivos' if con_archivos else '')
        ))

    def _importar_carpeta_recursiva(self, path, area, padre, con_archivos):
        """Recorre recursivamente un directorio creando Carpetas (y opcionalmente Documentos)."""
        carpetas_creadas = 0
        archivos_importados = 0

        # Separar directorios y archivos, ordenar
        subdirs = sorted([p for p in path.iterdir() if p.is_dir()])
        archivos = sorted([p for p in path.iterdir() if p.is_file()]) if con_archivos else []

        for idx, subdir in enumerate(subdirs):
            nombre = subdir.name
            carpeta, created = Carpeta.objects.get_or_create(
                nombre=nombre,
                area=area,
                padre=padre,
                defaults={'orden': idx}
            )
            if created:
                carpetas_creadas += 1

            # Recurrir a subcarpetas
            c, a = self._importar_carpeta_recursiva(
                subdir, area, padre=carpeta, con_archivos=con_archivos
            )
            carpetas_creadas += c
            archivos_importados += a

        # Importar archivos si se pidió
        for archivo_path in archivos:
            nombre = archivo_path.name
            if Documento.objects.filter(nombre=nombre, carpeta=padre).exists():
                continue
            try:
                with open(archivo_path, 'rb') as f:
                    doc = Documento(
                        nombre=nombre,
                        carpeta=padre,
                        tamano_bytes=archivo_path.stat().st_size,
                    )
                    doc.archivo.save(nombre, File(f), save=True)
                    archivos_importados += 1
            except Exception as e:
                self.stderr.write(self.style.WARNING(f'    Error importando {nombre}: {e}'))

        return carpetas_creadas, archivos_importados
