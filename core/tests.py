"""
Tests de core: normalización y sincronización desde WordPress.

    python manage.py test core
"""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase

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
(902, '2024-01-03 10:00:00', 'IBA 8-1', 'publish', 'informes', ''),
(950, '2024-01-01 10:00:00', 'INF-0001.pdf', 'inherit', 'attachment', 'https://portal/wp-content/uploads/INF-0001.pdf'),
(951, '2024-01-03 10:00:00', 'INF-0002.pdf', 'inherit', 'attachment', 'https://portal/wp-content/uploads/INF-0002.pdf'),
(952, '2024-01-03 10:00:00', 'INF-0003.pdf', 'inherit', 'attachment', 'https://portal/wp-content/uploads/INF-0003.pdf');

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
(24, 505, 'municipio', 'ibague'),
(25, 902, 'galeria-pdf', '951,952');

CREATE TABLE `wpf3_jet_rel_default` (
  `_ID` bigint(20) UNSIGNED NOT NULL,
  `rel_id` bigint(20) UNSIGNED NOT NULL,
  `parent_object_id` bigint(20) UNSIGNED NOT NULL,
  `child_object_id` bigint(20) UNSIGNED NOT NULL
) ENGINE=InnoDB;

INSERT INTO `wpf3_jet_rel_default` (`_ID`, `rel_id`, `parent_object_id`, `child_object_id`) VALUES
(1, 10, 501, 900),
(2, 10, 501, 901),
(3, 99, 501, 900),
(4, 10, 501, 902);
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
        # galería: varios PDF en el mismo post, en el orden de la galería
        self.assertEqual(informes[902].adjuntos, [(951, 'https://portal/wp-content/uploads/INF-0002.pdf'),
                                                  (952, 'https://portal/wp-content/uploads/INF-0003.pdf')])


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
        # galería de WP = un Informe por PDF, cada uno con el nombre de su PDF (no el código de la obra)
        galeria = Informe.objects.filter(id_wp_original=902).order_by('id_wp_adjunto')
        self.assertEqual([(i.id_wp_adjunto, i.titulo, i.url_archivo_original) for i in galeria], [
            (951, 'INF-0002.pdf', 'https://portal/wp-content/uploads/INF-0002.pdf'),
            (952, 'INF-0003.pdf', 'https://portal/wp-content/uploads/INF-0003.pdf'),
        ])
        self.assertEqual(Informe.objects.get(id_wp_original=900).id_wp_adjunto, 950)
        self.assertIn('Sincronización guardada', salida)

    def test_galeria_adopta_la_fila_vieja_sin_adjunto(self):
        # Antes de conocer galerías el sync creaba UNA fila por post, con el código de la obra como título
        self._run('--sin-informes')
        vieja = Informe.objects.create(titulo='IBA 8-1', obra=Obra.objects.get(id_wp_original=501), id_wp_original=902)
        salida = self._run()
        vieja.refresh_from_db()
        self.assertEqual((vieja.id_wp_adjunto, vieja.titulo), (951, 'INF-0002.pdf'))
        self.assertEqual(Informe.objects.filter(id_wp_original=902).count(), 2)
        self.assertIn('1 actualizados', salida)
        self.assertIn('0 creados', self._run())   # idempotente

    def test_borrar_un_pdf_de_la_galeria_no_bloquea_los_demas(self):
        from core.models import InformeEliminado
        self._run()
        uno = Informe.objects.get(id_wp_original=902, id_wp_adjunto=952)
        InformeEliminado.objects.create(titulo=uno.titulo, id_wp_original=902, id_wp_adjunto=952)
        uno.delete()
        salida = self._run()
        self.assertEqual(list(Informe.objects.filter(id_wp_original=902).values_list('id_wp_adjunto', flat=True)), [951])
        self.assertIn('1 eliminados en el portal', salida)

    def test_idempotente_y_dry_run(self):
        self._run()
        n = (Constructora.objects.count(), Obra.objects.count(), Informe.objects.count())
        salida = self._run()
        self.assertIn('Obras: 0 creadas, 0 adoptadas del portal, 0 actualizadas', salida)
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
        self.assertNotIn('constructora BUC99', salida)   # tiene obra: ni siquiera es candidata a borrarse

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

    def test_no_vuelve_a_traer_informes_eliminados_en_el_portal(self):
        from core.models import InformeEliminado
        self._run()
        inf = Informe.objects.get(id_wp_original=900)
        InformeEliminado.objects.create(titulo=inf.titulo, id_wp_original=900)
        inf.delete()
        salida = self._run()
        self.assertFalse(Informe.objects.filter(id_wp_original=900).exists())
        self.assertIn('1 eliminados en el portal', salida)

    def test_omitir(self):
        self._run('--omitir', '501')
        self.assertFalse(Obra.objects.filter(id_wp_original=501).exists())

    def test_adopta_obra_creada_en_el_portal(self):
        # obra creada a mano (sin id de WP, código sin prefijo) que luego aparece en WordPress como IBA 8-1
        dyco = Constructora.objects.create(codigo='IBA8', nombre='DYCO', ciudad='Ibagué')
        manual = Obra.objects.create(nombre='AMBALA', codigo_obra='8-1', constructora=dyco)
        salida = self._run()
        manual.refresh_from_db()
        self.assertEqual((manual.id_wp_original, manual.codigo_obra, manual.contacto), (501, 'IBA8-1', 'Javier'))
        self.assertEqual(Obra.objects.filter(codigo_obra='IBA8-1').count(), 1)
        self.assertIn('1 adoptadas del portal', salida)
        self.assertEqual(Informe.objects.get(id_wp_original=900).obra, manual)

    def test_codigo_reutilizado_el_registro_sigue_a_su_empresa(self):
        # en el portal BUC0-12 quedó con el nombre de la SEGUNDA empresa (CDE) y con su usuario;
        # en WP el código es primero de DISCON -> el registro de CDE pasa a BUC0-12B con su usuario
        cde = Constructora.objects.get(codigo='BUC012')
        cde.codigo, cde.nombre = 'BUC0-12', 'CDE S.A'
        cde.save()
        u = UsuarioBase.objects.create_user('cde', password='x', es_cliente=True)
        cliente = ClienteExterno.objects.create(user=u, empresa=cde, rol='remitente')
        salida = self._run()
        cde.refresh_from_db()
        cliente.refresh_from_db()
        self.assertEqual((cde.codigo, cde.nombre), ('BUC0-12B', 'CDE S.A'))
        self.assertEqual(cliente.empresa_id, cde.pk)
        self.assertEqual(Constructora.objects.get(codigo='BUC0-12').nombre, 'DISCON')
        self.assertEqual(Obra.objects.get(id_wp_original=503).constructora, cde)
        self.assertIn('renombrada a BUC0-12B', salida)

    def test_adopta_obra_con_id_wp_inventado(self):
        # id de WP puesto a mano en el admin (1 no es un proyecto de WordPress): también es obra del portal
        dyco = Constructora.objects.create(codigo='IBA8', nombre='DYCO', ciudad='Ibagué')
        manual = Obra.objects.create(nombre='AMBALA', codigo_obra='IBA8-1', constructora=dyco, id_wp_original=1)
        salida = self._run()
        manual.refresh_from_db()
        self.assertEqual(manual.id_wp_original, 501)
        self.assertIn('WP 1 -> 501', salida)
        self.assertEqual(Obra.objects.filter(codigo_obra='IBA8-1').count(), 1)

    def test_no_adopta_obra_de_otra_ciudad_y_avisa_repetidos(self):
        otra = Constructora.objects.create(codigo='BUC8', nombre='OTRA', ciudad='Bucaramanga')
        Obra.objects.create(nombre='X', codigo_obra='BUC8-1', constructora=otra)
        salida = self._run()
        self.assertIsNone(Obra.objects.get(codigo_obra='BUC8-1').id_wp_original)
        self.assertIn('0 adoptadas del portal', salida)
        self.assertIn('obra del portal sin WordPress: BUC8-1', salida)
        Obra.objects.create(nombre='copia', codigo_obra='IBA8-1', constructora=otra, id_wp_original=1)
        salida = self._run()
        self.assertIn('código de obra IBA8-1 repetido en el PORTAL', salida)


