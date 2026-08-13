"""
Crea (o convierte) un usuario con el rol Coordinador de Calidad.

Existe porque hacerlo a mano desde el admin de Django es un flujo de dos pasos
—la casilla es_geolab solo aparece despues de guardar— y si se marca es_geolab
antes de asignarle el area, el usuario queda como admin total por el fallback de
UsuarioBase.es_admin_geolab. Aqui todo ocurre dentro de una transaccion, asi que
esa ventana nunca se abre.
"""

import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from users.models import UsuarioBase, FuncionarioGeolab

AREA_CALIDAD = 'calidad'


class Command(BaseCommand):
    help = (
        'Crea un usuario Coordinador de Calidad: entra unicamente al Sistema '
        'de Calidad (/calidad/), pero dentro del SGC ve las 8 areas, sube, '
        'elimina y gestiona los accesos de los demas.'
    )

    def add_arguments(self, parser):
        parser.add_argument('username', help='Nombre de usuario para iniciar sesion.')
        parser.add_argument('--nombre', default='', help='Nombres de la persona.')
        parser.add_argument('--apellido', default='', help='Apellidos de la persona.')
        parser.add_argument('--email', default='', help='Correo electronico.')
        parser.add_argument(
            '--password',
            default=None,
            help='Contrasena. Si se omite, se pide de forma interactiva y oculta '
                 '(recomendado: asi no queda en el historial de la terminal).',
        )
        parser.add_argument(
            '--codigo-empleado', dest='codigo_empleado', default='',
            help='Codigo de empleado (opcional).',
        )
        parser.add_argument(
            '--actualizar', action='store_true',
            help='Si el usuario ya existe, convertirlo en Coordinador de Calidad '
                 'en vez de fallar.',
        )
        parser.add_argument(
            '--noinput', action='store_true',
            help='No hacer preguntas interactivas. Exige --password al crear.',
        )

    # ── entrada ───────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        username = options['username'].strip()
        if not username:
            raise CommandError('El nombre de usuario no puede estar vacio.')

        existente = UsuarioBase.objects.filter(username=username).first()
        if existente and not options['actualizar']:
            raise CommandError(
                f'El usuario "{username}" ya existe. Usa --actualizar para '
                f'convertirlo en Coordinador de Calidad.'
            )

        if existente:
            self._avisos_de_conversion(existente)

        email = options['email'].strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise CommandError(f'El correo "{email}" no es valido.')

        password = self._resolver_password(options, username, existente)

        with transaction.atomic():
            user = existente or UsuarioBase()
            user.username = username
            if options['nombre']:
                user.first_name = options['nombre'].strip()
            if options['apellido']:
                user.last_name = options['apellido'].strip()
            if email:
                user.email = email

            # El rol vive del lado Geolab; nunca es cliente ni entra al admin.
            user.es_geolab = True
            user.es_cliente = False
            user.is_staff = False
            user.is_superuser = False
            user.is_active = True

            if password:
                user.set_password(password)
            user.save()

            perfil, creado_perfil = FuncionarioGeolab.objects.update_or_create(
                user=user,
                defaults={
                    'area': AREA_CALIDAD,
                    'codigo_empleado': options['codigo_empleado'].strip(),
                },
            )

        self._resumen(user, perfil, creado_usuario=existente is None)

    # ── contrasena ────────────────────────────────────────────────────────────

    def _resolver_password(self, options, username, existente):
        """Devuelve la contrasena a fijar, o None para dejar la actual intacta."""
        password = options['password']

        if password is None:
            if options['noinput']:
                if existente:
                    return None  # conversion sin tocar la contrasena
                raise CommandError('Con --noinput debes pasar --password al crear.')
            password = self._pedir_password(username, opcional=bool(existente))
            if password is None:
                return None

        usuario_tentativo = existente or UsuarioBase(username=username)
        try:
            validate_password(password, usuario_tentativo)
        except ValidationError as e:
            raise CommandError(
                'La contrasena no cumple las reglas de seguridad:\n  - '
                + '\n  - '.join(e.messages)
            )
        return password

    def _pedir_password(self, username, opcional):
        etiqueta = (
            'Nueva contrasena (deja vacio para conservar la actual): '
            if opcional else f'Contrasena para "{username}": '
        )
        for intento in range(3):
            primera = getpass.getpass(etiqueta)
            if not primera:
                if opcional:
                    return None
                self.stderr.write('La contrasena no puede estar vacia.')
                continue
            segunda = getpass.getpass('Confirma la contrasena: ')
            if primera != segunda:
                self.stderr.write('Las contrasenas no coinciden. Intenta de nuevo.')
                continue
            return primera
        raise CommandError('Demasiados intentos fallidos.')

    # ── avisos y resumen ──────────────────────────────────────────────────────

    def _avisos_de_conversion(self, user):
        self.stdout.write(self.style.WARNING(
            f'El usuario "{user.username}" ya existe y sera convertido en '
            f'Coordinador de Calidad.'
        ))
        perfil = getattr(user, 'perfil_geolab', None)
        if perfil and perfil.area != AREA_CALIDAD:
            self.stdout.write(self.style.WARNING(
                f'  - Cambiara de area "{perfil.get_area_display()}" a Coordinador '
                f'de Calidad: perdera el acceso a los demas modulos.'
            ))
        if user.es_cliente:
            self.stdout.write(self.style.WARNING(
                '  - Dejara de ser usuario cliente (es_cliente pasa a False).'
            ))
        if user.is_superuser:
            self.stdout.write(self.style.WARNING(
                '  - Dejara de ser superusuario. Nota: los superusuarios quedan '
                'exentos del confinamiento a /calidad/.'
            ))

    def _resumen(self, user, perfil, creado_usuario):
        verbo = 'creado' if creado_usuario else 'actualizado'
        self.stdout.write(self.style.SUCCESS(
            f'\nCoordinador de Calidad {verbo}: {user.username}'
        ))

        nombre = user.get_full_name() or '(sin nombre)'
        self.stdout.write(f'  Nombre  : {nombre}')
        self.stdout.write(f'  Correo  : {user.email or "(sin correo)"}')
        self.stdout.write(f'  Area    : {perfil.get_area_display()}')
        if perfil.codigo_empleado:
            self.stdout.write(f'  Codigo  : {perfil.codigo_empleado}')

        # Se leen del objeto ya guardado para reportar el estado real, no el esperado.
        user.refresh_from_db()
        self.stdout.write('\n  Comprobacion del rol:')
        self.stdout.write(f'    es_coordinador_calidad : {user.es_coordinador_calidad}')
        self.stdout.write(f'    es_admin_sgc           : {user.es_admin_sgc}')
        self.stdout.write(f'    es_admin_geolab        : {user.es_admin_geolab}')

        if not user.es_coordinador_calidad or user.es_admin_geolab:
            raise CommandError(
                'El rol no quedo como se esperaba. Revisa el usuario en el admin.'
            )

        self.stdout.write(self.style.SUCCESS(
            '\n  Puede : entrar a /calidad/, ver las 8 areas, subir, crear carpetas,\n'
            '          eliminar documentos y gestionar los accesos al SGC.\n'
            '  No puede: salir del Sistema de Calidad (obras, remisiones, ensayos,\n'
            '          facturacion, usuarios y el admin de Django le quedan cerrados).'
        ))
