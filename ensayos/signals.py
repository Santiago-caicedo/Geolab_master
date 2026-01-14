from django.db.models.signals import post_save
from django.dispatch import receiver

from solicitudes.models import RemisionMuestras
from .models import HojaTrabajo, ResultadoMuestra


@receiver(post_save, sender=RemisionMuestras)
def crear_hoja_trabajo_automaticamente(sender, instance, created, **kwargs):
    """
    Cuando una remisión cambia a estado 'completada',
    se crea automáticamente la hoja de trabajo con todos los resultados.

    Flujo:
    1. Cliente completa la remisión (F-GC-05)
    2. Estado cambia a 'completada'
    3. Este signal se dispara
    4. Se crea HojaTrabajo vinculada a la remisión
    5. Se crea un ResultadoMuestra por cada Muestra de la remisión
    6. Laboratorio puede empezar a llenar los datos de ensayo
    """
    # Solo procesar si la remisión está completada
    if instance.estado == 'completada':
        # Verificar si ya existe una hoja de trabajo para esta remisión
        if not hasattr(instance, 'hoja_trabajo') or instance.hoja_trabajo is None:
            try:
                # Verificar que no exista (doble check por si acaso)
                HojaTrabajo.objects.get(remision=instance)
            except HojaTrabajo.DoesNotExist:
                # Crear la hoja de trabajo
                hoja = HojaTrabajo.objects.create(
                    remision=instance,
                    estado='pendiente'
                )

                # Crear un ResultadoMuestra por cada Muestra de la remisión
                muestras = instance.muestras.all()
                resultados_a_crear = []

                for muestra in muestras:
                    resultados_a_crear.append(
                        ResultadoMuestra(
                            hoja_trabajo=hoja,
                            muestra=muestra,
                            estado='pendiente'
                        )
                    )

                # Crear todos los resultados en bulk para mejor rendimiento
                if resultados_a_crear:
                    ResultadoMuestra.objects.bulk_create(resultados_a_crear)

                print(f"[SIGNAL] Creada Hoja de Trabajo para Remisión #{instance.orden_trabajo} "
                      f"con {len(resultados_a_crear)} muestras")