from core.wp_normalizar import agrupar_por_empresa, misma_empresa  # noqa: E402


class MismaEmpresaTests(SimpleTestCase):

    def test_variantes_del_mismo_nombre(self):
        for a, b in [
            ('MARVAL SAS', 'MARVAL S.A.S'), ('INACAR S.A', 'INACAR S.A.'),
            ('15 ANDES DESARROLADORA S.A.S', 'ANDES DESARROLLADORA S.A.S'),
            ('PRABYC INGENIEROS SAS', 'PRAVYC INGENIEROS'), ('G KOI S.A.S', 'KOI CONSTRUCTORA S.A.S'),
            ('URBANIZADORA MARVAL SAS', '57 URBANIZADORA MARVAL S.A.S AV EL DORADO'),
        ]:
            self.assertTrue(misma_empresa(a, b), (a, b))

    def test_empresas_distintas(self):
        for a, b in [
            ('ASFALTEMOS', 'UNIÓN TEMPORAL AP COELLO 2021'),
            ('CONSORCIO OBRAS ACUEDUCTO PROAR', 'PROYECTOS Y SOLUCIONES 4GA S.A.S'),
            ('CONSTRUCTORA VALU LTA', 'J.GE CONSTRUCCIONES S.A.S'), ('CAG S.A.S', 'GRUPO MIC SAS'),
            ('CONSORCIO DC 2025', 'INGEOTECNIA'),
        ]:
            self.assertFalse(misma_empresa(a, b), (a, b))

    def test_agrupar_conserva_orden(self):
        ps = [_p('a', **{'razon-social': r}) for r in ['ASFALTEMOS', 'UNIÓN TEMPORAL AP COELLO 2021', 'ASFALTEMOS VIAS']]
        grupos = agrupar_por_empresa(ps)
        self.assertEqual([[q.m('razon-social') for q in g] for g in grupos],
                         [['ASFALTEMOS', 'ASFALTEMOS VIAS'], ['UNIÓN TEMPORAL AP COELLO 2021']])


