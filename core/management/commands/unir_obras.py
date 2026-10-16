"""
Une dos obras que son el MISMO proyecto: pasa todo lo de la obra ORIGEN
(remisiones, informes, informes de ensayo, precios, registros, facturas,
residentes asignados) a la obra DESTINO y borra la de origen ya vacía.

Por defecto es un ENSAYO: muestra qué movería y no guarda nada.

    python manage.py unir_obras --origen 171 --destino 164             # ensayo
    python manage.py unir_obras --origen 171 --destino 164 --aplicar   # de verdad

Los números (pk) salen en los avisos de sincronizar_wordpress
("código de obra X repetido en el PORTAL: pk=...").

Se queda la obra DESTINO con su nombre, código e id de WordPress. Si algo
chocaría (p. ej. la misma orden de trabajo en las dos obras), no hace nada
y lo explica. Las dos obras deben ser de la misma constructora, salvo --forzar.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Obra
from core.management.commands.sincronizar_wordpress import _dependencias


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = 'Une dos obras duplicadas: mueve todo de --origen a --destino y borra el origen.'

    def add_arguments(self, parser):
        parser.add_argument('--origen', type=int, required=True, help='pk de la obra que se vacía y se borra')
        parser.add_argument('--destino', type=int, required=True, help='pk de la obra que se queda')
        parser.add_argument('--aplicar', action='store_true', help='Guarda los cambios (sin esto es un ensayo)')
        parser.add_argument('--forzar', action='store_true', help='Permite unir obras de constructoras distintas')

    def handle(self, *args, **o):
        if o['origen'] == o['destino']:
            raise CommandError('--origen y --destino son la misma obra.')
        try:
            origen = Obra.objects.select_related('constructora').get(pk=o['origen'])
            destino = Obra.objects.select_related('constructora').get(pk=o['destino'])
        except Obra.DoesNotExist as e:
            raise CommandError(f'No existe la obra: {e}')

        modo = 'REAL' if o['aplicar'] else 'ENSAYO (no se guarda nada)'
        self.stdout.write(self.style.MIGRATE_HEADING(f'Unir obras · {modo}'))
        for etiqueta, obra in (('ORIGEN (se borra) ', origen), ('DESTINO (se queda)', destino)):
            self.stdout.write(f'  {etiqueta}: pk={obra.pk} {obra.codigo_obra} "{obra.nombre}" '
                              f'· {obra.constructora} · WP {obra.id_wp_original if obra.id_wp_original is not None else "-"}'
                              f' · tiene: {_dependencias(obra) or "nada"}')
        if origen.constructora_id != destino.constructora_id and not o['forzar']:
            raise CommandError('Las obras son de constructoras distintas. Revisa los pk o usa --forzar.')

        conflictos = self._conflictos(origen, destino)
        if conflictos:
            self.stdout.write(self.style.ERROR('\nNo se puede unir, chocaría:'))
            for c in conflictos:
                self.stdout.write(f'  ✗ {c}')
            raise CommandError('Resuelve esos choques a mano y vuelve a intentar.')

        try:
            with transaction.atomic():
                self.stdout.write('\nSe mueve a la obra destino:')
                total = 0
                for rel in Obra._meta.related_objects:
                    qs = rel.related_model._default_manager.filter(**{rel.field.name: origen})
                    n = qs.update(**{rel.field.name: destino})
                    if n:
                        total += n
                        self.stdout.write(f'  → {n} {rel.related_model._meta.verbose_name_plural}')
                residentes = list(origen.residentes_asignados.all())
                if residentes:
                    destino.residentes_asignados.add(*residentes)
                    origen.residentes_asignados.clear()
                    self.stdout.write(f'  → {len(residentes)} residentes asignados')
                for campo in ('direccion', 'telefono', 'contacto', 'celular'):
                    if not getattr(destino, campo) and getattr(origen, campo):
                        setattr(destino, campo, getattr(origen, campo))
                        self.stdout.write(f'  → {campo}: "{getattr(origen, campo)}" (el destino no tenía)')
                destino.save()
                if not total and not residentes:
                    self.stdout.write('  (nada)')

                origen.refresh_from_db()
                quedan = _dependencias(origen)
                if quedan:   # seguridad: el borrado en cascada se llevaría esto
                    raise CommandError(f'La obra origen aún tiene {quedan}: no se borra.')
                origen.delete()
                self.stdout.write(f'\n  ✗ Obra origen pk={o["origen"]} borrada (quedó vacía).')
                destino.refresh_from_db()
                self.stdout.write(f'  ✓ Obra destino pk={destino.pk} ahora tiene: {_dependencias(destino) or "nada"}')
                if not o['aplicar']:
                    raise _Rollback
        except _Rollback:
            self.stdout.write(self.style.WARNING('\n[ENSAYO] No se guardó nada. Para hacerlo: agrega --aplicar'))
            return
        self.stdout.write(self.style.SUCCESS('\nObras unidas y guardadas.'))

    def _conflictos(self, origen, destino):
        """Lo que violaría una regla de "no repetir" al pasar a la obra destino."""
        conflictos = []
        ot_destino = set(destino.remisiones.values_list('orden_trabajo', flat=True))
        for r in origen.remisiones.filter(orden_trabajo__in=ot_destino):
            conflictos.append(f'remisión con orden de trabajo {r.orden_trabajo} existe en las dos obras')
        claves = set(destino.informes_ensayo.values_list('tipo', 'fecha_falla'))
        for i in origen.informes_ensayo.all():
            if (i.tipo, i.fecha_falla) in claves:
                conflictos.append(f'informe de ensayo {i.tipo} del {i.fecha_falla} existe en las dos obras')
        servicios = set(destino.lista_de_precios.values_list('tipo_servicio_id', flat=True))
        for p in origen.lista_de_precios.filter(tipo_servicio_id__in=servicios).select_related('tipo_servicio'):
            conflictos.append(f'precio de "{p.tipo_servicio}" existe en las dos obras')
        return conflictos
