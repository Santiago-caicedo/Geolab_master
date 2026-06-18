from django.core.management.base import BaseCommand
from django.db import transaction

from solicitudes.models import RemisionMuestras, Muestra, Notificacion
from ensayos.models import HojaTrabajo, ResultadoMuestra, InformeEnsayo, ConsecutivoInforme


class Command(BaseCommand):
    help = (
        'Borra TODAS las remisiones y, en cascada, sus muestras, hojas de '
        'trabajo, resultados y notificaciones. Pensado para limpiar datos de '
        'prueba. Operación irreversible.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--noinput',
            action='store_true',
            help='No pedir confirmación interactiva (úsalo con cuidado).',
        )
        parser.add_argument(
            '--informes',
            action='store_true',
            help='Borrar también los InformeEnsayo y reiniciar el consecutivo.',
        )

    def _conteos(self):
        return {
            'Remisiones': RemisionMuestras.objects.count(),
            'Muestras': Muestra.objects.count(),
            'Hojas de trabajo': HojaTrabajo.objects.count(),
            'Resultados': ResultadoMuestra.objects.count(),
            'Notificaciones': Notificacion.objects.count(),
            'Informes de ensayo': InformeEnsayo.objects.count(),
        }

    def handle(self, *args, **options):
        antes = self._conteos()

        if antes['Remisiones'] == 0:
            self.stdout.write(self.style.WARNING('No hay remisiones que borrar.'))
            return

        self.stdout.write('Se borrará en cascada:')
        for k, v in antes.items():
            self.stdout.write(f'  - {k}: {v}')
        if options['informes']:
            self.stdout.write(self.style.WARNING(
                '  (--informes) También se borrarán los informes y se reiniciará el consecutivo.'
            ))

        if not options['noinput']:
            confirm = input(
                self.style.WARNING(
                    '\nEsto es IRREVERSIBLE. Escribe "BORRAR" para confirmar: '
                )
            )
            if confirm.strip() != 'BORRAR':
                self.stdout.write(self.style.ERROR('Cancelado. No se borró nada.'))
                return

        with transaction.atomic():
            # El borrado de remisiones arrastra muestras, hojas, resultados y
            # notificaciones por los on_delete=CASCADE definidos en los modelos.
            RemisionMuestras.objects.all().delete()

            if options['informes']:
                InformeEnsayo.objects.all().delete()
                ConsecutivoInforme.objects.all().delete()

        despues = self._conteos()
        self.stdout.write(self.style.SUCCESS('\nListo. Estado final:'))
        for k, v in despues.items():
            self.stdout.write(f'  - {k}: {v}')

        self.stdout.write(self.style.SUCCESS(
            f"\nRemisiones borradas: {antes['Remisiones']}."
        ))
        if not options['informes'] and antes['Informes de ensayo']:
            self.stdout.write(self.style.WARNING(
                'Nota: los informes de ensayo NO se tocaron (quedaron sin resultados). '
                'Usa --informes si quieres borrarlos también.'
            ))
