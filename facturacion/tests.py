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

from .models import Factura, PrecioServicio, RegistroServicio
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


import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO

from .importar_excel import leer_lista_precios, resolver_obra


def _libro_de_prueba(ruta):
    """Libro mínimo con la estructura de BASE DATOS <CIUDAD>.xlsm."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'LISTA DE PRECIO'
    ws.append(['', '', 'LISTA DE PRECIOS 2023'])
    ws.append([])
    ws.append(['ÍTEM', 'DESCRIPCIÓN', 'NORMA', 'PRECIO LISTA', 'DESCUENTO ', '8-1', 0, '10-2', '8-1'])
    ws.append(['ÍTEM', 'DESCRIPCIÓN', 'NORMA', 'PRECIO LISTA', 'DESCUENTO ', '8-1', None, '10-2', '8-1'])
    ws.append(['\xa0       1', 'CONCRETOS'])
    ws.append(['1-1', 'Compresión de cilindros', 'NTC 673', 4500, -4500, 5000, None, 5500, None])
    ws.append(['1-2', 'Diseño de mezclas', 'N/A', 420000, -420000, None, None, 0, 350000])
    ws.append(['1-2', 'Diseño de mezclas', 'NTC 999', None, None, 111, None, None, None])   # dup nombre: fusiona
    ws.append(['13-8', 'Tracción indirecta', 'NTC 722', 20000, None, 21000, None, None, None])  # falta guion
    ws.append(['2', 'SUELOS'])
    ws.append(['2.1', 'Humedad', 'INV E-122', 5000, None, 6000, None, 6500, None])
    ws.append(['2-2', 'Compresión de cilindros', 'X', 1, None, None, None, None, None])       # mismo nombre otra cat.
    ws2 = wb.create_sheet('LISTA EMPRESAS REGULARES')
    ws2.append(['8', 'DYCO SAS', '10', 'ASFALTEMOS', '11', 'Columna1'])
    ws2.append(['8-1', 'AMBALA', '10-2', 'JORDAN'])
    wb.save(ruta)


class LecturaExcelTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta = str(Path(cls.tmp.name) / 'base.xlsx')
        _libro_de_prueba(cls.ruta)
        cls.lectura = leer_lista_precios(cls.ruta)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def test_categorias_y_columnas(self):
        self.assertEqual(self.lectura.categorias, [('1', 'CONCRETOS'), ('2', 'SUELOS')])
        self.assertEqual(self.lectura.obras, ['8-1', '10-2'])          # la "8-1" repetida no se duplica
        self.assertEqual(self.lectura.nombres_obras, {'8-1': 'AMBALA', '10-2': 'JORDAN'})
        self.assertEqual(self.lectura.nombres_empresas, {'8': 'DYCO SAS', '10': 'ASFALTEMOS'})

    def test_limpieza_de_codigos_y_nombres(self):
        por_codigo = {s.codigo: s for s in self.lectura.servicios}
        self.assertEqual(set(por_codigo), {'1-1', '1-2', '1-3-8', '2-1', '2-2'})
        self.assertEqual(por_codigo['1-2'].norma, 'NTC 999')                       # 'N/A' + fusión
        self.assertEqual(por_codigo['2-2'].nombre, 'Compresión de cilindros (cód. 2-2)')

    def test_precios_por_obra(self):
        por_codigo = {s.codigo: s for s in self.lectura.servicios}
        self.assertEqual(por_codigo['1-1'].precios, {'8-1': Decimal('5000'), '10-2': Decimal('5500')})
        # 0 se ignora; la columna 8-1 repetida aporta 350000; la fila fusionada aporta 111 solo si faltaba
        self.assertEqual(por_codigo['1-2'].precios, {'8-1': Decimal('350000')})
        self.assertEqual(por_codigo['2-1'].precios, {'8-1': Decimal('6000'), '10-2': Decimal('6500')})

    def test_hoja_inexistente(self):
        with self.assertRaises(ValueError):
            leer_lista_precios(self.ruta, hoja='NO EXISTE')


class ImportarCatalogoExcelTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta = str(Path(cls.tmp.name) / 'base.xlsx')
        _libro_de_prueba(cls.ruta)
        dyco = Constructora.objects.create(codigo='IBA8', nombre='DYCO SAS', ciudad='Ibagué')
        cls.ambala = Obra.objects.create(constructora=dyco, nombre='AMBALA', codigo_obra='IBA8-1')
        asf = Constructora.objects.create(codigo='IBA10', nombre='ASFALTEMOS', ciudad='Ibagué')
        cls.jordan = Obra.objects.create(constructora=asf, nombre='Jordan', codigo_obra='IBA10-555')
        Obra.objects.create(constructora=asf, nombre='Otra', codigo_obra='IBA10-556')
        # mismo código en otra ciudad: no debe mezclarse
        cat_buc = CategoriaServicio.objects.create(ciudad='Bucaramanga', codigo='1', nombre='CONCRETOS')
        TipoServicio.objects.create(categoria=cat_buc, codigo='1-1', nombre='Otro servicio con código 1-1')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def _run(self, *extra):
        out = StringIO()
        call_command('importar_catalogo_excel', self.ruta, '--ciudad', 'ibague', *extra, stdout=out)
        return out.getvalue()

    def test_importa_catalogo_y_precios_resolviendo_obras(self):
        salida = self._run()
        self.assertEqual(TipoServicio.objects.filter(ciudad='Ibagué').count(), 5)
        self.assertEqual(TipoServicio.objects.filter(ciudad='Bucaramanga', codigo='1-1').count(), 1)
        precio = PrecioServicio.objects.get(obra=self.ambala, tipo_servicio__codigo='1-1', tipo_servicio__ciudad='Ibagué')
        self.assertEqual(precio.precio, Decimal('5000'))
        # 10-2 se resolvió por nombre de proyecto (JORDAN) aunque el código no coincide
        self.assertTrue(PrecioServicio.objects.filter(obra=self.jordan, precio=Decimal('5500')).exists())
        self.assertIn('Importación guardada', salida)

    def test_es_idempotente_y_dry_run_no_escribe(self):
        self._run()
        antes = PrecioServicio.objects.count()
        salida = self._run()
        self.assertIn('0 nuevos', salida)
        self.assertEqual(PrecioServicio.objects.count(), antes)
        PrecioServicio.objects.all().delete()
        salida = self._run('--dry-run')
        self.assertIn('DRY-RUN', salida)
        self.assertEqual(PrecioServicio.objects.count(), 0)

    def test_no_sobrescribir_conserva_precio_manual(self):
        self._run()
        ps = PrecioServicio.objects.get(obra=self.ambala, tipo_servicio__codigo='1-1', tipo_servicio__ciudad='Ibagué')
        ps.precio = Decimal('1')
        ps.save()
        self._run('--no-sobrescribir')
        ps.refresh_from_db()
        self.assertEqual(ps.precio, Decimal('1'))
        self._run()
        ps.refresh_from_db()
        self.assertEqual(ps.precio, Decimal('5000'))

    def test_obra_manual_y_no_resuelta(self):
        # ya no coincide ni por código ni por nombre de proyecto: cae en 'única obra'
        Obra.objects.filter(codigo_obra='IBA8-1').update(codigo_obra='IBA8-999', nombre='Bodega')
        salida = self._run()
        self.assertIn('única obra de DYCO SAS', salida)
        salida = self._run('--obra', '8-1=IBA10-556')
        self.assertIn('--obra', salida)
        self.assertTrue(PrecioServicio.objects.filter(obra__codigo_obra='IBA10-556', precio=Decimal('5000')).exists())

    def test_conflicto_de_nombre_aborta(self):
        cat = CategoriaServicio.objects.create(ciudad='Ibagué', codigo='9', nombre='OTRA')
        TipoServicio.objects.create(categoria=cat, codigo='9-1', nombre='Humedad')
        with self.assertRaises(CommandError):
            self._run()
        self.assertEqual(TipoServicio.objects.filter(ciudad='Ibagué').count(), 1)


class CatalogoPorCiudadTests(TestCase):

    def test_mismo_codigo_en_dos_ciudades(self):
        for ciudad in ('Bucaramanga', 'Ibagué'):
            cat = CategoriaServicio.objects.create(ciudad=ciudad, codigo='1', nombre='CONCRETOS')
            TipoServicio.objects.create(categoria=cat, codigo='1-8', nombre=f'Servicio 1-8 de {ciudad}')
        self.assertEqual(TipoServicio.objects.filter(codigo='1-8').count(), 2)
        self.assertEqual(TipoServicio.objects.get(codigo='1-8', ciudad='Ibagué').nombre, 'Servicio 1-8 de Ibagué')

    def test_servicio_hereda_ciudad_de_su_categoria(self):
        cat = CategoriaServicio.objects.create(ciudad='Ibagué', codigo='2', nombre='SUELOS')
        s = TipoServicio.objects.create(categoria=cat, codigo='2-1', nombre='Humedad')
        self.assertEqual(s.ciudad, 'Ibagué')

    def test_formulario_de_servicio_rechaza_duplicado_solo_en_su_ciudad(self):
        from .forms import TipoServicioForm
        cat_i = CategoriaServicio.objects.create(ciudad='Ibagué', codigo='1', nombre='CONCRETOS')
        cat_b = CategoriaServicio.objects.create(ciudad='Bucaramanga', codigo='1', nombre='CONCRETOS')
        TipoServicio.objects.create(categoria=cat_b, codigo='1-1', nombre='Compresión')
        datos = {'categoria': cat_i.pk, 'codigo': '1-1', 'nombre': 'Compresión', 'norma': ''}
        self.assertTrue(TipoServicioForm(datos, ciudad='Ibagué').is_valid())
        form = TipoServicioForm({**datos, 'categoria': cat_b.pk}, ciudad='Bucaramanga')
        self.assertFalse(form.is_valid())
        self.assertIn('codigo', form.errors)
        # el select de categoría solo ofrece las de la ciudad
        self.assertEqual(list(TipoServicioForm(ciudad='Ibagué').fields['categoria'].queryset), [cat_i])