class UnirObrasTests(TestCase):

    def setUp(self):
        from solicitudes.models import RemisionMuestras
        self.c = Constructora.objects.create(codigo='BUC53', nombre='MARTINEZ', ciudad='Bucaramanga')
        self.destino = Obra.objects.create(nombre='ALTOS DEL DIAMANTE', codigo_obra='BUC53-4', constructora=self.c, id_wp_original=44746)
        self.origen = Obra.objects.create(nombre='BUC53-4', codigo_obra='BUC53-4', constructora=self.c, id_wp_original=1,
                                          contacto='Ana')
        Informe.objects.create(titulo='inf.pdf', obra=self.destino)
        self.rem = RemisionMuestras.objects.create(obra=self.origen, estado='completada')
        u = UsuarioBase.objects.create_user('res', password='x', es_cliente=True)
        self.residente = ClienteExterno.objects.create(user=u, empresa=self.c, rol='residente')
        self.origen.residentes_asignados.add(self.residente)

    def _run(self, *extra):
        out = StringIO()
        call_command('unir_obras', '--origen', str(self.origen.pk), '--destino', str(self.destino.pk), *extra, stdout=out)
        return out.getvalue()

    def test_ensayo_no_cambia_nada(self):
        salida = self._run()
        self.assertIn('[ENSAYO]', salida)
        self.assertTrue(Obra.objects.filter(pk=self.origen.pk).exists())
        self.rem.refresh_from_db()
        self.assertEqual(self.rem.obra_id, self.origen.pk)

    def test_aplicar_mueve_todo_y_borra_origen(self):
        salida = self._run('--aplicar')
        self.assertIn('Obras unidas y guardadas', salida)
        self.assertFalse(Obra.objects.filter(pk=self.origen.pk).exists())
        self.rem.refresh_from_db()
        self.assertEqual(self.rem.obra_id, self.destino.pk)
        self.destino.refresh_from_db()
        self.assertEqual((self.destino.nombre, self.destino.id_wp_original, self.destino.contacto),
                         ('ALTOS DEL DIAMANTE', 44746, 'Ana'))
        self.assertIn(self.residente, self.destino.residentes_asignados.all())
        self.assertEqual(self.destino.informes.count(), 1)

    def test_choque_de_orden_de_trabajo_no_hace_nada(self):
        from solicitudes.models import RemisionMuestras
        RemisionMuestras.objects.create(obra=self.destino, estado='completada', orden_trabajo=self.rem.orden_trabajo)
        with self.assertRaises(CommandError):
            self._run('--aplicar')
        self.assertTrue(Obra.objects.filter(pk=self.origen.pk).exists())

    def test_constructoras_distintas_requiere_forzar(self):
        otra = Constructora.objects.create(codigo='BUC54', nombre='OTRA', ciudad='Bucaramanga')
        self.destino.constructora = otra
        self.destino.save()
        with self.assertRaises(CommandError):
            self._run()




