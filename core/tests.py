"""
Tests de core: normalización y sincronización desde WordPress.

    python manage.py test core
"""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
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

