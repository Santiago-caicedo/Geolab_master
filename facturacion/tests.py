"""
Tests del módulo de facturación.

    python manage.py test facturacion
"""

from django.test import SimpleTestCase, TestCase

from .models import CategoriaServicio, TipoServicio
from .orden import clave_orden


class ClaveOrdenTests(SimpleTestCase):
    """La clave debe ordenar los códigos como números, no como texto."""

    def test_numeros_simples(self):
        codigos = ['10', '2', '1', '14', '9']
        self.assertEqual(
            sorted(codigos, key=clave_orden), ['1', '2', '9', '10', '14'],
        )

    def test_sufijos_de_letras(self):
        codigos = ['9', '8V', '8A', '10', '11L', '11A', '11B', '12']
        self.assertEqual(
            sorted(codigos, key=clave_orden),
            ['8A', '8V', '9', '10', '11A', '11B', '11L', '12'],
        )

    def test_codigos_compuestos(self):
        codigos = ['1-10', '1-2', '1-1', '1-3-5-2', '1-3-5', '1-1-1', '1-3']
        self.assertEqual(
            sorted(codigos, key=clave_orden),
            ['1-1', '1-1-1', '1-2', '1-3', '1-3-5', '1-3-5-2', '1-10'],
        )

    def test_letras_pegadas_al_numero(self):
        self.assertLess(clave_orden('11-10L'), clave_orden('11-10LV'))
        self.assertLess(clave_orden('8-1A'), clave_orden('8-10A'))

    def test_codigo_corto_antes_que_sus_derivados(self):
        codigos = ['11-1-1L', '11-1L', '11-2L', '11-10L', '11-1-7L']
        self.assertEqual(
            sorted(codigos, key=clave_orden),
            ['11-1L', '11-1-1L', '11-1-7L', '11-2L', '11-10L'],
        )

    def test_codigo_vacio_no_rompe(self):
        self.assertEqual(clave_orden(''), '')
        self.assertEqual(clave_orden(None), '')


class OrdenEnBaseDeDatosTests(TestCase):
    """Meta.ordering usa clave_orden, que se calcula sola en save()."""

    def test_categorias_en_orden_natural(self):
        for codigo in ['10', '2', '11L', '1', '8V', '8A', '9', '14']:
            CategoriaServicio.objects.create(codigo=codigo, nombre=f'CAT {codigo}')
        self.assertEqual(
            list(CategoriaServicio.objects.values_list('codigo', flat=True)),
            ['1', '2', '8A', '8V', '9', '10', '11L', '14'],
        )

    def test_servicios_por_categoria_y_codigo(self):
        c1 = CategoriaServicio.objects.create(codigo='1', nombre='CONCRETOS')
        c10 = CategoriaServicio.objects.create(codigo='10', nombre='PERFORACIONES')
        TipoServicio.objects.create(categoria=c10, codigo='10-1', nombre='s10-1')
        TipoServicio.objects.create(categoria=c1, codigo='1-10', nombre='s1-10')
        TipoServicio.objects.create(categoria=c1, codigo='1-2', nombre='s1-2')
        TipoServicio.objects.create(categoria=c1, codigo='1-1', nombre='s1-1')
        self.assertEqual(
            list(TipoServicio.objects.values_list('codigo', flat=True)),
            ['1-1', '1-2', '1-10', '10-1'],
        )

    def test_clave_se_recalcula_al_cambiar_codigo(self):
        cat = CategoriaServicio.objects.create(codigo='3', nombre='X')
        cat.codigo = '12'
        cat.save()
        cat.refresh_from_db()
        self.assertEqual(cat.clave_orden, '0012')


from django.urls import reverse

from core.models import Obra
from users.models import Constructora, FuncionarioGeolab, UsuarioBase

from .models import Factura, RegistroServicio
from .sede import SESSION_KEY