class FechaInformeTests(TestCase):
    """La fecha del informe se elige al cargarlo (por defecto hoy, nunca futura)."""

    def setUp(self):
        from django.test import override_settings
        from users.models import FuncionarioGeolab
        self.tmp = tempfile.TemporaryDirectory()
        self.media = override_settings(MEDIA_ROOT=self.tmp.name)
        self.media.enable()
        u = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True)
        FuncionarioGeolab.objects.create(user=u, area='admin')
        self.client.force_login(u)
        c = Constructora.objects.create(codigo='BUC46', nombre='JAIMES', ciudad='Bucaramanga')
        self.obra = Obra.objects.create(nombre='LA GRANJA', codigo_obra='BUC46-5', constructora=c)

    def tearDown(self):
        self.media.disable()
        self.tmp.cleanup()

    def _pdf(self, nombre='INF-0001.pdf', contenido=b'%PDF-1.4 prueba', tipo='application/pdf'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nombre, contenido, content_type=tipo)

    def _subir(self, url, fecha, archivos=None):
        return self.client.post(url, {'obra': self.obra.pk, 'fecha': fecha,
                                      'archivos': archivos or [self._pdf()]})

    def test_paginas_muestran_fecha_de_hoy(self):
        from django.urls import reverse
        from django.utils import timezone
        hoy = timezone.localdate().isoformat()
        for url in (reverse('cargar_informe'), reverse('cargar_informe_obra', args=[self.obra.pk])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, f'value="{hoy}"')
            self.assertContains(r, 'type="date"')
            self.assertContains(r, 'multiple')
            self.assertContains(r, 'accept=".pdf,application/pdf"')

    def test_pantalla_unica_con_y_sin_obra(self):
        from django.urls import reverse
        r = self.client.get(reverse('cargar_informe_obra', args=[self.obra.pk]))
        self.assertTemplateUsed(r, 'core/cargar_informe.html')
        self.assertContains(r, 'BUC46-5')
        self.assertContains(r, 'name="obra" id="cgObraId" value="%d"' % self.obra.pk)
        self.assertNotContains(r, 'id="cgEmpresaInput"')          # obra fija: no hay buscador
        r = self.client.get(reverse('cargar_informe') + '?obra=%d' % self.obra.pk)
        self.assertContains(r, 'id="cgEmpresaInput"')
        self.assertContains(r, 'value="%d"' % self.obra.pk)   # llega con la obra elegida
        self.assertContains(r, '"codigo": "BUC46"')            # empresas para el buscador (json_script)

    def test_error_conserva_la_obra_elegida(self):
        from django.urls import reverse
        r = self._subir(reverse('cargar_informe'), '2025-03-14',
                        [self._pdf('malo.pdf', b'no es pdf')])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No se cargó ningún informe')
        self.assertContains(r, 'name="obra" id="cgObraId" value="%d"' % self.obra.pk)

    def test_titulos_existentes_de_la_obra(self):
        from django.urls import reverse
        Informe.objects.create(titulo='INF-0001', obra=self.obra)
        r = self.client.get(reverse('titulos_informes_obra', args=[self.obra.pk]))
        self.assertEqual(r.json(), {'titulos': ['INF-0001']})
        cliente = UsuarioBase.objects.create_user('cli', password='x', es_cliente=True)
        self.client.force_login(cliente)
        self.assertEqual(self.client.get(reverse('titulos_informes_obra', args=[self.obra.pk])).status_code, 403)

    def test_guarda_la_fecha_elegida(self):
        from django.urls import reverse
        from django.utils import timezone
        for url in (reverse('cargar_informe'), reverse('cargar_informe_obra', args=[self.obra.pk])):
            Informe.objects.all().delete()
            r = self._subir(url, '2025-03-14')
            self.assertEqual(r.status_code, 302)
            inf = Informe.objects.get()
            self.assertEqual(timezone.localtime(inf.fecha_creacion).date().isoformat(), '2025-03-14')

    def test_rechaza_fecha_futura(self):
        from datetime import timedelta
        from django.urls import reverse
        from django.utils import timezone
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self._subir(reverse('cargar_informe_obra', args=[self.obra.pk]), manana)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'no puede ser futura')
        self.assertFalse(Informe.objects.exists())

    def test_carga_varios_pdf_con_su_nombre_como_titulo(self):
        from django.urls import reverse
        from django.utils import timezone
        archivos = [self._pdf('INF 0340-2026 VIGAS.pdf'), self._pdf('INF-0341.PDF'), self._pdf('INF-0342.pdf')]
        r = self._subir(reverse('cargar_informe_obra', args=[self.obra.pk]), '2025-03-14', archivos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(sorted(Informe.objects.values_list('titulo', flat=True)),
                         ['INF 0340-2026 VIGAS', 'INF-0341', 'INF-0342'])
        self.assertTrue(all(timezone.localtime(i.fecha_creacion).date().isoformat() == '2025-03-14'
                            for i in Informe.objects.all()))
        self.assertTrue(all(i.obra_id == self.obra.pk for i in Informe.objects.all()))

    def test_si_uno_no_es_pdf_no_se_carga_ninguno(self):
        from django.urls import reverse
        malos = [
            self._pdf('foto.jpg', b'\xff\xd8', 'image/jpeg'),            # otra extensión
            self._pdf('falso.pdf', b'MZ ejecutable', 'application/pdf'),  # .pdf pero no es PDF
        ]
        for malo in malos:
            r = self._subir(reverse('cargar_informe'), '2025-03-14', [self._pdf(), malo])
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, malo.name)
            self.assertFalse(Informe.objects.exists())

    def test_avisa_si_la_obra_ya_tiene_un_informe_con_ese_nombre(self):
        from django.urls import reverse
        Informe.objects.create(titulo='INF-0001', obra=self.obra)
        r = self._subir(reverse('cargar_informe_obra', args=[self.obra.pk]), '2025-03-14')
        self.assertEqual(Informe.objects.filter(titulo='INF-0001').count(), 2)
        mensajes = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('mismo nombre' in m for m in mensajes), mensajes)


