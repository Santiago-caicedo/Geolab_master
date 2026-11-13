import tempfile
from io import StringIO
from pathlib import Path

import openpyxl
from django.core.management import call_command
from django.test import TestCase

from core.models import Obra
from users.models import ClienteExterno, Constructora, UsuarioBase


class CargarUsuariosExcelTests(TestCase):
    """Carga del Excel de usuarios del laboratorio: contraseñas tal cual, códigos con guiones de más."""

    @classmethod
    def setUpTestData(cls):
        cls.marval = Constructora.objects.create(codigo='BUC57', nombre='URBANIZADORA MARVAL SAS', ciudad='Bucaramanga')
        cls.obra = Obra.objects.create(nombre='AZAFRAN', codigo_obra='BUC57-4', constructora=cls.marval)
        Constructora.objects.create(codigo='BUC56', nombre='MARVAL SAS', ciudad='Bucaramanga')
        # código repetido: dos empresas con BUC11-1
        cls.cag = Constructora.objects.create(codigo='BUC11', nombre='CAG', ciudad='Bucaramanga')
        cls.mic = Constructora.objects.create(codigo='BUC11B', nombre='GRUPO MIC', ciudad='Bucaramanga')
        cls.provenza = Obra.objects.create(nombre='CASA PROVENZA', codigo_obra='BUC11-1', constructora=cls.cag)
        Obra.objects.create(nombre='FINCA VEGAS', codigo_obra='BUC11-1', constructora=cls.mic)
        UsuarioBase.objects.create_user('existente', password='otra-clave-larga')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = str(Path(self.tmp.name) / 'usuarios.xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'BUC'
        ws.append(['USUARIO', None, 'CONTRASEÑA', None, 'OBRA', 'RAZON SOCIAL', None, 'USUARIO REMISIONES', None,
                   'CONTRASEÑA', None, 'OBRA', None, None, 'CLIENTE'])
        ws.append([None] * 14 + ['USUARIO', 'CONTRASEÑA'])
        ws.append(['azafran1', None, 'az1', None, '57--4', None, None, 'rprovenza', None, 1234, None, '11--1',
                   None, None, 'urbmarval', 'Clave Con Espacio ', 'URBANIZADORA MARVAL'])
        ws.append(['existente', None, 'x', None, '57-4'])
        ws.append([None, None, 'sin-usuario', None, '57-13'])
        ws.append(['beltramonto', None, 'b', None, '57-4'])
        wb.save(self.ruta)

    def _run(self, *extra):
        out = StringIO()
        call_command('cargar_usuarios_excel', self.ruta, *extra, stdout=out)
        return out.getvalue()

    def test_ensayo_no_guarda_ni_muestra_claves(self):
        salida = self._run()
        self.assertIn('Se crean 3 usuarios', salida)
        self.assertIn('ENSAYO', salida)
        self.assertFalse(UsuarioBase.objects.filter(username='azafran1').exists())
        for clave in ('az1', '1234', 'Clave Con Espacio'):
            self.assertNotIn(clave, salida)

    def test_aplicar_carga_claves_tal_cual(self):
        salida = self._run('--aplicar')
        self.assertIn('Creados 3 usuarios', salida)
        res = UsuarioBase.objects.get(username='azafran1')
        self.assertTrue(res.check_password('az1'))                   # corta: se carga igual (excepción)
        self.assertTrue(res.es_cliente)
        self.assertEqual(list(res.perfil_cliente.obras_asignadas.all()), [self.obra])
        rem = UsuarioBase.objects.get(username='rprovenza')
        self.assertTrue(rem.check_password('1234'))                  # celda numérica
        self.assertEqual(rem.perfil_cliente.rol, 'remitente')
        self.assertEqual(list(rem.perfil_cliente.obras_asignadas.all()), [self.provenza])   # desempate CAG
        dire = UsuarioBase.objects.get(username='urbmarval')
        self.assertTrue(dire.check_password('Clave Con Espacio '))   # sin recortar
        self.assertEqual((dire.perfil_cliente.rol, dire.perfil_cliente.empresa), ('director', self.marval))
        # el que ya existía no se toca; el pendiente y la fila sin usuario no se cargan
        self.assertTrue(UsuarioBase.objects.get(username='existente').check_password('otra-clave-larga'))
        self.assertFalse(UsuarioBase.objects.filter(username='beltramonto').exists())
        self.assertEqual(ClienteExterno.objects.count(), 3)
        self.assertIn('Creados 0 usuarios', self._run('--aplicar'))   # idempotente

    def test_pendiente_se_carga_con_obra_fijada(self):
        self._run('--aplicar', '--obra', 'beltramonto=BUC57-4')
        self.assertTrue(UsuarioBase.objects.filter(username='beltramonto').exists())
