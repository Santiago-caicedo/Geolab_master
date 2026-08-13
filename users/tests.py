"""Tests del comando crear_coordinador_calidad."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from calidad.models import AreaCalidad
from users.models import UsuarioBase, FuncionarioGeolab


def crear_coordinador(username, **kwargs):
    kwargs.setdefault('noinput', True)
    call_command('crear_coordinador_calidad', username, stdout=StringIO(), stderr=StringIO(), **kwargs)
    return UsuarioBase.objects.get(username=username)


class CrearCoordinadorCalidadTest(TestCase):

    def test_crea_el_usuario_con_todos_sus_datos(self):
        user = crear_coordinador(
            'mcalidad', nombre='Maria', apellido='Gomez',
            email='maria@geolab.com', password='Geolab.Calidad.2026',
            codigo_empleado='GC-01',
        )
        self.assertEqual(user.get_full_name(), 'Maria Gomez')
        self.assertEqual(user.email, 'maria@geolab.com')
        self.assertEqual(user.perfil_geolab.area, 'calidad')
        self.assertEqual(user.perfil_geolab.codigo_empleado, 'GC-01')
        self.assertTrue(user.check_password('Geolab.Calidad.2026'))

    def test_el_rol_queda_correcto_y_sin_poder_de_admin(self):
        user = crear_coordinador('mcalidad', password='Geolab.Calidad.2026')
        self.assertTrue(user.es_geolab)
        self.assertTrue(user.es_coordinador_calidad)
        self.assertTrue(user.es_admin_sgc)
        # Lo que NO debe ganar
        self.assertFalse(user.es_admin_geolab)
        self.assertFalse(user.es_cliente)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_el_usuario_creado_entra_al_sgc_y_no_a_lo_demas(self):
        for n in range(1, 9):
            AreaCalidad.objects.create(numero=n, nombre=f'Area {n}')
        crear_coordinador('mcalidad', password='Geolab.Calidad.2026')

        self.assertTrue(self.client.login(username='mcalidad', password='Geolab.Calidad.2026'))
        resp = self.client.get('/calidad/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['areas_info']), 8)
        self.assertEqual(self.client.get('/remisiones/').url, '/calidad/')

    def test_rechaza_usuario_repetido_sin_actualizar(self):
        crear_coordinador('mcalidad', password='Geolab.Calidad.2026')
        with self.assertRaisesMessage(CommandError, 'ya existe'):
            crear_coordinador('mcalidad', password='Geolab.Calidad.2026')

    def test_rechaza_contrasena_debil_sin_crear_nada(self):
        with self.assertRaisesMessage(CommandError, 'reglas de seguridad'):
            crear_coordinador('debil', password='12345')
        self.assertFalse(UsuarioBase.objects.filter(username='debil').exists())

    def test_rechaza_correo_invalido_sin_crear_nada(self):
        with self.assertRaisesMessage(CommandError, 'no es valido'):
            crear_coordinador('malmail', email='no-es-correo', password='Geolab.Calidad.2026')
        self.assertFalse(UsuarioBase.objects.filter(username='malmail').exists())

    def test_exige_password_con_noinput(self):
        with self.assertRaisesMessage(CommandError, '--password'):
            crear_coordinador('sinclave')

    def test_convierte_un_tecnico_conservando_su_contrasena(self):
        user = UsuarioBase.objects.create_user('tec', password='Clave.Tecnico.2026', es_geolab=True)
        FuncionarioGeolab.objects.create(user=user, area='tecnico')

        user = crear_coordinador('tec', actualizar=True)

        self.assertEqual(user.perfil_geolab.area, 'calidad')
        self.assertTrue(user.es_coordinador_calidad)
        self.assertFalse(user.es_tecnico_laboratorio)
        # Sin --password la contrasena no se toca
        self.assertTrue(user.check_password('Clave.Tecnico.2026'))

    def test_convertir_a_un_cliente_le_quita_ese_rol(self):
        UsuarioBase.objects.create_user('cli', password='Clave.Cliente.2026', es_cliente=True)
        user = crear_coordinador('cli', actualizar=True)
        self.assertFalse(user.es_cliente)
        self.assertTrue(user.es_coordinador_calidad)
