"""
Carga el catálogo de servicios de la sede Bucaramanga (categorías + servicios)
tomado de la hoja "LISTA DE PRECIO" de BASE DATOS BUCARAMANGA.xlsm.

Los datos viven en facturacion/catalogo_bucaramanga.py. NO importa precios:
esos se gestionan por obra desde /facturacion/precios/.

Es idempotente: se puede correr varias veces. Busca por código; si la
categoría o el servicio ya existen, actualiza nombre/norma/categoría; si no,
los crea. Nunca borra nada.

    python manage.py cargar_catalogo_bucaramanga
    python manage.py cargar_catalogo_bucaramanga --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from facturacion.catalogo_bucaramanga import CATEGORIAS, SERVICIOS
from facturacion.models import CategoriaServicio, TipoServicio


class Command(BaseCommand):
    help = 'Carga/actualiza categorías y servicios de la sede Bucaramanga (sin precios).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra lo que haría sin escribir en la base de datos.',
        )

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        stats = {'cat_creadas': 0, 'cat_actualizadas': 0,
                 'srv_creados': 0, 'srv_actualizados': 0, 'sin_cambios': 0}
        self._verificar_conflictos()
        try:
            with transaction.atomic():
                self._cargar(stats)
                if dry:
                    self._resumen(stats, dry)
                    raise _Rollback
        except _Rollback:
            return
        except IntegrityError as e:
            raise CommandError(
                f'Conflicto de unicidad, no se guardó nada: {e}\n'
                'Revisa si ya existe un servicio con el mismo NOMBRE pero otro '
                'código (TipoServicio.nombre es único).'
            )
        self._resumen(stats, dry)

    def _verificar_conflictos(self):
        """
        TipoServicio.nombre es único. Si en la BD ya hay un servicio con el
        mismo nombre pero OTRO código (típico: datos sintéticos de
        seed_facturacion), el INSERT fallaría a mitad de camino. Se detecta
        antes y se aborta con la lista completa.
        """
        codigo_por_nombre = {n.lower(): c for _, c, n, _ in SERVICIOS}
        conflictos = []
        for s in TipoServicio.objects.all():
            esperado = codigo_por_nombre.get(s.nombre.lower())
            if esperado and esperado != s.codigo:
                conflictos.append(f'  [{s.codigo}] "{s.nombre}"  (en el catálogo es [{esperado}])')
        if conflictos:
            raise CommandError(
                'No se cargó nada. Ya existen servicios con el mismo NOMBRE pero '
                'otro código:\n' + '\n'.join(conflictos) + '\n'
                'Corrige o elimina esos servicios desde /facturacion/catalogo/ y '
                'vuelve a correr el comando. Si son datos sintéticos de '
                'seed_facturacion, `seed_facturacion --limpiar` borra TODO el '
                'módulo de facturación (catálogo, precios, registros y facturas).'
            )

        # Aviso (no bloquea): categorías existentes con servicios que no están
        # en el catálogo real. Al renombrar la categoría esos servicios quedan
        # bajo un nombre que no les corresponde.
        codigos_catalogo = {c for _, c, _, _ in SERVICIOS}
        for cat_codigo, nombre in CATEGORIAS:
            cat = CategoriaServicio.objects.filter(codigo=cat_codigo).first()
            if cat is None:
                continue
            ajenos = cat.servicios.exclude(codigo__in=codigos_catalogo).count()
            if ajenos:
                self.stdout.write(self.style.WARNING(
                    f'  ! Categoría {cat_codigo} ("{cat.nombre}") tiene {ajenos} '
                    f'servicio(s) que no están en el catálogo; quedará como "{nombre}".'
                ))

    def _cargar(self, stats):
        categorias = {}
        for codigo, nombre in CATEGORIAS:
            cat, creada = CategoriaServicio.objects.get_or_create(
                codigo=codigo, defaults={'nombre': nombre},
            )
            if creada:
                stats['cat_creadas'] += 1
                self.stdout.write(f'  + Categoría {codigo} - {nombre}')
            elif cat.nombre != nombre:
                self.stdout.write(f'  ~ Categoría {codigo}: "{cat.nombre}" -> "{nombre}"')
                cat.nombre = nombre
                cat.save(update_fields=['nombre'])
                stats['cat_actualizadas'] += 1
            categorias[codigo] = cat

        for cat_codigo, codigo, nombre, norma in SERVICIOS:
            cat = categorias[cat_codigo]
            srv = TipoServicio.objects.filter(codigo=codigo).first()
            if srv is None:
                TipoServicio.objects.create(
                    categoria=cat, codigo=codigo, nombre=nombre, norma=norma,
                )
                stats['srv_creados'] += 1
                self.stdout.write(f'  + [{codigo}] {nombre}')
                continue
            cambios = []
            if srv.nombre != nombre:
                cambios.append(f'nombre: "{srv.nombre}" -> "{nombre}"')
                srv.nombre = nombre
            if srv.norma != norma:
                cambios.append(f'norma: "{srv.norma}" -> "{norma}"')
                srv.norma = norma
            if srv.categoria_id != cat.pk:
                cambios.append(f'categoría: {srv.categoria.codigo} -> {cat.codigo}')
                srv.categoria = cat
            if cambios:
                srv.save()
                stats['srv_actualizados'] += 1
                self.stdout.write(f'  ~ [{codigo}] ' + '; '.join(cambios))
            else:
                stats['sin_cambios'] += 1

    def _resumen(self, s, dry):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY-RUN] ' if dry else ''}"
            f"Categorías: {s['cat_creadas']} creadas, {s['cat_actualizadas']} actualizadas. "
            f"Servicios: {s['srv_creados']} creados, {s['srv_actualizados']} actualizados, "
            f"{s['sin_cambios']} sin cambios."
        ))
        if dry:
            self.stdout.write(self.style.WARNING('No se escribió nada en la base de datos.'))


class _Rollback(Exception):
    """Se lanza dentro de transaction.atomic() para deshacer el dry-run."""
