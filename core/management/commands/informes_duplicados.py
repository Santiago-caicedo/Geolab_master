"""
Informes repetidos: subidos a mano en el portal y traídos también de WordPress.

    python manage.py informes_duplicados                      # SOLO muestra (no cambia nada)
    python manage.py informes_duplicados --aplicar            # borra las copias de WordPress
    python manage.py informes_duplicados --sin-comparar       # no mira el tamaño de los PDF

Se conserva SIEMPRE la que subió el laboratorio en el portal; se borra la copia de WordPress, se
deja en InformeEliminado (bitácora + la sincronización no la vuelve a traer) y se borra su PDF
del almacenamiento si ningún otro informe lo usa.

Se borra solo lo seguro: mismo título en la misma obra (o en otra obra de la misma empresa con
el mismo código, las obras repetidas) y, si se comparan, PDF del mismo tamaño. Lo demás se lista
para revisarlo a mano: mismo título en otra obra de la empresa, o PDF de tamaño distinto
(--incluir-distintos también los borra).
"""

from collections import defaultdict

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction

from core.informes_duplicados import buscar_duplicados
from core.models import Informe, InformeEliminado


def _tamano(informe):
    if not informe.archivo:
        return None
    try:
        return default_storage.size(informe.archivo.name)
    except Exception:  # noqa: BLE001 - archivo que no está en el storage
        return None


class Command(BaseCommand):
    help = 'Encuentra (y con --aplicar borra) las copias de WordPress de informes ya subidos en el portal.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Borra las copias de WordPress (sin esto solo muestra).')
        parser.add_argument('--sin-comparar', action='store_true', help='No compara el tamaño de los PDF (más rápido).')
        parser.add_argument('--incluir-distintos', action='store_true',
                            help='Borra también las copias cuyo PDF tiene otro tamaño que el subido a mano.')

    def handle(self, *args, **opts):
        comparar = not opts['sin_comparar']
        pares = buscar_duplicados()
        borrar, revisar = [], []
        for p in pares:
            p.tamanos = (_tamano(p.copia), _tamano(p.manual)) if comparar else (None, None)
            p.igual = None if None in p.tamanos else p.tamanos[0] == p.tamanos[1]
            if p.tipo == 'otra_obra':
                p.motivo = f'está en otra obra de la empresa ({p.manual.obra.codigo_obra} "{p.manual.obra.nombre}")'
                revisar.append(p)
            elif comparar and p.igual is False and not opts['incluir_distintos']:
                p.motivo = f'mismo nombre pero el PDF pesa distinto ({p.tamanos[0]:,} vs {p.tamanos[1]:,} bytes)'
                revisar.append(p)
            else:
                borrar.append(p)

        # Una copia de WP solo se borra una vez aunque su título case con dos subidas a mano
        vistos, unicos = set(), []
        for p in borrar:
            if p.copia.pk not in vistos:
                vistos.add(p.copia.pk)
                unicos.append(p)
        borrar = unicos

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Copias de WordPress de informes ya subidos en el portal: {len(borrar)}'))
        por_obra = defaultdict(list)
        for p in borrar:
            por_obra[p.copia.obra].append(p)
        for obra, lista in sorted(por_obra.items(), key=lambda x: x[0].codigo_obra or ''):
            self.stdout.write(f'\n  {obra.codigo_obra}  {obra.nombre}  ({len(lista)})')
            for p in lista:
                marca = '' if p.tipo == 'misma_obra' else f'  [subido en la obra gemela pk={p.manual.obra_id}]'
                if p.igual is None and comparar:
                    marca += '  [sin PDF para comparar]'
                self.stdout.write(f'    - {p.copia.titulo}  (WP {p.copia.id_wp_original}, pk={p.copia.pk})'
                                  f'  = "{p.manual.titulo}" (pk={p.manual.pk}){marca}')

        if revisar:
            self.stdout.write(self.style.WARNING(f'\nPara revisar a mano (NO se borran): {len(revisar)}'))
            for p in revisar:
                self.stdout.write(f'  ? {p.copia.obra.codigo_obra} {p.copia.titulo} (pk={p.copia.pk}): {p.motivo}')

        if not opts['aplicar']:
            self.stdout.write(self.style.WARNING('\nSolo se mostró: no se borró nada. Para borrar: --aplicar'))
            return
        if not borrar:
            self.stdout.write(self.style.SUCCESS('\nNo hay nada que borrar.'))
            return

        copias = [p.copia for p in borrar]
        ids = [c.pk for c in copias]
        with transaction.atomic():
            InformeEliminado.objects.bulk_create([
                InformeEliminado(
                    titulo=c.titulo, obra_codigo=c.obra.codigo_obra or '', obra_nombre=c.obra.nombre,
                    id_wp_original=c.id_wp_original, id_wp_adjunto=c.id_wp_adjunto,
                    archivo=c.archivo.name if c.archivo else '', fecha_informe=c.fecha_creacion,
                )
                for c in copias
            ])
            Informe.objects.filter(pk__in=ids).delete()
            # El PDF solo se borra si ningún informe que queda lo usa (WordPress y el portal
            # pudieron dejar el mismo nombre de archivo)
            en_uso = set(Informe.objects.exclude(archivo='').exclude(archivo__isnull=True)
                         .filter(archivo__in=[c.archivo.name for c in copias if c.archivo])
                         .values_list('archivo', flat=True))
            archivos = [c.archivo.name for c in copias if c.archivo and c.archivo.name not in en_uso]
            transaction.on_commit(lambda: self._borrar_archivos(archivos))
        self.stdout.write(self.style.SUCCESS(
            f'\nBorradas {len(copias)} copias de WordPress ({len(archivos)} PDF del almacenamiento). '
            'Quedan en InformeEliminado: la sincronización no las vuelve a traer.'))

    def _borrar_archivos(self, nombres):
        for nombre in nombres:
            try:
                default_storage.delete(nombre)
            except Exception as e:  # noqa: BLE001 - el registro ya quedó
                self.stderr.write(f'  No se pudo borrar {nombre}: {e}')
