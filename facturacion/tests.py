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
