"""
Usuarios de Facturación: ciudades y secciones por usuario.

    python manage.py test facturacion.tests_permisos

Lo que se comprueba:
- Cada sección abre exactamente sus pantallas y APIs (matriz completa): lo que
  no tiene, lo rechaza SIN tocar datos, y lo que tiene funciona.
- Quitar una sección no rompe la operación de las otras (registrar sin
  histórico, generar sin repositorio, etc.).
- Ciudades: solo las suyas, la sesión se corrige si se las quitan.
- El resto del portal queda cerrado (middleware) y nadie más que un
  superusuario administra estos usuarios.
"""

import json
from unittest import mock

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from core.models import Obra
from users.models import Constructora, FuncionarioGeolab, UsuarioBase

from . import permisos
from .models import (
    AccesoFacturacion, CategoriaServicio, Factura, Impuesto, PrecioServicio,
    RegistroServicio, TipoServicio,
)
from .sede import SESSION_KEY

CLAVE = 'Clave-de-prueba-2026'


def crear_usuario_fx(username, ciudades, secciones, activo=True):
    u = UsuarioBase.objects.create_user(username, password=CLAVE, es_geolab=True, is_active=activo)
    FuncionarioGeolab.objects.create(user=u, area='facturacion')
    AccesoFacturacion.objects.create(usuario=u, ciudades=list(ciudades), secciones=list(secciones))
    return u


