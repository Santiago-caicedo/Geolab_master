from django.core.management.base import BaseCommand
from solicitudes.models import RemisionMuestras
from ensayos.models import HojaTrabajo, ResultadoMuestra


class Command(BaseCommand):
    help = 'Sincroniza hojas de trabajo para remisiones completadas que no las tengan'

    def handle(self, *args, **options):
        self.stdout.write('Buscando remisiones sin hoja de trabajo...')

        # Remisiones completadas sin hoja de trabajo
        sin_hoja = RemisionMuestras.objects.filter(
            estado='completada'
        ).exclude(
            hoja_trabajo__isnull=False
        )

        creadas = 0
        for remision in sin_hoja:
            # Crear hoja de trabajo
            hoja = HojaTrabajo.objects.create(
                remision=remision,
                estado='pendiente'
            )

            # Crear resultados para cada muestra
            muestras = remision.muestras.all()
            resultados = []
            for muestra in muestras:
                if not ResultadoMuestra.objects.filter(muestra=muestra).exists():
                    resultados.append(ResultadoMuestra(
                        hoja_trabajo=hoja,
                        muestra=muestra,
                        estado='pendiente'
                    ))

            if resultados:
                ResultadoMuestra.objects.bulk_create(resultados)

            creadas += 1
            self.stdout.write(
                f'  + {remision.obra.codigo_obra} Rem#{remision.orden_trabajo}: '
                f'{len(resultados)} muestras'
            )

        # Buscar hojas sin resultados
        hojas_vacias = HojaTrabajo.objects.filter(resultados__isnull=True)
        resultados_creados = 0

        for hoja in hojas_vacias:
            muestras = hoja.remision.muestras.all()
            resultados = []
            for muestra in muestras:
                if not ResultadoMuestra.objects.filter(muestra=muestra).exists():
                    resultados.append(ResultadoMuestra(
                        hoja_trabajo=hoja,
                        muestra=muestra,
                        estado='pendiente'
                    ))

            if resultados:
                ResultadoMuestra.objects.bulk_create(resultados)
                resultados_creados += len(resultados)

        self.stdout.write(self.style.SUCCESS(
            f'Listo! {creadas} hojas creadas, {resultados_creados} resultados agregados.'
        ))
