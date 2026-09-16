"""
Tests de core: normalización y sincronización desde WordPress.

    python manage.py test core
"""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.models import Informe, Obra
from core.wp_fuente import FuenteDump, ProyectoWP
from core.wp_normalizar import clave_constructora, codigo_obra, nombre_obra, razon_social_canonica
from facturacion.models import Factura
from users.models import ClienteExterno, Constructora, UsuarioBase


def _p(titulo, **meta):
    return ProyectoWP(1, titulo, None, 'publish', meta)


class NormalizarTests(SimpleTestCase):

    def test_clave_constructora(self):
        casos = {
            ('BUC 46', 'bucaramanga'): ('BUC46', False),
            ('BUC-23', 'bucaramanga'): ('BUC23', False),
            ('IBA13-1', 'ibague'): ('IBA13', False),
            ('BOG 1-12', 'bogota'): ('BOG1', False),
            ('BUC 0-12', 'bucaramanga'): ('BUC0-12', True),
            ('0-22', 'bucaramanga'): ('BUC0-22', True),
            ('BOG 0', 'bogota'): ('BOG0-0', True),
            ('sddsd', 'bucaramanga'): (None, None),
            ('', 'bucaramanga'): (None, None),
        }
        for (raw, mun), esperado in casos.items():
            self.assertEqual(clave_constructora(_p('x', **{'codigo-cliente_743': raw, 'municipio': mun})), esperado, raw)

    def test_codigo_obra(self):
        self.assertEqual(codigo_obra(_p('BUC 46-9'), 'BUC46'), 'BUC46-9')
        self.assertEqual(codigo_obra(_p('BUC 25--2'), 'BUC25'), 'BUC25-2')
        self.assertEqual(codigo_obra(_p('BUC-27-2'), 'BUC27'), 'BUC27-2')
        self.assertEqual(codigo_obra(_p('BOG0-2'), 'BOG0-2'), 'BOG0-2')
        self.assertEqual(codigo_obra(_p('San Benito', **{'codigo-proyecto': 'BUC 50-2'}), 'BUC50'), 'BUC50-2')
        self.assertEqual(codigo_obra(_p('1-1'), 'IBA1'), 'IBA1-1')          # sin prefijo: lo hereda
        self.assertIsNone(codigo_obra(_p('VILLANOVA'), 'BUC7'))

    def test_nombre_y_razon_social(self):
        self.assertEqual(nombre_obra(_p('BUC 46-9', **{'nombre-proyecto': "  'SUB  ESTACION' "})), 'SUB ESTACION')
        self.assertEqual(nombre_obra(_p('BUC 46-9')), 'BUC 46-9')
        self.assertEqual(razon_social_canonica(['MARVAL SAS', 'MARVAL S.A.S', 'MARVAL SAS']), 'MARVAL SAS')
        self.assertEqual(razon_social_canonica(['INACAR S.A', 'INACAR S.A.']), 'INACAR S.A.')