class PartesInformeTests(SimpleTestCase):

    def test_separa_numero_y_tipo(self):
        from core.templatetags.informes_tags import partes_informe
        casos = {
            'INF-0103-2024-COMPRESION-CILINDROS.xlsx_.pdf': ('INF 0103-2024', 'Compresión cilindros'),
            'INF-3580-2026-COMPRESION-CILINDROS.xlsx-1': ('INF 3580-2026', 'Compresión cilindros'),
            'INF 0340-2026 VIGAS FLEXION M 8V': ('INF 0340-2026', 'Vigas flexión M 8V'),
            'IN1234-26-DE-ALGO.pdf': ('INF 1234-26', 'De algo'),
            'Analisis_tecnico.pdf': ('', 'Analisis_tecnico'),
        }
        for titulo, (numero, tipo) in casos.items():
            p = partes_informe(titulo)
            self.assertEqual((p['numero'], p['tipo']), (numero, tipo), titulo)

    def test_familia_de_ensayo_para_el_color(self):
        from core.templatetags.informes_tags import partes_informe
        self.assertEqual(partes_informe('INF-0103-2024-COMPRESION-CILINDROS.pdf')['clase'], 'cil')
        self.assertEqual(partes_informe('INF1078-2026 COMPRESION CUBOS')['clase'], 'cub')
        self.assertEqual(partes_informe('INF 0340-2026 VIGAS FLEXION M 8V')['clase'], 'vig')
        self.assertEqual(partes_informe('Analisis_tecnico.pdf')['clase'], 'otro')


class ListaInformesObraTests(TestCase):
    """Registro de informes de la obra: búsqueda y borrado (solo superusuario)."""

    def setUp(self):
        from django.core.files.base import ContentFile
        from django.test import override_settings
        from users.models import FuncionarioGeolab
        self.tmp = tempfile.TemporaryDirectory()
        self.media = override_settings(MEDIA_ROOT=self.tmp.name)
        self.media.enable()
        c = Constructora.objects.create(codigo='BUC46', nombre='JAIMES', ciudad='Bucaramanga')
        self.obra = Obra.objects.create(nombre='LA GRANJA', codigo_obra='BUC46-5', constructora=c)
        otra = Obra.objects.create(nombre='OIBA', codigo_obra='BUC46-7', constructora=c)
        self.inf1 = Informe.objects.create(titulo='INF-0340-2026-COMPRESION-CILINDROS.xlsx.pdf', obra=self.obra,
                                           id_wp_original=5001)
        self.inf1.archivo.save('INF-0340.pdf', ContentFile(b'%PDF-1.4'))
        self.inf2 = Informe.objects.create(titulo='INF-0341-2026-VIGAS.pdf', obra=self.obra)
        self.ajeno = Informe.objects.create(titulo='INF-0999-2026.pdf', obra=otra)
        self.super = UsuarioBase.objects.create_superuser('root', password='x', es_geolab=True)
        FuncionarioGeolab.objects.create(user=self.super, area='admin')
        self.staff = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True)
        FuncionarioGeolab.objects.create(user=self.staff, area='admin')

    def tearDown(self):
        self.media.disable()
        self.tmp.cleanup()

    def _url(self, nombre='lista_informes_obra'):
        from django.urls import reverse
        return reverse(nombre, args=[self.obra.pk])

    def test_superusuario_ve_acciones_de_borrado_y_staff_no(self):
        self.client.force_login(self.super)
        r = self.client.get(self._url())
        self.assertContains(r, 'INF 0340-2026')
        self.assertContains(r, 'Compresión cilindros')
        self.assertContains(r, 'class="inf-del"')
        self.client.force_login(self.staff)
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'class="inf-del"')
        self.assertNotContains(r, 'id="infModal"')

    def test_busqueda_por_palabras_sin_tildes(self):
        self.client.force_login(self.staff)
        for q in ('INF 0340', 'compresión', '0340 cilindros'):
            r = self.client.get(self._url(), {'q': q})
            self.assertContains(r, 'INF 0340-2026', msg_prefix=q)
            self.assertNotContains(r, 'INF 0341-2026', msg_prefix=q)

    def test_superusuario_elimina_y_queda_en_bitacora(self):
        from core.models import InformeEliminado
        from django.core.files.storage import default_storage
        nombre = self.inf1.archivo.name
        self.assertTrue(default_storage.exists(nombre))
        self.client.force_login(self.super)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self._url('eliminar_informes'),
                                 {'informes': [self.inf1.pk, self.inf2.pk, self.ajeno.pk], 'next': self._url()})
        self.assertRedirects(r, self._url(), fetch_redirect_response=False)
        self.assertEqual(list(self.obra.informes.all()), [])
        self.assertTrue(Informe.objects.filter(pk=self.ajeno.pk).exists())   # de otra obra: no se toca
        self.assertFalse(default_storage.exists(nombre))
        reg = InformeEliminado.objects.get(id_wp_original=5001)
        self.assertEqual((reg.obra_codigo, reg.eliminado_por), ('BUC46-5', self.super))
        self.assertEqual(InformeEliminado.objects.count(), 2)

    def test_staff_no_superusuario_no_puede_eliminar(self):
        self.client.force_login(self.staff)
        self.client.post(self._url('eliminar_informes'), {'informes': [self.inf1.pk]})
        self.assertTrue(Informe.objects.filter(pk=self.inf1.pk).exists())

    def test_get_y_next_externo_no_borran_ni_redirigen_fuera(self):
        self.client.force_login(self.super)
        r = self.client.get(self._url('eliminar_informes'), {'informes': [self.inf1.pk]})
        self.assertTrue(Informe.objects.filter(pk=self.inf1.pk).exists())
        r = self.client.post(self._url('eliminar_informes'), {'informes': [self.inf2.pk], 'next': 'https://malo.com/'})
        self.assertRedirects(r, self._url(), fetch_redirect_response=False)