class DatosFacturacion(TestCase):
    """Dos sedes con empresa, obra, catálogo, precio, IVA, un registro pendiente y una factura."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = UsuarioBase.objects.create_user('admin_px', password=CLAVE, es_geolab=True)
        FuncionarioGeolab.objects.create(user=cls.admin, area='admin')
        cls.superu = UsuarioBase.objects.create_superuser('super_px', password=CLAVE, es_geolab=True)
        FuncionarioGeolab.objects.create(user=cls.superu, area='admin')

        cls.c_buc = Constructora.objects.create(nombre='Buc SAS', codigo='BUC1', ciudad='Bucaramanga')
        cls.c_bog = Constructora.objects.create(nombre='Bog SAS', codigo='BOG1', ciudad='Bogotá')
        cls.c_iba = Constructora.objects.create(nombre='Iba SAS', codigo='IBA1', ciudad='Ibagué')
        cls.obra = Obra.objects.create(nombre='Obra Buc', codigo_obra='BUC1-1', constructora=cls.c_buc)
        cls.o_bog = Obra.objects.create(nombre='Obra Bog', codigo_obra='BOG1-1', constructora=cls.c_bog)
        cls.cat = CategoriaServicio.objects.create(ciudad='Bucaramanga', codigo='1', nombre='CONCRETOS')
        cls.srv = TipoServicio.objects.create(categoria=cls.cat, codigo='1-1', nombre='Compresión')
        cls.srv_libre = TipoServicio.objects.create(categoria=cls.cat, codigo='1-9', nombre='Sin uso')
        cls.precio = PrecioServicio.objects.create(obra=cls.obra, tipo_servicio=cls.srv, precio=1000)
        cls.iva = Impuesto.objects.create(nombre='IVA', porcentaje='19.00')

    def setUp(self):
        self.registro = RegistroServicio.objects.create(
            obra=self.obra, tipo_servicio=self.srv, fecha_realizacion='2026-09-10', cantidad=2,
            numero_informe='INF-1', precio_unitario_congelado=1000, creado_por=self.admin,
        )
        facturado = RegistroServicio.objects.create(
            obra=self.obra, tipo_servicio=self.srv, fecha_realizacion='2026-08-10', cantidad=1,
            numero_informe='INF-0', precio_unitario_congelado=1000, creado_por=self.admin,
        )
        self.factura = Factura.objects.create(
            constructora=self.c_buc, obra=self.obra, fecha_inicio_periodo='2026-08-01', fecha_fin_periodo='2026-08-31',
            subtotal=1000, monto_iva=190, total=1190, pdf_archivo='facturas/2026/08/f.pdf',
        )
        facturado.factura = self.factura
        facturado.save()
        # El PDF real necesita WeasyPrint: no hace falta para probar permisos
        p = mock.patch('facturacion.views._generar_pdf_factura')
        p.start()
        self.addCleanup(p.stop)

    def entrar(self, user, ciudad='Bucaramanga'):
        self.client.force_login(user)
        if ciudad:
            s = self.client.session
            s[SESSION_KEY] = ciudad
            s.save()

    def huella(self):
        """Estado de todo lo que una pantalla podría cambiar."""
        return (
            list(RegistroServicio.objects.order_by('pk').values_list('pk', 'cantidad', 'numero_informe', 'factura_id')),
            list(Factura.objects.order_by('pk').values_list('pk', 'estado')),
            list(PrecioServicio.objects.order_by('pk').values_list('pk', 'precio')),
            list(CategoriaServicio.objects.order_by('pk').values_list('pk', 'codigo', 'nombre')),
            list(TipoServicio.objects.order_by('pk').values_list('pk', 'codigo', 'nombre')),
            list(Impuesto.objects.order_by('pk').values_list('pk', 'nombre', 'porcentaje', 'activo')),
        )

    # Una solicitud por cada ruta del módulo: (url_name, método, url, datos, json)
    def solicitudes(self):
        o, f, r, cat, srv = self.obra, self.factura, self.registro, self.cat, self.srv
        registro_json = json.dumps({'obra_id': o.pk, 'fecha_realizacion': '2026-09-11', 'envio_id': None,
                                    'servicios': [{'tipo_servicio_id': srv.pk, 'numero_informe': 'INF-X', 'cantidad': 1}]})
        return [
            ('dashboard_facturacion', 'get', reverse('dashboard_facturacion'), None, False),
            ('api_facturacion_mensual', 'get', reverse('api_facturacion_mensual'), None, False),
            ('catalogo_servicios', 'get', reverse('catalogo_servicios'), None, False),
            ('crear_categoria_facturacion', 'get', reverse('crear_categoria_facturacion'), None, False),
            ('crear_categoria_facturacion', 'post', reverse('crear_categoria_facturacion'), {'codigo': '5', 'nombre': 'NUEVA'}, False),
            ('editar_categoria_facturacion', 'get', reverse('editar_categoria_facturacion', args=[cat.pk]), None, False),
            ('editar_categoria_facturacion', 'post', reverse('editar_categoria_facturacion', args=[cat.pk]), {'codigo': '1', 'nombre': 'CAMBIADA'}, False),
            ('crear_servicio_facturacion', 'get', reverse('crear_servicio_facturacion'), None, False),
            ('crear_servicio_facturacion', 'post', reverse('crear_servicio_facturacion'), {'categoria': cat.pk, 'codigo': '1-5', 'nombre': 'Nuevo', 'norma': ''}, False),
            ('editar_servicio_facturacion', 'get', reverse('editar_servicio_facturacion', args=[srv.pk]), None, False),
            ('editar_servicio_facturacion', 'post', reverse('editar_servicio_facturacion', args=[srv.pk]), {'categoria': cat.pk, 'codigo': '1-1', 'nombre': 'Cambiado', 'norma': ''}, False),
            ('eliminar_servicio_facturacion', 'get', reverse('eliminar_servicio_facturacion', args=[self.srv_libre.pk]), None, False),
            ('eliminar_servicio_facturacion', 'post', reverse('eliminar_servicio_facturacion', args=[self.srv_libre.pk]), {}, False),
            ('precios_obras', 'get', reverse('precios_obras'), None, False),
            ('gestionar_precios_obra', 'get', reverse('gestionar_precios_obra', args=[o.pk]), None, False),
            ('guardar_precio_obra', 'post', reverse('guardar_precio_obra', args=[o.pk, self.precio.pk]),
             json.dumps({'precio': '2500', 'anterior': '1000'}), True),
            ('lista_impuestos', 'get', reverse('lista_impuestos'), None, False),
            ('crear_impuesto', 'get', reverse('crear_impuesto'), None, False),
            ('crear_impuesto', 'post', reverse('crear_impuesto'), {'nombre': 'RETE', 'porcentaje': '4', 'activo': 'on'}, False),
            ('editar_impuesto', 'get', reverse('editar_impuesto', args=[self.iva.pk]), None, False),
            ('editar_impuesto', 'post', reverse('editar_impuesto', args=[self.iva.pk]), {'nombre': 'IVA', 'porcentaje': '5', 'activo': 'on'}, False),
            ('crear_registro_facturacion', 'get', reverse('crear_registro_facturacion'), None, False),
            ('crear_registro_facturacion', 'post', reverse('crear_registro_facturacion'), registro_json, True),
            ('editar_registro_facturacion', 'get', reverse('editar_registro_facturacion', args=[r.pk]), None, False),
            ('editar_registro_facturacion', 'post', reverse('editar_registro_facturacion', args=[r.pk]),
             {'obra': o.pk, 'tipo_servicio': srv.pk, 'fecha_realizacion': '2026-09-10', 'numero_informe': 'CAMBIO', 'cantidad': 5}, False),
            ('eliminar_registro_facturacion', 'post', reverse('eliminar_registro_facturacion', args=[r.pk]), {}, False),
            ('historico_facturacion', 'get', reverse('historico_facturacion'), None, False),
            ('generar_factura', 'get', reverse('generar_factura') + f'?obra={o.pk}&fecha_inicio=2026-09-01&fecha_fin=2026-09-30', None, False),
            ('finalizar_factura', 'post', reverse('finalizar_factura'),
             {'obra_id': o.pk, 'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-09-30', 'registro_ids': [str(r.pk)]}, False),
            ('repositorio_clientes', 'get', reverse('repositorio_clientes'), None, False),
            ('repositorio_obras_cliente', 'get', reverse('repositorio_obras_cliente', args=[self.c_buc.pk]), None, False),
            ('repositorio_facturas_obra', 'get', reverse('repositorio_facturas_obra', args=[o.pk]), None, False),
            ('anular_factura', 'post', reverse('anular_factura', args=[f.pk]), {}, False),
            ('marcar_factura_pagada', 'post', reverse('marcar_factura_pagada', args=[f.pk]), {}, False),
            ('marcar_factura_pendiente', 'post', reverse('marcar_factura_pendiente', args=[f.pk]), {}, False),
            ('descargar_factura_pdf', 'get', reverse('descargar_factura_pdf', args=[f.pk]), None, False),
            ('api_get_obras_facturacion', 'get', reverse('api_get_obras_facturacion') + f'?constructora_id={self.c_buc.pk}', None, False),
            ('api_get_precio', 'get', reverse('api_get_precio') + f'?obra_id={o.pk}&tiposervicio_id={srv.pk}', None, False),
            ('api_buscar_servicios', 'get', reverse('api_buscar_servicios') + '?q=Comp', None, False),
        ]

    def pedir(self, metodo, url, datos, es_json):
        if metodo == 'get':
            return self.client.get(url)
        if es_json:
            return self.client.post(url, data=datos, content_type='application/json')
        return self.client.post(url, datos)


class MapaDeVistasTests(TestCase):
    """Deny by default: ninguna ruta del módulo queda sin decidir quién la abre."""

    def _nombres_del_modulo(self):
        nombres = set()

        def recorrer(patrones, prefijo=''):
            for p in patrones:
                if isinstance(p, URLResolver):
                    recorrer(p.url_patterns, prefijo + str(p.pattern))
                elif isinstance(p, URLPattern) and (prefijo + str(p.pattern)).startswith('facturacion/') and p.name:
                    nombres.add(p.name)
        recorrer(get_resolver().url_patterns)
        return nombres

    def test_toda_ruta_del_modulo_esta_en_el_mapa(self):
        nombres = self._nombres_del_modulo()
        self.assertGreater(len(nombres), 30)
        sin_decidir = nombres - set(permisos.VISTAS) - permisos.SIN_SECCION
        self.assertEqual(sin_decidir, set(), 'Agregar estas rutas a permisos.VISTAS')
        self.assertEqual(set(permisos.VISTAS) - nombres, set(), 'VISTAS menciona rutas que no existen')

    def test_cada_seccion_tiene_inicio_que_ella_misma_abre(self):
        self.assertEqual(set(permisos.INICIO), set(permisos.CLAVES))
        for clave, url_name in permisos.INICIO.items():
            self.assertIn(clave, permisos.VISTAS[url_name])


class MatrizDeSeccionesTests(DatosFacturacion):
    """
    Un usuario por sección (solo esa sección): cada ruta abre si y solo si el
    mapa lo dice. Lo rechazado no cambia nada en la base.
    """

    def test_matriz_completa(self):
        for clave in permisos.CLAVES:
            usuario = crear_usuario_fx(f'solo_{clave}', ['Bucaramanga'], [clave])
            self.entrar(usuario)
            inicio = permisos.url_inicio(usuario)
            self.assertEqual(inicio, reverse(permisos.INICIO[clave]))
            for url_name, metodo, url, datos, es_json in self.solicitudes():
                permitida = clave in permisos.VISTAS[url_name]
                with self.subTest(seccion=clave, vista=url_name, metodo=metodo):
                    antes = self.huella()
                    r = self.pedir(metodo, url, datos, es_json)
                    if not permitida:
                        if es_json or '/facturacion/api/' in url:
                            self.assertEqual(r.status_code, 403)
                            self.assertEqual(r.json()['status'], 'error')
                        else:
                            self.assertEqual(r.status_code, 302)
                            self.assertEqual(r.url, inicio)
                        self.assertEqual(self.huella(), antes, 'una solicitud rechazada cambió datos')
                    elif metodo == 'get':
                        if url_name == 'descargar_factura_pdf':
                            self.assertEqual(r.status_code, 302)
                            self.assertIn('/media/facturas/', r.url)
                        else:
                            self.assertEqual(r.status_code, 200, r.content[:300])
            self.client.logout()

    def test_rechazo_explica_que_seccion_falta(self):
        u = crear_usuario_fx('solo_panel', ['Bucaramanga'], ['panel'])
        self.entrar(u)
        r = self.client.get(reverse('historico_facturacion'), follow=True)
        self.assertContains(r, 'no tiene acceso a Histórico')
        r = self.client.get(reverse('api_get_precio'))
        self.assertIn('Registrar servicio', r.json()['message'])

    def test_acceso_completo_sigue_igual_para_el_staff(self):
        self.entrar(self.admin)
        for url_name, metodo, url, datos, es_json in self.solicitudes():
            if metodo != 'get':
                continue
            with self.subTest(vista=url_name):
                r = self.client.get(url)
                self.assertIn(r.status_code, (200, 302))
                if r.status_code == 302:
                    self.assertEqual(url_name, 'descargar_factura_pdf')


class OperacionSinOtrasSeccionesTests(DatosFacturacion):
    """Quitar una sección no rompe el trabajo que sí tiene el usuario."""

    def test_registrar_sin_historico_ni_precios(self):
        u = crear_usuario_fx('registra', ['Bucaramanga'], ['registrar'])
        self.entrar(u)
        r = self.client.get(reverse('crear_registro_facturacion'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'const PUEDE_PRECIOS = false;')
        self.assertContains(r, 'const PUEDE_HISTORICO = false;')
        self.assertNotContains(r, f'href="{reverse("historico_facturacion")}"')
        # Las APIs que usa la pantalla responden
        obras = self.client.get(reverse('api_get_obras_facturacion'), {'constructora_id': self.c_buc.pk}).json()
        self.assertEqual([o['id'] for o in obras['obras']], [self.obra.pk])
        precio = self.client.get(reverse('api_get_precio'), {'obra_id': self.obra.pk, 'tiposervicio_id': self.srv.pk}).json()
        self.assertEqual(precio['precio'], '1000.00')
        r = self.client.post(reverse('crear_registro_facturacion'), data=json.dumps({
            'obra_id': self.obra.pk, 'fecha_realizacion': '2026-09-12', 'envio_id': None,
            'servicios': [{'tipo_servicio_id': self.srv.pk, 'numero_informe': 'INF-5', 'cantidad': 3}],
        }), content_type='application/json')
        self.assertEqual(r.json()['status'], 'success')
        self.assertTrue(RegistroServicio.objects.filter(numero_informe='INF-5', creado_por=u).exists())

    def test_generar_sin_repositorio_lleva_al_pdf_de_la_nueva(self):
        u = crear_usuario_fx('genera', ['Bucaramanga'], ['generar'])
        self.entrar(u)
        r = self.client.get(reverse('generar_factura'), {'obra': self.obra.pk, 'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-09-30'})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, f'href="{reverse("repositorio_clientes")}"')
        self.assertNotContains(r, 'Ver su histórico')
        r = self.client.post(reverse('finalizar_factura'), {
            'obra_id': self.obra.pk, 'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-09-30',
            'registro_ids': [str(self.registro.pk)],
        })
        nueva = Factura.objects.exclude(pk=self.factura.pk).get()
        self.assertEqual(r.url, reverse('generar_factura') + f'?generada={nueva.pk}')
        r = self.client.get(r.url)
        self.assertContains(r, reverse('descargar_factura_pdf', args=[nueva.pk]))
        # Doble clic: tampoco lo manda al repositorio
        r = self.client.post(reverse('finalizar_factura'), {
            'obra_id': self.obra.pk, 'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-09-30',
            'registro_ids': [str(self.registro.pk)],
        })
        self.assertEqual(Factura.objects.count(), 2)
        self.assertEqual(r.url, reverse('generar_factura') + f'?generada={nueva.pk}')
        # Y no puede anularla ni marcarla pagada
        self.client.post(reverse('anular_factura', args=[nueva.pk]))
        nueva.refresh_from_db()
        self.assertEqual(nueva.estado, 'PENDIENTE')

    def test_generar_con_repositorio_sigue_yendo_al_repositorio(self):
        u = crear_usuario_fx('genera_repo', ['Bucaramanga'], ['generar', 'repositorio'])
        self.entrar(u)
        r = self.client.post(reverse('finalizar_factura'), {
            'obra_id': self.obra.pk, 'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-09-30',
            'registro_ids': [str(self.registro.pk)],
        })
        self.assertEqual(r.url, reverse('repositorio_facturas_obra', args=[self.obra.pk]))

    def test_historico_sin_registrar_edita_y_elimina(self):
        u = crear_usuario_fx('historia', ['Bucaramanga'], ['historico'])
        self.entrar(u)
        r = self.client.get(reverse('historico_facturacion'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, f'href="{reverse("crear_registro_facturacion")}"')
        self.client.post(reverse('editar_registro_facturacion', args=[self.registro.pk]), {
            'obra': self.obra.pk, 'tipo_servicio': self.srv.pk, 'fecha_realizacion': '2026-09-10',
            'numero_informe': 'INF-1 corregido', 'cantidad': 4,
        })
        self.registro.refresh_from_db()
        self.assertEqual((self.registro.cantidad, self.registro.numero_informe), (4, 'INF-1 corregido'))
        self.client.post(reverse('eliminar_registro_facturacion', args=[self.registro.pk]))
        self.assertFalse(RegistroServicio.objects.filter(pk=self.registro.pk).exists())

    def test_repositorio_sin_generar_cambia_estados(self):
        u = crear_usuario_fx('cobra', ['Bucaramanga'], ['repositorio'])
        self.entrar(u)
        r = self.client.get(reverse('repositorio_facturas_obra', args=[self.obra.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Nueva factura')
        self.client.post(reverse('marcar_factura_pagada', args=[self.factura.pk]))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.estado, 'PAGADA')
        self.client.post(reverse('marcar_factura_pendiente', args=[self.factura.pk]))
        self.client.post(reverse('anular_factura', args=[self.factura.pk]))
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.estado, 'ANULADA')

    def test_precios_sin_catalogo_guarda_por_fila(self):
        u = crear_usuario_fx('tarifa', ['Bucaramanga'], ['precios'])
        self.entrar(u)
        r = self.client.get(reverse('gestionar_precios_obra', args=[self.obra.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, f'href="{reverse("detalle_obra", args=[self.obra.pk])}"')
        r = self.client.post(reverse('guardar_precio_obra', args=[self.obra.pk, self.precio.pk]),
                             data=json.dumps({'precio': '2500', 'anterior': '1000'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.precio.refresh_from_db()
        self.assertEqual(self.precio.precio, 2500)

    def test_catalogo_e_impuestos_por_separado(self):
        u = crear_usuario_fx('catalogo', ['Bucaramanga'], ['catalogo'])
        self.entrar(u)
        self.client.post(reverse('crear_servicio_facturacion'), {'categoria': self.cat.pk, 'codigo': '1-5', 'nombre': 'Nuevo', 'norma': ''})
        self.assertTrue(TipoServicio.objects.filter(codigo='1-5').exists())
        self.client.post(reverse('editar_impuesto', args=[self.iva.pk]), {'nombre': 'IVA', 'porcentaje': '5', 'activo': 'on'})
        self.iva.refresh_from_db()
        self.assertEqual(str(self.iva.porcentaje), '19.00')

        u2 = crear_usuario_fx('impuestos', ['Bucaramanga'], ['impuestos'])
        self.entrar(u2)
        self.client.post(reverse('editar_impuesto', args=[self.iva.pk]), {'nombre': 'IVA', 'porcentaje': '5', 'activo': 'on'})
        self.iva.refresh_from_db()
        self.assertEqual(str(self.iva.porcentaje), '5.00')

    def test_panel_solo_muestra_enlaces_permitidos(self):
        u = crear_usuario_fx('mira', ['Bucaramanga'], ['panel'])
        self.entrar(u)
        r = self.client.get(reverse('dashboard_facturacion'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for prohibida in ('crear_registro_facturacion', 'generar_factura', 'historico_facturacion',
                          'repositorio_clientes', 'precios_obras', 'catalogo_servicios', 'lista_impuestos',
                          'usuarios_facturacion'):
            self.assertNotIn(f'href="{reverse(prohibida)}', html, prohibida)
        self.assertNotIn(f'href="{reverse("home")}"', html)   # sin "Volver al portal"
        self.assertNotIn('id="notificacionesBtn"', html)

    def test_menu_lateral_muestra_solo_lo_suyo(self):
        u = crear_usuario_fx('mixto', ['Bucaramanga'], ['registrar', 'repositorio', 'impuestos'])
        self.entrar(u)
        html = self.client.get(reverse('crear_registro_facturacion')).content.decode()
        for visible in ('crear_registro_facturacion', 'repositorio_clientes', 'lista_impuestos'):
            self.assertIn(f'href="{reverse(visible)}"', html)
        for oculta in ('dashboard_facturacion', 'generar_factura', 'historico_facturacion', 'precios_obras', 'catalogo_servicios'):
            self.assertNotIn(f'href="{reverse(oculta)}"', html)
        self.assertIn('OPERACIÓN', html)
        self.assertNotIn('>PANEL<', html)
        # El logo lleva a su inicio, que no es el panel
        self.assertIn(f'href="{reverse("crear_registro_facturacion")}" class="sidebar-brand', html)

    def test_cambio_de_permisos_aplica_en_la_siguiente_solicitud(self):
        u = crear_usuario_fx('cambia', ['Bucaramanga'], ['historico'])
        self.entrar(u)
        self.assertEqual(self.client.get(reverse('historico_facturacion')).status_code, 200)
        AccesoFacturacion.objects.filter(usuario=u).update(secciones=['panel'])
        r = self.client.get(reverse('historico_facturacion'))
        self.assertEqual(r.url, reverse('dashboard_facturacion'))


class CiudadesTests(DatosFacturacion):

    def test_una_ciudad_se_elige_sola(self):
        u = crear_usuario_fx('bog', ['Bogotá'], ['panel', 'historico'])
        self.entrar(u, ciudad=None)
        r = self.client.get(reverse('historico_facturacion'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session[SESSION_KEY], 'Bogotá')
        r = self.client.get(reverse('seleccionar_ciudad_facturacion'))
        self.assertEqual(r.url, reverse('dashboard_facturacion'))
        html = self.client.get(reverse('dashboard_facturacion')).content.decode()
        self.assertNotIn('CAMBIAR', html)

    def test_varias_ciudades_solo_lista_las_suyas(self):
        u = crear_usuario_fx('dos', ['Bogotá', 'Ibagué'], ['panel'])
        self.entrar(u, ciudad=None)
        r = self.client.get(reverse('seleccionar_ciudad_facturacion'))
        self.assertEqual([c for c, _n in r.context['ciudades']], ['Bogotá', 'Ibagué'])
        self.assertNotContains(r, 'Bucaramanga')
        self.assertNotContains(r, 'sin ciudad asignada')
        # Forzar otra ciudad por POST no sirve
        self.client.post(reverse('seleccionar_ciudad_facturacion'), {'ciudad': 'Bucaramanga'})
        self.assertNotIn(SESSION_KEY, self.client.session)
        r = self.client.post(reverse('seleccionar_ciudad_facturacion'), {'ciudad': 'Ibagué'})
        self.assertEqual(r.url, reverse('dashboard_facturacion'))
        self.assertEqual(self.client.session[SESSION_KEY], 'Ibagué')

    def test_ciudad_quitada_en_la_sesion_vuelve_al_selector(self):
        u = crear_usuario_fx('quitar', ['Bucaramanga', 'Bogotá'], ['historico'])
        self.entrar(u, ciudad='Bucaramanga')
        self.assertEqual(self.client.get(reverse('historico_facturacion')).status_code, 200)
        AccesoFacturacion.objects.filter(usuario=u).update(ciudades=['Bogotá', 'Ibagué'])
        r = self.client.get(reverse('historico_facturacion'))
        self.assertIn(reverse('seleccionar_ciudad_facturacion'), r.url)
        self.assertNotIn(SESSION_KEY, self.client.session)
        # Las APIs contestan JSON, no redirigen
        s = self.client.session
        s[SESSION_KEY] = 'Bucaramanga'
        s.save()
        r = self.client.get(reverse('api_get_obras_facturacion'), {'constructora_id': self.c_buc.pk})
        self.assertEqual(r.status_code, 403)

    def test_objetos_de_otra_ciudad_dan_404(self):
        u = crear_usuario_fx('bog404', ['Bogotá'], ['repositorio', 'precios'])
        self.entrar(u, ciudad=None)
        self.assertEqual(self.client.get(reverse('repositorio_facturas_obra', args=[self.obra.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('gestionar_precios_obra', args=[self.obra.pk])).status_code, 404)
        r = self.client.post(reverse('anular_factura', args=[self.factura.pk]))
        self.assertEqual(r.status_code, 404)
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.estado, 'PENDIENTE')

    def test_mayusculas_y_tildes_de_la_ciudad_guardada(self):
        u = crear_usuario_fx('may', ['bogotá'], ['panel'])
        self.assertEqual(permisos.ciudades_de(u), ['Bogotá'])


class SinPermisosTests(DatosFacturacion):

    def test_sin_secciones_o_sin_ciudades_ve_explicacion_sin_bucles(self):
        for ciudades, secciones in ((['Bucaramanga'], []), ([], ['panel']), (['Medellín'], ['panel'])):
            with self.subTest(ciudades=ciudades, secciones=secciones):
                u = crear_usuario_fx(f'vacio{len(ciudades)}{len(secciones)}{ciudades[:1]}', ciudades, secciones)
                self.entrar(u, ciudad=None)
                r = self.client.get('/', follow=True)
                self.assertEqual(r.status_code, 403)
                self.assertContains(r, 'todavía no tiene ciudades o secciones', status_code=403)
                self.assertLessEqual(len(r.redirect_chain), 2)
                r = self.client.get(reverse('api_get_obras_facturacion'))
                self.assertEqual(r.status_code, 403)
                self.client.logout()

    def test_sin_registro_de_acceso(self):
        u = UsuarioBase.objects.create_user('sin_acceso', password=CLAVE, es_geolab=True)
        FuncionarioGeolab.objects.create(user=u, area='facturacion')
        self.entrar(u, ciudad=None)
        r = self.client.get(reverse('dashboard_facturacion'))
        self.assertEqual(r.status_code, 403)


class EncierroEnFacturacionTests(DatosFacturacion):
    """El Usuario de Facturación no sale del módulo (middleware, lista blanca)."""

    def test_rutas_del_portal_cerradas(self):
        u = crear_usuario_fx('encerrado', ['Bucaramanga'], list(permisos.CLAVES))
        self.entrar(u)
        rutas = [reverse('lista_constructoras'), reverse('detalle_obra', args=[self.obra.pk]),
                 '/usuarios/', '/calidad/', '/remisiones/', '/ensayos/hojas-trabajo/', '/notificaciones/',
                 '/admin/']
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                r = self.client.get(ruta)
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.url, reverse('seleccionar_ciudad_facturacion'))
        r = self.client.get('/notificaciones/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 403)
        # La raíz lo manda a Facturación; el logout sigue funcionando
        r = self.client.get('/')
        self.assertEqual(r.url, reverse('seleccionar_ciudad_facturacion'))
        self.client.post(reverse('logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_no_es_administrador_del_portal(self):
        u = crear_usuario_fx('noadmin', ['Bucaramanga'], ['panel'])
        self.assertFalse(u.es_admin_geolab)
        self.assertFalse(u.es_admin_sgc)
        self.assertFalse(u.es_tecnico_laboratorio)
        self.assertFalse(u.is_staff)

    def test_no_recibe_correos_de_remisiones_ni_aparece_en_accesos_de_calidad(self):
        UsuarioBase.objects.filter(pk=crear_usuario_fx('correo', ['Bucaramanga'], ['panel']).pk).update(email='fx@geolab.test')
        self.admin.email = 'admin@geolab.test'
        self.admin.save()
        correos = list(UsuarioBase.objects.filter(es_geolab=True, is_active=True, email__isnull=False)
                       .exclude(email='').exclude(perfil_geolab__area='facturacion').values_list('email', flat=True))
        self.assertIn('admin@geolab.test', correos)
        self.assertNotIn('fx@geolab.test', correos)
        self.entrar(self.superu)
        r = self.client.get(reverse('gestionar_accesos'))
        self.assertNotContains(r, 'correo')


class AdministrarUsuariosTests(DatosFacturacion):
    """Solo un superusuario crea, edita y desactiva Usuarios de Facturación."""

    def _datos(self, **extra):
        d = {'username': 'ana.cobros', 'nombre': 'Ana', 'apellido': 'Ruiz', 'email': 'ana@geolab.test',
             'password1': 'Facturas-Seguras-77', 'password2': 'Facturas-Seguras-77',
             'ciudades': ['Bogotá'], 'secciones': ['repositorio', 'panel']}
        d.update(extra)
        return d

    def test_solo_superusuario(self):
        fx = crear_usuario_fx('fx_intruso', ['Bucaramanga'], list(permisos.CLAVES))
        for quien in (self.admin, fx):
            with self.subTest(usuario=quien.username):
                self.entrar(quien)
                for url in (reverse('usuarios_facturacion'), reverse('crear_usuario_facturacion'),
                            reverse('editar_usuario_facturacion', args=[fx.pk])):
                    r = self.client.get(url)
                    self.assertEqual(r.status_code, 302, url)
                r = self.client.post(reverse('crear_usuario_facturacion'), self._datos())
                self.assertFalse(UsuarioBase.objects.filter(username='ana.cobros').exists())
                self.client.post(reverse('estado_usuario_facturacion', args=[fx.pk]))
                fx.refresh_from_db()
                self.assertTrue(fx.is_active)
                html = self.client.get(reverse('crear_registro_facturacion')).content.decode()
                self.assertNotIn(reverse('usuarios_facturacion'), html)

    def test_crear_y_entrar(self):
        self.entrar(self.superu)
        self.assertContains(self.client.get(reverse('crear_registro_facturacion')), reverse('usuarios_facturacion'))
        r = self.client.post(reverse('crear_usuario_facturacion'), self._datos())
        self.assertRedirects(r, reverse('usuarios_facturacion'), fetch_redirect_response=False)
        u = UsuarioBase.objects.get(username='ana.cobros')
        self.assertTrue(u.es_geolab and u.es_usuario_facturacion)
        self.assertFalse(u.is_staff or u.is_superuser or u.es_admin_geolab)
        self.assertEqual(u.acceso_facturacion.ciudades, ['Bogotá'])
        self.assertEqual(u.acceso_facturacion.secciones, ['panel', 'repositorio'])   # en el orden del menú
        self.assertEqual(u.acceso_facturacion.actualizado_por, self.superu)
        lista = self.client.get(reverse('usuarios_facturacion'))
        self.assertContains(lista, 'ana.cobros')
        self.assertContains(lista, 'Repositorio de facturas')
        # Entra con su clave y aterriza en su panel de Bogotá
        self.client.logout()
        self.assertTrue(self.client.login(username='ana.cobros', password='Facturas-Seguras-77'))
        r = self.client.get('/', follow=True)
        self.assertEqual(r.request['PATH_INFO'], reverse('dashboard_facturacion'))
        self.assertEqual(self.client.session[SESSION_KEY], 'Bogotá')

    def test_validaciones(self):
        self.entrar(self.superu)
        casos = [
            (self._datos(ciudades=[]), 'ciudades'),
            (self._datos(secciones=[]), 'secciones'),
            (self._datos(ciudades=['Medellín']), 'ciudades'),
            (self._datos(secciones=['usuarios']), 'secciones'),
            (self._datos(password2='otra-cosa-77'), 'password2'),
            (self._datos(password1='123', password2='123'), 'password1'),
            (self._datos(username='ADMIN_PX'), 'username'),
            (self._datos(password1='', password2=''), 'password1'),
        ]
        for datos, campo in casos:
            with self.subTest(campo=campo, datos=datos):
                r = self.client.post(reverse('crear_usuario_facturacion'), datos)
                self.assertEqual(r.status_code, 200)
                self.assertIn(campo, r.context['form'].errors)
        self.assertFalse(UsuarioBase.objects.filter(username='ana.cobros').exists())
        self.assertFalse(FuncionarioGeolab.objects.filter(area='facturacion').exists())

    def test_falla_a_medias_no_deja_usuario_suelto(self):
        self.entrar(self.superu)
        with mock.patch('facturacion.views_usuarios.AccesoFacturacion.objects.create', side_effect=RuntimeError('caída')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('crear_usuario_facturacion'), self._datos())
        self.assertFalse(UsuarioBase.objects.filter(username='ana.cobros').exists())

    def test_editar_permisos_y_clave(self):
        u = crear_usuario_fx('edita', ['Bucaramanga'], ['panel'])
        self.entrar(self.superu)
        r = self.client.get(reverse('editar_usuario_facturacion', args=[u.pk]))
        self.assertContains(r, 'value="Bucaramanga" checked')
        r = self.client.post(reverse('editar_usuario_facturacion', args=[u.pk]), self._datos(
            username='edita', password1='', password2='', ciudades=['Bucaramanga', 'Ibagué'], secciones=['historico']))
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertTrue(u.check_password(CLAVE))             # clave en blanco: se conserva
        self.assertEqual(u.acceso_facturacion.secciones, ['historico'])
        self.assertEqual(u.acceso_facturacion.ciudades, ['Bucaramanga', 'Ibagué'])
        self.client.post(reverse('editar_usuario_facturacion', args=[u.pk]), self._datos(
            username='edita', password1='Nueva-Clave-2026', password2='Nueva-Clave-2026'))
        u.refresh_from_db()
        self.assertTrue(u.check_password('Nueva-Clave-2026'))

    def test_no_se_puede_editar_a_otro_tipo_de_usuario(self):
        self.entrar(self.superu)
        for otro in (self.admin, self.superu):
            self.assertEqual(self.client.get(reverse('editar_usuario_facturacion', args=[otro.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse('estado_usuario_facturacion', args=[otro.pk])).status_code, 404)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_desactivar_corta_la_sesion_abierta(self):
        u = crear_usuario_fx('corta', ['Bucaramanga'], ['panel'])
        otro = self.client_class()
        otro.force_login(u)
        self.assertEqual(otro.get(reverse('dashboard_facturacion')).status_code, 200)
        self.entrar(self.superu)
        self.client.post(reverse('estado_usuario_facturacion', args=[u.pk]))
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        r = otro.get(reverse('dashboard_facturacion'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('login'), r.url)
        self.client.post(reverse('estado_usuario_facturacion', args=[u.pk]))
        u.refresh_from_db()
        self.assertTrue(u.is_active)
