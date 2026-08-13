"""
Tests del rol Coordinador de Calidad.

Cubren las dos mitades del rol:
  1. Manda dentro del SGC (ve las 8 areas, sube, elimina, gestiona accesos).
  2. No puede salir de /calidad/ (RestriccionCalidadMiddleware).
"""

from django.test import TestCase

from calidad.models import AreaCalidad, Carpeta, Documento, AccesoAreaUsuario
from calidad.views import _usuario_tiene_acceso
from users.models import UsuarioBase, FuncionarioGeolab


def crear_geolab(username, area):
    user = UsuarioBase.objects.create_user(
        username, password='clave-de-prueba', es_geolab=True
    )
    FuncionarioGeolab.objects.create(user=user, area=area)
    return user


class RolCoordinadorCalidadTest(TestCase):
    """El coordinador manda dentro del SGC pero no es admin general."""

    @classmethod
    def setUpTestData(cls):
        cls.areas = [
            AreaCalidad.objects.create(numero=n, nombre=f'Area {n}')
            for n in range(1, 9)
        ]
        cls.coordinador = crear_geolab('coord', 'calidad')
        cls.tecnico = crear_geolab('tec', 'tecnico')
        cls.admin = crear_geolab('adm', 'admin')

    def test_propiedades_del_rol(self):
        self.assertTrue(self.coordinador.es_coordinador_calidad)
        self.assertTrue(self.coordinador.es_admin_sgc)
        # No hereda poder fuera del SGC
        self.assertFalse(self.coordinador.es_admin_geolab)
        self.assertFalse(self.coordinador.es_tecnico_laboratorio)

    def test_ve_las_ocho_areas_sin_matriz_de_accesos(self):
        self.assertEqual(AccesoAreaUsuario.objects.filter(usuario=self.coordinador).count(), 0)
        self.client.force_login(self.coordinador)
        resp = self.client.get('/calidad/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['areas_info']), 8)

    def test_tiene_lectura_y_edicion_en_toda_area(self):
        for area in self.areas:
            self.assertTrue(_usuario_tiene_acceso(self.coordinador, area))
            self.assertTrue(_usuario_tiene_acceso(self.coordinador, area, requiere_edicion=True))

    def test_puede_eliminar_documentos(self):
        carpeta = Carpeta.objects.create(nombre='Formatos', area=self.areas[0])
        doc = Documento.objects.create(nombre='f.pdf', carpeta=carpeta)
        self.client.force_login(self.coordinador)
        resp = self.client.post(f'/calidad/documento/{doc.pk}/eliminar/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Documento.objects.filter(pk=doc.pk).exists())

    def test_puede_gestionar_accesos(self):
        self.client.force_login(self.coordinador)
        resp = self.client.get('/calidad/accesos/')
        self.assertEqual(resp.status_code, 200)
        # No se lista a si mismo: ya tiene acceso total
        listados = [f['usuario'].pk for f in resp.context['matriz']]
        self.assertNotIn(self.coordinador.pk, listados)
        self.assertIn(self.tecnico.pk, listados)

    def test_el_tecnico_no_gana_poder_en_el_sgc(self):
        self.assertFalse(self.tecnico.es_admin_sgc)
        self.assertFalse(_usuario_tiene_acceso(self.tecnico, self.areas[0]))


class ContencionCoordinadorCalidadTest(TestCase):
    """El middleware lo encierra en /calidad/ sin afectar a los demas roles."""

    RUTAS_DE_OTROS_MODULOS = [
        '/empresas/',
        '/obras/1/',
        '/usuarios/',
        '/remisiones/',
        '/cargar-informe/',
        '/ensayos/hojas-trabajo/',
        '/facturacion/',
        '/admin/',
    ]

    @classmethod
    def setUpTestData(cls):
        AreaCalidad.objects.create(numero=1, nombre='Gestion Directiva')
        cls.coordinador = crear_geolab('coord', 'calidad')
        cls.admin = crear_geolab('adm', 'admin')

    def test_queda_bloqueado_fuera_de_calidad(self):
        self.client.force_login(self.coordinador)
        for ruta in self.RUTAS_DE_OTROS_MODULOS:
            with self.subTest(ruta=ruta):
                resp = self.client.get(ruta)
                self.assertEqual(resp.status_code, 302, f'{ruta} no redirigio')
                self.assertEqual(resp.url, '/calidad/')

    def test_entra_al_sgc(self):
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get('/calidad/').status_code, 200)

    def test_la_raiz_lo_manda_a_su_panel(self):
        self.client.force_login(self.coordinador)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/calidad/')

    def test_puede_cerrar_sesion(self):
        self.client.force_login(self.coordinador)
        resp = self.client.post('/accounts/logout/')
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.url, '/calidad/')

    def test_el_staff_no_queda_restringido(self):
        """La contencion no debe tocar a los demas roles."""
        self.client.force_login(self.admin)
        resp = self.client.get('/empresas/')
        self.assertEqual(resp.status_code, 200)
