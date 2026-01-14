from django.apps import AppConfig


class EnsayosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ensayos'
    verbose_name = 'Ensayos de Laboratorio'

    def ready(self):
        # Importar signals cuando la app esté lista
        import ensayos.signals  # noqa