DUMP = """
CREATE TABLE `wpf3_posts` (
  `ID` bigint(20) UNSIGNED NOT NULL,
  `post_date` datetime NOT NULL,
  `post_title` text NOT NULL,
  `post_status` varchar(20) NOT NULL,
  `post_type` varchar(20) NOT NULL,
  `guid` varchar(255) NOT NULL,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB;

INSERT INTO `wpf3_posts` (`ID`, `post_date`, `post_title`, `post_status`, `post_type`, `guid`) VALUES
(500, '2023-05-01 10:00:00', 'IBA 13-1', 'publish', 'proyectos', ''),
(501, '2023-05-02 10:00:00', 'IBA 8-1', 'publish', 'proyectos', ''),
(502, '2023-05-03 10:00:00', 'BUC 0-12', 'publish', 'proyectos', ''),
(503, '2023-05-04 10:00:00', 'BUC0-12', 'publish', 'proyectos', ''),
(504, '2023-05-05 10:00:00', 'ejemplo', 'publish', 'proyectos', ''),
(505, '2023-05-06 10:00:00', 'IBA 8-2', 'draft', 'proyectos', ''),
(900, '2024-01-01 10:00:00', 'Informe 1', 'publish', 'informes', ''),
(901, '2024-01-02 10:00:00', 'Informe 2', 'publish', 'informes', ''),
(950, '2024-01-01 10:00:00', 'INF-0001.pdf', 'inherit', 'attachment', 'https://portal/wp-content/uploads/INF-0001.pdf');

CREATE TABLE `wpf3_postmeta` (
  `meta_id` bigint(20) UNSIGNED NOT NULL,
  `post_id` bigint(20) UNSIGNED NOT NULL,
  `meta_key` varchar(255) DEFAULT NULL,
  `meta_value` longtext DEFAULT NULL
) ENGINE=InnoDB;

INSERT INTO `wpf3_postmeta` (`meta_id`, `post_id`, `meta_key`, `meta_value`) VALUES
(1, 500, 'codigo-cliente_743', 'IBA13-1'),
(2, 500, 'razon-social', 'UNION TEMPORAL ROVIRA 2018'),
(3, 500, 'municipio', 'ibague'),
(4, 500, 'nombre-proyecto', 'Vía Rovira'),
(5, 501, 'codigo-cliente_743', 'IBA 8'),
(6, 501, 'razon-social', 'DYCO S.A.S'),
(7, 501, 'municipio', 'ibague'),
(8, 501, 'nombre-proyecto', 'AMBALA'),
(9, 501, 'direccion', 'Av Ambalá'),
(10, 501, 'persona-de-contacto-1', 'Javier'),
(11, 502, 'codigo-cliente_743', 'BUC 0-12'),
(12, 502, 'razon-social', 'DISCON'),
(13, 502, 'municipio', 'bucaramanga'),
(14, 502, 'nombre-proyecto', 'Bodega Discon'),
(15, 503, 'codigo-cliente_743', 'BUC0-12'),
(16, 503, 'razon-social', 'CDE S.A'),
(17, 503, 'municipio', 'bucaramanga'),
(18, 503, 'nombre-proyecto', 'Planta CDE'),
(19, 504, 'codigo-cliente_743', 'sddsd'),
(20, 504, 'razon-social', 'sdsd'),
(21, 504, 'municipio', 'bucaramanga'),
(22, 900, 'galeria-pdf', '950'),
(23, 505, 'codigo-cliente_743', 'IBA 8'),
(24, 505, 'municipio', 'ibague');

CREATE TABLE `wpf3_jet_rel_default` (
  `_ID` bigint(20) UNSIGNED NOT NULL,
  `rel_id` bigint(20) UNSIGNED NOT NULL,
  `parent_object_id` bigint(20) UNSIGNED NOT NULL,
  `child_object_id` bigint(20) UNSIGNED NOT NULL
) ENGINE=InnoDB;

INSERT INTO `wpf3_jet_rel_default` (`_ID`, `rel_id`, `parent_object_id`, `child_object_id`) VALUES
(1, 10, 501, 900),
(2, 10, 501, 901),
(3, 99, 501, 900);
"""


class FuenteDumpTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta = str(Path(cls.tmp.name) / 'mini.sql')
        Path(cls.ruta).write_text(DUMP, encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def test_lee_proyectos_e_informes(self):
        f = FuenteDump(self.ruta)
        proyectos = {p.id: p for p in f.proyectos()}
        self.assertEqual(sorted(proyectos), [500, 501, 502, 503, 504, 505])
        self.assertEqual(proyectos[501].m('nombre-proyecto'), 'AMBALA')
        self.assertEqual(proyectos[501].m('direccion'), 'Av Ambalá')
        self.assertEqual(proyectos[505].estado, 'draft')
        informes = {i.id: i for i in f.informes()}
        self.assertEqual(informes[900].proyecto_id, 501)
        self.assertEqual(informes[900].url_pdf, 'https://portal/wp-content/uploads/INF-0001.pdf')
        self.assertIsNone(informes[901].url_pdf)


class SincronizarWordpressTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta = str(Path(cls.tmp.name) / 'mini.sql')
        Path(cls.ruta).write_text(DUMP, encoding='utf-8')
        # Estado que dejó la migración vieja: constructora mutilada "IBA131" con un usuario colgado,
        # obra con el código como nombre y codigo_obra inventado; "BUC012" con dos obras de empresas distintas.
        cls.rovira_vieja = Constructora.objects.create(codigo='IBA131', nombre='UNION TEMPORAL ROVIRA 2018', ciudad='Ibagué')
        cls.obra_rovira = Obra.objects.create(id_wp_original=500, nombre='IBA 13-1', codigo_obra='IBA131-500', constructora=cls.rovira_vieja)
        u = UsuarioBase.objects.create_user('rovira', password='x', es_cliente=True)
        cls.cliente = ClienteExterno.objects.create(user=u, empresa=cls.rovira_vieja, rol='director')
        buc012 = Constructora.objects.create(codigo='BUC012', nombre='DISCON', ciudad='Bucaramanga')
        Obra.objects.create(id_wp_original=502, nombre='BUC 0-12', codigo_obra='BUC012-502', constructora=buc012)
        Obra.objects.create(id_wp_original=503, nombre='BUC0-12', codigo_obra='BUC012-503', constructora=buc012)
        Constructora.objects.create(codigo='SDDSD', nombre='sdsd', ciudad='Bucaramanga')   # basura, sin obras

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def _run(self, *extra):
        out = StringIO()
        call_command('sincronizar_wordpress', '--dump', self.ruta, *extra, stdout=out)
        return out.getvalue()

    def test_normaliza_y_conserva_identidades(self):
        salida = self._run()
        # IBA131 renombrada a IBA13 (mismo registro: el usuario sigue colgado)
        self.rovira_vieja.refresh_from_db()
        self.assertEqual(self.rovira_vieja.codigo, 'IBA13')
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.empresa_id, self.rovira_vieja.pk)
        # la obra conserva su pk y ahora tiene nombre y código reales
        self.obra_rovira.refresh_from_db()
        self.assertEqual((self.obra_rovira.nombre, self.obra_rovira.codigo_obra), ('Vía Rovira', 'IBA13-1'))
        # obra nueva con contacto
        ambala = Obra.objects.get(id_wp_original=501)
        self.assertEqual((ambala.codigo_obra, ambala.constructora.codigo, ambala.contacto), ('IBA8-1', 'IBA8', 'Javier'))
        # clientes varios: dos empresas distintas bajo BUC 0-12 -> BUC0-12 y BUC0-12B
        self.assertEqual(Obra.objects.get(id_wp_original=502).constructora.codigo, 'BUC0-12')
        self.assertEqual(Obra.objects.get(id_wp_original=503).constructora.codigo, 'BUC0-12B')
        self.assertEqual(Obra.objects.get(id_wp_original=503).constructora.nombre, 'CDE S.A')
        # basura y borradores fuera; constructora basura vacía eliminada
        self.assertFalse(Obra.objects.filter(id_wp_original__in=[504, 505]).exists())
        self.assertFalse(Constructora.objects.filter(codigo='SDDSD').exists())
        self.assertIn('irreconocible', salida)
        # informes ligados por id de WP, título = nombre del PDF
        self.assertEqual(Informe.objects.get(id_wp_original=900).titulo, 'INF-0001.pdf')
        self.assertEqual(Informe.objects.get(id_wp_original=901).obra, ambala)
        self.assertIn('Sincronización guardada', salida)

    def test_idempotente_y_dry_run(self):
        self._run()
        n = (Constructora.objects.count(), Obra.objects.count(), Informe.objects.count())
        salida = self._run()
        self.assertIn('Obras: 0 creadas, 0 actualizadas', salida)
        self.assertIn('Informes: 0 creados, 0 actualizados', salida)
        self.assertEqual(n, (Constructora.objects.count(), Obra.objects.count(), Informe.objects.count()))
        Obra.objects.filter(id_wp_original=501).delete()
        salida = self._run('--dry-run')
        self.assertIn('DRY-RUN', salida)
        self.assertFalse(Obra.objects.filter(id_wp_original=501).exists())

    def test_no_borra_constructora_con_facturas(self):
        # una constructora vacía con factura no se toca, se avisa
        vacia = Constructora.objects.create(codigo='BUC99', nombre='VIEJA', ciudad='Bucaramanga')
        obra = Obra.objects.create(nombre='x', codigo_obra='BUC99-1', constructora=vacia)
        Factura.objects.create(constructora=vacia, obra=obra, fecha_inicio_periodo='2026-01-01', fecha_fin_periodo='2026-01-31',
                               subtotal=0, monto_iva=0, total=0)
        salida = self._run()
        self.assertTrue(Constructora.objects.filter(codigo='BUC99').exists())
        self.assertNotIn('BUC99', salida.split('Avisos')[-1] if 'Avisos' in salida else '')   # tiene obra: ni siquiera es candidata

    def test_obra_basura_se_elimina_solo_sin_dependencias(self):
        basura = Constructora.objects.get(codigo='SDDSD')
        con_informe = Obra.objects.create(id_wp_original=504, nombre='ejemplo', codigo_obra='SDDSD-504', constructora=basura)
        Informe.objects.create(titulo='x.pdf', obra=con_informe)
        salida = self._run()
        self.assertTrue(Obra.objects.filter(id_wp_original=504).exists())      # tiene informe: se conserva
        self.assertTrue(Constructora.objects.filter(codigo='SDDSD').exists())
        self.assertIn('NO se eliminó', salida)
        Informe.objects.filter(obra=con_informe).delete()
        self._run()
        self.assertFalse(Obra.objects.filter(id_wp_original=504).exists())
        self.assertFalse(Constructora.objects.filter(codigo='SDDSD').exists())

    def test_omitir(self):
        self._run('--omitir', '501')
        self.assertFalse(Obra.objects.filter(id_wp_original=501).exists())