class ExpedienteObraTests(TestCase):
    """detalle_obra: solo staff, el director de la empresa o el cliente con la obra asignada."""

    def setUp(self):
        from users.models import FuncionarioGeolab
        self.c = Constructora.objects.create(codigo='BUC53', nombre='MARTINEZ', ciudad='Bucaramanga')
        otra = Constructora.objects.create(codigo='BUC46', nombre='JAIMES', ciudad='Bucaramanga')
        self.obra = Obra.objects.create(nombre='ALTOS DEL DIAMANTE', codigo_obra='BUC53-4', constructora=self.c,
                                        contacto='Ing. Laura')
        Informe.objects.create(titulo='INF-3618-2026-COMPRESION-CILINDROS.xlsx.pdf', obra=self.obra)
        self.staff = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True)
        FuncionarioGeolab.objects.create(user=self.staff, area='admin')

        def cliente(nombre, empresa, rol):
            u = UsuarioBase.objects.create_user(nombre, password='x', es_cliente=True)
            return ClienteExterno.objects.create(user=u, empresa=empresa, rol=rol)
        self.director = cliente('dir', self.c, 'director')
        self.ajeno = cliente('ajeno', otra, 'director')
        self.remitente = cliente('rem', self.c, 'remitente')

    def _get(self, user):
        from django.urls import reverse
        self.client.force_login(user)
        return self.client.get(reverse('detalle_obra', args=[self.obra.pk]))

    def test_staff_ve_el_expediente(self):
        r = self._get(self.staff)
        self.assertContains(r, 'Expediente de obra')
        self.assertContains(r, 'INF 3618-2026')
        self.assertContains(r, 'Ing. Laura')
        self.assertContains(r, 'Cargar informes')

    def test_director_de_la_empresa_entra_sin_acciones_de_staff(self):
        r = self._get(self.director.user)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Nueva remisión')

    def test_cliente_de_otra_empresa_o_sin_asignar_no_entra(self):
        self.assertRedirects(self._get(self.ajeno.user), '/', fetch_redirect_response=False)
        self.assertRedirects(self._get(self.remitente.user), '/', fetch_redirect_response=False)
        self.remitente.obras_asignadas.add(self.obra)
        self.assertEqual(self._get(self.remitente.user).status_code, 200)


