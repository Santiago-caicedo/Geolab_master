from django.apps import AppConfig


class EnsayosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ensayos'
    verbose_name = 'Ensayos de Laboratorio'

    # Signal desactivado - la lógica se maneja en la vista con transaction.atomic()
    # para evitar race conditions y garantizar consistencia de datos.
    # Ver: solicitudes/views.py -> responder_remision()
    #
    # def ready(self):
    #     import ensayos.signals  # noqa
