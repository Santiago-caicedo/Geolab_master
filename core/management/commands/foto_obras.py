"""
Fotografía actual de constructoras y sus obras, tal como están en la base.
SOLO LECTURA: no modifica nada.

    python manage.py foto_obras                          # todo, en pantalla
    python manage.py foto_obras --ciudad Ibagué          # una sede
    python manage.py foto_obras --problemas              # solo lo que tiene algo raro
    python manage.py foto_obras --csv foto_obras.csv     # además a un CSV (abre en Excel)

Cada obra/constructora con algo raro lleva al final una marca entre corchetes:
  [código]      código fuera de la convención (BUC46 / BUC46-9 / BUC0-12-1)
  [ciudad]      el prefijo del código no corresponde a su ciudad
  [código-wp]   código viejo "<cliente>-<id WordPress>" (BUC7-43806)
  [sin nombre]  el nombre es un código o está vacío
  [duplicada]   otra constructora tiene la misma razón social
  [sin obras]   constructora sin obras
"""

import csv
import re
from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Count

from core.management.commands.estado_sistema import RE_CONSTRUCTORA, RE_OBRA
from users.ciudades import CIUDADES, normalizar_ciudad
from users.models import Constructora


def _clave_nombre(nombre):
    return re.sub(r'[^A-Z0-9]', '', (nombre or '').upper())


def marcas_constructora(c, repetidos):
    m = []
    if not RE_CONSTRUCTORA.match(c.codigo or ''):
        m.append('código')
    elif c.ciudad in CIUDADES and not c.codigo.startswith(CIUDADES[c.ciudad]):
        m.append('ciudad')
    if repetidos[_clave_nombre(c.nombre)] > 1:
        m.append('duplicada')
    if c.n_obras == 0:
        m.append('sin obras')
    return m


def marcas_obra(o):
    m = []
    codigo = o.codigo_obra or ''
    if not RE_OBRA.match(codigo):
        m.append('código')
    if o.id_wp_original and codigo.endswith(f'-{o.id_wp_original}'):
        m.append('código-wp')
    nombre = (o.nombre or '').strip()
    if (not nombre or nombre.replace(' ', '').upper() == codigo.upper()
            or RE_OBRA.match(nombre.replace(' ', '').upper())):
        m.append('sin nombre')
    return m


class Command(BaseCommand):
    help = 'Lista constructoras y obras como están hoy en la base (solo lectura).'

    def add_arguments(self, parser):
        parser.add_argument('--ciudad', help='Solo una sede (Bucaramanga, Bogotá, Ibagué)')
        parser.add_argument('--problemas', action='store_true',
                            help='Solo constructoras/obras con alguna marca')
        parser.add_argument('--csv', metavar='ARCHIVO',
                            help='Guarda además una fila por obra en un CSV (separador ;)')

    def handle(self, *args, **o):
        qs = Constructora.objects.annotate(n_obras=Count('obras')).prefetch_related('obras')
        if o['ciudad']:
            qs = qs.filter(ciudad=normalizar_ciudad(o['ciudad']))
        constructoras = list(qs.order_by('ciudad', 'codigo'))
        repetidos = Counter(_clave_nombre(c.nombre) for c in Constructora.objects.all())

        filas, total_obras, con_marca = [], 0, Counter()
        ciudad_actual = None
        for c in constructoras:
            mc = marcas_constructora(c, repetidos)
            obras = sorted(c.obras.all(), key=lambda x: x.codigo_obra or '')
            obras_m = [(ob, marcas_obra(ob)) for ob in obras]
            if o['problemas'] and not mc and not any(m for _, m in obras_m):
                continue

            if c.ciudad != ciudad_actual:
                ciudad_actual = c.ciudad
                self.stdout.write(self.style.MIGRATE_HEADING(f'\n══ {c.ciudad or "(sin ciudad)"} ══'))
            etiqueta = f'{c.codigo} · {c.nombre} · {c.n_obras} obras'
            if mc:
                self.stdout.write(self.style.WARNING(f'\n{etiqueta}  [{", ".join(mc)}]'))
            else:
                self.stdout.write(f'\n{etiqueta}')
            con_marca.update(mc)

            for ob, mo in obras_m:
                total_obras += 1
                con_marca.update(f'obra {x}' for x in mo)
                if o['problemas'] and not mo and not mc:
                    continue
                linea = f'    {ob.codigo_obra or "":<18} {(ob.nombre or "")[:50]:<50} wp={"-" if ob.id_wp_original is None else ob.id_wp_original}'
                if mo:
                    self.stdout.write(self.style.WARNING(f'{linea}  [{", ".join(mo)}]'))
                else:
                    self.stdout.write(linea)
                filas.append([c.ciudad or '', c.codigo, c.nombre, ', '.join(mc), ob.codigo_obra,
                              ob.nombre, '' if ob.id_wp_original is None else ob.id_wp_original, ', '.join(mo),
                              ob.direccion, ob.contacto, ob.celular or ob.telefono])
            if not obras:
                filas.append([c.ciudad or '', c.codigo, c.nombre, ', '.join(mc), '', '', '', '', '', '', ''])

        self.stdout.write(self.style.MIGRATE_HEADING('\n══ Resumen ══'))
        self.stdout.write(f'  Constructoras: {len(constructoras)} · Obras: {total_obras}')
        for marca, n in sorted(con_marca.items()):
            self.stdout.write(f'  [{marca}]: {n}')

        if o['csv']:
            with open(o['csv'], 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow(['Ciudad', 'Código constructora', 'Constructora', 'Marcas constructora',
                            'Código obra', 'Obra', 'ID WordPress', 'Marcas obra',
                            'Dirección', 'Contacto', 'Teléfono'])
                w.writerows(filas)
            self.stdout.write(self.style.SUCCESS(f'\nCSV guardado en {o["csv"]} ({len(filas)} filas)'))