class DirectorioEmpresasTests(TestCase):
    """Directorio y detalle de empresa: conteos correctos, sedes, orden natural y acceso."""

    def setUp(self):
        from users.models import FuncionarioGeolab
        self.staff = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True)
        FuncionarioGeolab.objects.create(user=self.staff, area='admin')
        self.buc = Constructora.objects.create(codigo='BUC53', nombre='MARTINEZ', ciudad='Bucaramanga')
        self.iba = Constructora.objects.create(codigo='IBA8', nombre='DYCO', ciudad='Ibagué')
        for n in (1, 2, 10):
            o = Obra.objects.create(nombre=f'OBRA {n}', codigo_obra=f'BUC53-{n}', constructora=self.buc)
            Informe.objects.create(titulo=f'INF-{n}.pdf', obra=o)
        for i in range(2):   # dos usuarios: con joins cruzados las obras salían x2
            u = UsuarioBase.objects.create_user(f'c{i}', password='x', es_cliente=True)
            ClienteExterno.objects.create(user=u, empresa=self.buc, rol='remitente')

    def test_conteos_no_se_multiplican(self):
        from django.urls import reverse
        self.client.force_login(self.staff)
        r = self.client.get(reverse('lista_constructoras'))
        buc = next(c for c in r.context['constructoras'] if c.pk == self.buc.pk)
        self.assertEqual((buc.num_obras, buc.num_usuarios, buc.num_informes), (3, 2, 3))

    def test_filtro_por_sede(self):
        from django.urls import reverse
        self.client.force_login(self.staff)
        r = self.client.get(reverse('lista_constructoras'), {'ciudad': 'Ibagué'})
        self.assertEqual([c.pk for c in r.context['constructoras']], [self.iba.pk])
        self.assertContains(r, 'Bucaramanga <span class="n">1</span>', html=False)

    def test_detalle_con_obras_en_orden_natural_y_usuarios(self):
        from django.urls import reverse
        self.client.force_login(self.staff)
        r = self.client.get(reverse('detalle_constructora', args=[self.buc.pk]))
        self.assertEqual([o.codigo_obra for o in r.context['obras']], ['BUC53-1', 'BUC53-2', 'BUC53-10'])
        self.assertEqual(r.context['total_informes'], 3)
        self.assertEqual(len(r.context['usuarios']), 2)

    def test_cliente_sin_perfil_no_rompe_el_detalle(self):
        from django.urls import reverse
        u = UsuarioBase.objects.create_user('suelto', password='x', es_cliente=True)
        self.client.force_login(u)
        r = self.client.get(reverse('detalle_constructora', args=[self.buc.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'core/pending.html')


class DescargarArchivosTests(TestCase):
    """WordPress repite nombres de PDF entre carpetas (las sedes comparten la
    numeración INF): el nombre solo no debe cruzar el PDF de una obra a otra."""

    URL = 'https://portal.geolabsas.co/wp-content/uploads/{}/INF-0425-2023-COMPRESION-CILINDROS.xlsx_.pdf'

    def setUp(self):
        c1 = Constructora.objects.create(codigo='IBA8', nombre='UNO', ciudad='Ibagué')
        c2 = Constructora.objects.create(codigo='BUC53', nombre='DOS', ciudad='Bucaramanga')
        o1 = Obra.objects.create(nombre='A', codigo_obra='IBA8-1', constructora=c1)
        o2 = Obra.objects.create(nombre='B', codigo_obra='BUC53-1', constructora=c2)
        self.a = Informe.objects.create(titulo='a', obra=o1, url_archivo_original=self.URL.format('2023/08'))
        self.b = Informe.objects.create(titulo='b', obra=o2, url_archivo_original=self.URL.format('2024/02'))

    def _run(self, *extra, media):
        out = StringIO()
        with self.settings(MEDIA_ROOT=media):
            call_command('descargar_archivos', *extra, stdout=out)
        return out.getvalue()

    def test_enlaza_local_por_carpeta_y_no_por_nombre(self):
        with tempfile.TemporaryDirectory() as media:
            for carpeta in ('2023/08', '2024/02'):
                ruta = Path(media, 'informes', carpeta)
                ruta.mkdir(parents=True)
                (ruta / 'INF-0425-2023-COMPRESION-CILINDROS.xlsx_.pdf').write_bytes(b'%PDF')
            self._run(media=media)
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(self.a.archivo.name, 'informes/2023/08/INF-0425-2023-COMPRESION-CILINDROS.xlsx_.pdf')
        self.assertEqual(self.b.archivo.name, 'informes/2024/02/INF-0425-2023-COMPRESION-CILINDROS.xlsx_.pdf')

    def test_descarga_cada_uno_aunque_compartan_nombre(self):
        from unittest import mock
        respuesta = mock.Mock(status_code=200, content=b'%PDF')
        with tempfile.TemporaryDirectory() as media, \
                mock.patch('requests.Session.get', return_value=respuesta) as get, \
                mock.patch('time.sleep'):
            self._run(media=media)
            self.assertEqual(get.call_count, 2)
            self.a.refresh_from_db()
            self.b.refresh_from_db()
            self.assertNotEqual(self.a.archivo.name, self.b.archivo.name)

    def test_sube_al_storage_lo_que_solo_esta_en_el_disco_del_servidor(self):
        # En producción MEDIA_ROOT es el disco del servidor (copia de uploads de WP) y el
        # storage es S3: enlazar la ruta sin subir el archivo deja NoSuchKey en el portal
        with tempfile.TemporaryDirectory() as disco, tempfile.TemporaryDirectory() as storage:
            ruta = Path(disco, 'informes', '2023', '08')
            ruta.mkdir(parents=True)
            (ruta / 'INF-0425-2023-COMPRESION-CILINDROS.xlsx_.pdf').write_bytes(b'%PDF-a')
            self.b.delete()
            with self.settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage',
                                                     'OPTIONS': {'location': storage}}}):
                self._run(media=disco)
                self.a.refresh_from_db()
                self.assertTrue(self.a.archivo.name.startswith('informes/'))
                self.assertEqual(self.a.archivo.read(), b'%PDF-a')
                self.assertTrue(Path(storage, self.a.archivo.name).exists())
                # --revisar no lo reporta como faltante; uno enlazado a una ruta inexistente sí
                self.a.archivo.name = 'informes/2025/12/no-esta.pdf'
                self.a.save(update_fields=['archivo'])
                salida = self._run('--revisar', media=disco)
                self.assertIn('NO existe en el storage: 1', salida)
                self._run('--reparar', media=disco)
                self.a.refresh_from_db()
                self.assertEqual(self.a.archivo.name, '')

    def test_revisar_y_reparar_pdf_compartido(self):
        Informe.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(archivo='informes/2026/10/x.pdf')
        with tempfile.TemporaryDirectory() as media:
            salida = self._run('--revisar', media=media)
            self.assertIn('1 archivos, 2 informes', salida)
            self.assertEqual(Informe.objects.filter(archivo='').count(), 0)
            self._run('--reparar', media=media)
        self.assertEqual(Informe.objects.filter(archivo='').count(), 2)


