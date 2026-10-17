from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from solicitudes.models import Notificacion
from users.models import UsuarioBase


class Command(BaseCommand):
    help = 'Marca como leídas todas las notificaciones pendientes (o solo las de un usuario con --usuario).'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', help='Solo las dirigidas a este usuario (login)')
        parser.add_argument('--dry-run', action='store_true', help='Solo cuenta, no cambia nada')

    def handle(self, *args, **o):
        pendientes = Notificacion.objects.filter(leida=False)
        if o['usuario']:
            try:
                u = UsuarioBase.objects.get(username=o['usuario'])
            except UsuarioBase.DoesNotExist:
                raise CommandError(f'No existe el usuario "{o["usuario"]}"')
            pendientes = pendientes.filter(destinatario=u)
        n = pendientes.count()
        if o['dry_run']:
            self.stdout.write(f'[DRY-RUN] {n} notificaciones quedarían marcadas como leídas.')
            return
        pendientes.update(leida=True, fecha_lectura=timezone.now())
        self.stdout.write(self.style.SUCCESS(f'{n} notificaciones marcadas como leídas.'))