class CiudadFacturacionTests(TestCase):
    """El módulo exige elegir ciudad y filtra todo por ella."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = UsuarioBase.objects.create_user(
            'admin_fact', password='clave-de-prueba', es_geolab=True,
        )
        FuncionarioGeolab.objects.create(user=cls.staff, area='admin')

        cls.c_buc = Constructora.objects.create(nombre='Buc SAS', codigo='B1', ciudad='Bucaramanga')
        cls.c_bog = Constructora.objects.create(nombre='Bog SAS', codigo='G1', ciudad='Bogotá')
        cls.c_sin = Constructora.objects.create(nombre='Sin ciudad', codigo='S1', ciudad='')
        cls.o_buc = Obra.objects.create(nombre='Obra Buc', codigo_obra='B1-1', constructora=cls.c_buc)
        cls.o_bog = Obra.objects.create(nombre='Obra Bog', codigo_obra='G1-1', constructora=cls.c_bog)

        cat = CategoriaServicio.objects.create(codigo='1', nombre='CONCRETOS')
        cls.srv = TipoServicio.objects.create(categoria=cat, codigo='1-1', nombre='Compresión')
        for obra in (cls.o_buc, cls.o_bog):
            RegistroServicio.objects.create(
                obra=obra, tipo_servicio=cls.srv, fecha_realizacion='2026-09-01',
                cantidad=1, precio_unitario_congelado=1000, creado_por=cls.staff,
            )

    def setUp(self):
        self.client.login(username='admin_fact', password='clave-de-prueba')

    def _elegir(self, ciudad):
        session = self.client.session
        session[SESSION_KEY] = ciudad
        session.save()

    def test_sin_ciudad_redirige_al_selector(self):
        r = self.client.get(reverse('dashboard_facturacion'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('seleccionar_ciudad_facturacion'), r.url)
        self.assertIn('next=', r.url)

    def test_api_sin_ciudad_devuelve_403_json(self):
        r = self.client.get(reverse('api_get_obras_facturacion'), {'constructora_id': self.c_buc.pk})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['status'], 'error')

    def test_selector_lista_ciudades_y_avisa_sin_ciudad(self):
        r = self.client.get(reverse('seleccionar_ciudad_facturacion'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c for c, _ in r.context['ciudades']], ['Bogotá', 'Bucaramanga'])
        self.assertEqual(r.context['sin_ciudad'], 1)

    def test_elegir_ciudad_guarda_en_sesion_y_respeta_next(self):
        destino = reverse('historico_facturacion')
        r = self.client.post(
            reverse('seleccionar_ciudad_facturacion'),
            {'ciudad': 'Bucaramanga', 'next': destino},
        )
        self.assertRedirects(r, destino)
        self.assertEqual(self.client.session[SESSION_KEY], 'Bucaramanga')

    def test_ciudad_invalida_no_se_acepta(self):
        r = self.client.post(reverse('seleccionar_ciudad_facturacion'), {'ciudad': 'Marte'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_next_externo_se_ignora(self):
        r = self.client.post(
            reverse('seleccionar_ciudad_facturacion'),
            {'ciudad': 'Bogotá', 'next': 'https://evil.example/x'},
        )
        self.assertRedirects(r, reverse('dashboard_facturacion'), fetch_redirect_response=False)

    def test_dashboard_cuenta_solo_la_ciudad(self):
        self._elegir('Bucaramanga')
        r = self.client.get(reverse('dashboard_facturacion'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_constructoras'], 1)
        self.assertEqual(r.context['total_obras'], 1)
        self.assertEqual(r.context['registros_pendientes'], 1)

    def test_historico_y_formularios_filtran(self):
        self._elegir('Bucaramanga')
        r = self.client.get(reverse('historico_facturacion'))
        self.assertEqual(r.context['total_registros'], 1)
        self.assertEqual(list(r.context['form'].fields['constructora'].queryset), [self.c_buc])
        r = self.client.get(reverse('generar_factura'))
        self.assertEqual(list(r.context['form'].fields['constructora'].queryset), [self.c_buc])

    def test_api_obras_no_devuelve_otra_ciudad(self):
        self._elegir('Bucaramanga')
        r = self.client.get(reverse('api_get_obras_facturacion'), {'constructora_id': self.c_bog.pk})
        self.assertEqual(r.json()['obras'], [])
        r = self.client.get(reverse('api_get_obras_facturacion'), {'constructora_id': self.c_buc.pk})
        self.assertEqual([o['id'] for o in r.json()['obras']], [self.o_buc.pk])

    def test_objetos_de_otra_ciudad_dan_404(self):
        self._elegir('Bucaramanga')
        self.assertEqual(
            self.client.get(reverse('gestionar_precios_obra', args=[self.o_bog.pk])).status_code, 404,
        )
        self.assertEqual(
            self.client.get(reverse('repositorio_obras_cliente', args=[self.c_bog.pk])).status_code, 404,
        )
        reg_bog = RegistroServicio.objects.get(obra=self.o_bog)
        self.assertEqual(
            self.client.get(reverse('editar_registro_facturacion', args=[reg_bog.pk])).status_code, 404,
        )

    def test_crear_registro_rechaza_obra_de_otra_ciudad(self):
        self._elegir('Bucaramanga')
        r = self.client.post(
            reverse('crear_registro_facturacion'),
            data='{"obra_id": %d, "fecha_realizacion": "2026-09-01", "servicios": [{"tipo_id": %d, "cantidad": 1}]}'
                 % (self.o_bog.pk, self.srv.pk),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)

    def test_sidebar_muestra_ciudad_activa(self):
        self._elegir('Bucaramanga')
        r = self.client.get(reverse('dashboard_facturacion'))
        self.assertContains(r, 'Bucaramanga')
        self.assertContains(r, reverse('seleccionar_ciudad_facturacion'))