class PaginasErrorTests(TestCase):
    """Páginas 400/403/404/500 y CSRF con la ficha de Geolab (no las de Django)."""

    def test_404_y_csrf_desde_el_cliente(self):
        from django.urls import reverse
        r = self.client.get('/esta-pagina-no-existe/')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'F-ERR-404', status_code=404)
        self.assertContains(r, 'geolab-logo.png', status_code=404)
        r = Client(enforce_csrf_checks=True).post(reverse('login'), {'username': 'a', 'password': 'b'})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'Formulario vencido', status_code=403)

    def test_400_403_500_renderizan_sin_contexto(self):
        from django.test import RequestFactory
        from django.views import defaults
        req = RequestFactory().get('/')
        self.assertIn('F-ERR-400', defaults.bad_request(req, Exception()).content.decode())
        self.assertIn('F-ERR-403', defaults.permission_denied(req, Exception()).content.decode())
        cuerpo = defaults.server_error(req).content.decode()
        self.assertIn('F-ERR-500', cuerpo)
        self.assertIn('Reintentar', cuerpo)


class PanelStaffTests(TestCase):
    """Panel principal: agenda de falla (vencidas + 7 días) y obras activas sin conteos multiplicados."""

    def setUp(self):
        from users.models import FuncionarioGeolab
        u = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True, first_name='Ana')
        FuncionarioGeolab.objects.create(user=u, area='admin')
        self.client.force_login(u)
        c = Constructora.objects.create(codigo='BUC46', nombre='JAIMES', ciudad='Bucaramanga')
        self.obra = Obra.objects.create(nombre='LA GRANJA', codigo_obra='BUC46-5', constructora=c)

    def test_agenda_y_obras_activas(self):
        from datetime import timedelta
        from django.utils import timezone
        from solicitudes.models import Muestra, RemisionMuestras
        from solicitudes.views import crear_hoja_trabajo_y_resultados
        hoy = timezone.localdate()
        for _ in range(2):   # 2 remisiones + 3 informes: el conteo cruzado daría 6
            r = RemisionMuestras.objects.create(obra=self.obra, estado='completada')
            for n, (toma, edad) in enumerate([(hoy - timedelta(days=7), 7), (hoy - timedelta(days=10), 7), (hoy, 3)], 1):
                Muestra.objects.create(remision=r, numero_muestra=n, cantidad=1, tipo_muestra='concreto',
                                       dimension_especimen='6_pulg', fecha_toma=toma, edad_ensayo_dias=edad)
            crear_hoja_trabajo_y_resultados(r)
        for i in range(3):
            Informe.objects.create(titulo=f'INF-000{i}', obra=self.obra, fecha_creacion=timezone.now())
        r = self.client.get('/')
        self.assertTemplateUsed(r, 'core/home_staff.html')
        ctx = r.context
        self.assertEqual(ctx['ensayos_hoy'], 2)
        self.assertEqual(ctx['ensayos_vencidos'], 2)
        self.assertEqual([d['n'] for d in ctx['agenda']], [2, 0, 0, 2, 0, 0, 0])
        obra = ctx['obras_activas'][0]
        self.assertEqual((obra.informes_recientes, obra.remisiones_recientes), (3, 2))
        self.assertContains(r, 'Ana')
        self.assertContains(r, 'Agenda de falla')

