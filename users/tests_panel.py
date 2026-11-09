"""
Panel de usuarios (/usuarios/panel/): solo superusuarios, un formulario para
todos los roles. Se prueba que cada rol creado desde el panel queda con el
acceso que dice tener, y que el panel no deja cuentas a medias.

    python manage.py test users.tests_panel
"""

from django.test import TestCase
from django.urls import reverse

from calidad.models import AccesoAreaUsuario, AccesoCarpetaUsuario, AreaCalidad, Carpeta
from core.models import Obra
from facturacion.models import AccesoFacturacion
from users.models import ClienteExterno, Constructora, FuncionarioGeolab, UsuarioBase

CLAVE = 'Geolab.Panel.2026'


def geolab(username, area, **extra):
    u = UsuarioBase.objects.create_user(username, password=CLAVE, es_geolab=True, **extra)
    FuncionarioGeolab.objects.create(user=u, area=area)
    return u


class PanelBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.super = UsuarioBase.objects.create_user('jefe', password=CLAVE, es_geolab=True,
                                                    is_superuser=True, is_staff=True)
        FuncionarioGeolab.objects.create(user=cls.super, area='admin')
        cls.marval = Constructora.objects.create(nombre='MARVAL SAS', codigo='BUC46', ciudad='Bucaramanga')
        cls.otra = Constructora.objects.create(nombre='OTRA SAS', codigo='BOG3', ciudad='Bogotá')
        cls.obra1 = Obra.objects.create(nombre='Torre 1', codigo_obra='BUC46-1', constructora=cls.marval)
        cls.obra2 = Obra.objects.create(nombre='Torre 2', codigo_obra='BUC46-2', constructora=cls.marval)
        cls.ajena = Obra.objects.create(nombre='Ajena', codigo_obra='BOG3-1', constructora=cls.otra)
        cls.area1 = AreaCalidad.objects.create(numero=1, nombre='Gestión directiva')
        cls.area2 = AreaCalidad.objects.create(numero=2, nombre='Laboratorio')

    def setUp(self):
        self.client.force_login(self.super)

    def datos(self, rol, username='nueva', **extra):
        d = {'rol': rol, 'username': username, 'nombre': 'Ana', 'apellido': 'Ruiz',
             'email': f'{username}@correo.com', 'password1': CLAVE, 'password2': CLAVE}
        d.update(extra)
        return d

    def crear(self, rol, **extra):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos(rol, **extra))
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        return UsuarioBase.objects.get(username=extra.get('username', 'nueva'))


class AccesoAlPanelTests(PanelBase):
    def test_solo_superusuario(self):
        rutas = [reverse('panel_usuarios'), reverse('panel_usuario_nuevo'),
                 reverse('panel_usuario', args=[self.super.pk]),
                 reverse('panel_obras_empresa', args=[self.marval.pk])]
        for area in ('admin', 'tecnico', 'calidad', 'facturacion'):
            u = geolab(f'no_{area}', area)
            self.client.force_login(u)
            for ruta in rutas:
                r = self.client.get(ruta)
                self.assertNotEqual(r.status_code, 200, f'{area} abrió {ruta}')
            r = self.client.post(reverse('panel_usuario_estado', args=[self.super.pk]))
            self.assertNotEqual(r.status_code, 200)
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_active)

    def test_superusuario_ve_todo(self):
        r = self.client.get(reverse('panel_usuarios'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'jefe')

    def test_tecnico_ya_no_gestiona_clientes(self):
        """Antes /usuarios/ solo pedía es_geolab: un técnico podía crear y desactivar clientes."""
        self.client.force_login(geolab('tec', 'tecnico'))
        for ruta in (reverse('lista_usuarios_cliente'), reverse('crear_usuario_cliente')):
            self.assertEqual(self.client.get(ruta).status_code, 302)
        cli = UsuarioBase.objects.create_user('cli', password=CLAVE, es_cliente=True)
        perfil = ClienteExterno.objects.create(user=cli, empresa=self.marval, rol='director')
        r = self.client.post(reverse('toggle_estado_usuario', args=[perfil.pk]))
        self.assertEqual(r.status_code, 403)
        cli.refresh_from_db()
        self.assertTrue(cli.is_active)

    def test_admin_sigue_gestionando_clientes(self):
        self.client.force_login(geolab('adm', 'admin'))
        self.assertEqual(self.client.get(reverse('lista_usuarios_cliente')).status_code, 200)


class CrearCadaRolTests(PanelBase):
    def test_roles_de_geolab_quedan_con_su_perfil(self):
        for i, area in enumerate(('admin', 'lab', 'recepcion', 'tecnico', 'calidad')):
            u = self.crear(area, username=f'g{i}', codigo_empleado=f'E-{i}')
            self.assertTrue(u.es_geolab)
            self.assertFalse(u.es_cliente)
            self.assertFalse(u.is_superuser)
            self.assertEqual(u.perfil_geolab.area, area)
            self.assertEqual(u.perfil_geolab.codigo_empleado, f'E-{i}')
            self.assertTrue(u.check_password(CLAVE))
        self.assertTrue(UsuarioBase.objects.get(username='g0').es_admin_geolab)
        self.assertFalse(UsuarioBase.objects.get(username='g3').es_admin_geolab)
        self.assertTrue(UsuarioBase.objects.get(username='g4').es_coordinador_calidad)

    def test_usuario_de_facturacion_y_su_acceso(self):
        u = self.crear('facturacion', ciudades=['Bogotá'], secciones=['repositorio', 'panel'])
        self.assertTrue(u.es_usuario_facturacion)
        acceso = AccesoFacturacion.objects.get(usuario=u)
        self.assertEqual(acceso.ciudades, ['Bogotá'])
        self.assertEqual(acceso.secciones, ['panel', 'repositorio'])  # orden del menú
        # Y de verdad queda encerrado: fuera de Facturación lo devuelve
        self.client.force_login(u)
        self.assertEqual(self.client.get('/empresas/').status_code, 302)

    def test_facturacion_sin_ciudad_o_seccion_no_se_guarda(self):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('facturacion', secciones=['panel']))
        self.assertEqual(r.status_code, 200)
        self.assertIn('ciudades', r.context['form'].errors)
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('facturacion', ciudades=['Bogotá']))
        self.assertIn('secciones', r.context['form'].errors)
        self.assertFalse(UsuarioBase.objects.filter(username='nueva').exists())

    def test_tecnico_con_areas_de_calidad(self):
        u = self.crear('tecnico', **{f'calidad_{self.area1.pk}': 'edicion', f'calidad_{self.area2.pk}': 'lectura'})
        accesos = {a.area_id: a.puede_editar for a in AccesoAreaUsuario.objects.filter(usuario=u)}
        self.assertEqual(accesos, {self.area1.pk: True, self.area2.pk: False})

    def test_usuario_de_calidad_pasa_a_sus_carpetas(self):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('calidad_usuario'))
        u = UsuarioBase.objects.get(username='nueva')
        self.assertRedirects(r, reverse('panel_usuario_carpetas', args=[u.pk]))
        self.assertTrue(u.es_usuario_calidad)
        raiz = Carpeta.objects.create(nombre='Formatos', area=self.area1)
        Carpeta.objects.create(nombre='Otra', area=self.area2)
        self.client.post(reverse('panel_usuario_carpetas', args=[u.pk]), {f'cargar_{raiz.pk}': 'on'})
        g = AccesoCarpetaUsuario.objects.get(usuario=u)
        self.assertEqual((g.carpeta_id, g.puede_ver, g.puede_cargar, g.puede_eliminar), (raiz.pk, True, True, False))

    def test_carpetas_solo_para_usuarios_de_calidad(self):
        r = self.client.get(reverse('panel_usuario_carpetas', args=[self.super.pk]))
        self.assertEqual(r.status_code, 404)

    def test_director(self):
        u = self.crear('director', empresa=self.marval.pk, cargo='Gerente')
        self.assertTrue(u.es_cliente)
        self.assertFalse(u.es_geolab)
        self.assertEqual((u.perfil_cliente.empresa, u.perfil_cliente.rol, u.perfil_cliente.cargo),
                         (self.marval, 'director', 'Gerente'))
        self.assertFalse(FuncionarioGeolab.objects.filter(user=u).exists())

    def test_residente_con_obras(self):
        u = self.crear('residente', empresa=self.marval.pk, obras=[self.obra1.pk])
        self.assertEqual(list(u.perfil_cliente.obras_asignadas.all()), [self.obra1])

    def test_residente_no_recibe_obras_de_otra_empresa(self):
        r = self.client.post(reverse('panel_usuario_nuevo'),
                             self.datos('residente', empresa=self.marval.pk, obras=[self.obra1.pk, self.ajena.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('obras', r.context['form'].errors)
        self.assertFalse(UsuarioBase.objects.filter(username='nueva').exists())

    def test_cliente_necesita_empresa_y_correo(self):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('remitente', email=''))
        errores = r.context['form'].errors
        self.assertIn('empresa', errores)
        self.assertIn('email', errores)

    def test_usuario_y_correo_repetidos(self):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('admin', username='JEFE'))
        self.assertIn('username', r.context['form'].errors)
        self.crear('admin', username='uno', email='x@correo.com')
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('admin', username='dos', email='X@correo.com'))
        self.assertIn('email', r.context['form'].errors)

    def test_contrasena_debil_o_distinta(self):
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('admin', password1='12345678', password2='12345678'))
        self.assertIn('password1', r.context['form'].errors)
        r = self.client.post(reverse('panel_usuario_nuevo'), self.datos('admin', password2='otra.cosa.2026'))
        self.assertIn('password2', r.context['form'].errors)

    def test_crear_superusuario_sin_admin_de_django(self):
        u = self.crear('admin', superusuario='on')
        self.assertTrue(u.is_superuser)
        self.assertFalse(u.is_staff)
        # Manda en el portal (panel de usuarios) pero /admin/ no lo deja entrar
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse('panel_usuarios')).status_code, 200)
        r = self.client.get('/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])
        self.assertNotContains(self.client.get('/'), 'Configuración Avanzada')

    def test_crear_con_admin_de_django(self):
        u = self.crear('admin', superusuario='on', admin_django='on')
        self.assertTrue(u.is_superuser and u.is_staff)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertContains(self.client.get('/'), 'Configuración Avanzada')


class EditarTests(PanelBase):
    def editar(self, u, **cambios):
        from users.forms_panel import UsuarioPanelForm
        d = {k: v for k, v in UsuarioPanelForm.iniciales(u).items() if v not in (None, '', [], False)}
        d.update(cambios)
        return self.client.post(reverse('panel_usuario', args=[u.pk]), d)

    def test_clave_en_blanco_conserva_la_actual(self):
        u = geolab('lab1', 'lab')
        r = self.editar(u, nombre='Luis')
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(u.first_name, 'Luis')
        self.assertTrue(u.check_password(CLAVE))

    def test_cambiar_de_area_de_geolab(self):
        u = geolab('tec1', 'tecnico')
        self.editar(u, rol='facturacion', ciudades=['Bucaramanga'], secciones=['panel'])
        u.refresh_from_db()
        self.assertTrue(u.es_usuario_facturacion)
        self.assertEqual(AccesoFacturacion.objects.get(usuario=u).ciudades, ['Bucaramanga'])

    def test_no_se_cambia_de_geolab_a_cliente(self):
        u = geolab('tec2', 'tecnico')
        r = self.editar(u, rol='director', empresa=self.marval.pk, email='t@correo.com')
        self.assertEqual(r.status_code, 200)
        self.assertIn('rol', r.context['form'].errors)
        u.refresh_from_db()
        self.assertTrue(u.es_geolab)
        self.assertFalse(ClienteExterno.objects.filter(user=u).exists())

    def test_cuenta_de_geolab_sin_area_se_repara(self):
        """es_geolab sin perfil = admin total por el fallback; el panel lo muestra y lo arregla."""
        u = UsuarioBase.objects.create_user('huerfano', password=CLAVE, es_geolab=True)
        self.assertTrue(u.es_admin_geolab)  # el peligro
        r = self.client.get(reverse('panel_usuarios') + '?problemas=1')
        self.assertContains(r, 'huerfano')
        self.assertContains(r, 'administrador total')
        self.editar(u, rol='tecnico')
        u = UsuarioBase.objects.get(pk=u.pk)
        self.assertEqual(u.perfil_geolab.area, 'tecnico')
        self.assertFalse(u.es_admin_geolab)

    def test_superusuario_de_createsuperuser_se_guarda_sin_pelear_con_el_rol(self):
        """createsuperuser no marca es_geolab ni crea perfil: el panel le propone Administrativo."""
        u = UsuarioBase.objects.create_superuser('jefe2', password=CLAVE)
        r = self.client.get(reverse('panel_usuario', args=[u.pk]))
        self.assertContains(r, 'no tiene rol')
        self.assertContains(r, 'value="admin" data-familia="geolab" checked')
        # Le quita el admin de Django y guarda sin tocar nada más
        r = self.editar(u, admin_django='')
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertTrue(u.is_superuser)
        self.assertFalse(u.is_staff)
        self.assertTrue(u.es_geolab)
        self.assertEqual(u.perfil_geolab.area, 'admin')
        # Y ya ve el portal de Geolab en vez de la página de espera
        self.client.force_login(u)
        self.assertTemplateUsed(self.client.get('/'), 'core/home_staff.html')

    def test_residente_cambia_de_obras_y_director_de_empresa(self):
        u = self.crear('residente', empresa=self.marval.pk, obras=[self.obra1.pk, self.obra2.pk])
        self.editar(u, obras=[self.obra2.pk])
        self.assertEqual(list(u.perfil_cliente.obras_asignadas.all()), [self.obra2])
        # Pasa a director de otra empresa: no conserva obras de la anterior
        self.editar(u, rol='director', empresa=self.otra.pk, obras=[])
        perfil = ClienteExterno.objects.get(user=u)
        self.assertEqual((perfil.rol, perfil.empresa), ('director', self.otra))
        self.assertFalse(perfil.obras_asignadas.exists())

    def test_tecnico_pierde_un_area(self):
        u = self.crear('tecnico', **{f'calidad_{self.area1.pk}': 'lectura'})
        self.editar(u, **{f'calidad_{self.area1.pk}': ''})
        self.assertFalse(AccesoAreaUsuario.objects.filter(usuario=u).exists())

    def test_no_se_quita_su_propio_superusuario(self):
        r = self.editar(self.super, superusuario='')
        self.assertEqual(r.status_code, 200)
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_superuser)

    def test_quitar_superusuario_a_otro(self):
        u = geolab('otro_jefe', 'admin', is_superuser=True, is_staff=True)
        r = self.editar(u, superusuario='')
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.is_staff)  # son independientes: el admin de Django se quita aparte
        self.editar(u, admin_django='')
        u.refresh_from_db()
        self.assertFalse(u.is_staff)

    def test_no_se_quita_su_propio_admin_de_django(self):
        r = self.editar(self.super, admin_django='')
        self.assertEqual(r.status_code, 200)
        self.assertIn('admin_django', r.context['form'].errors)
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_staff)

    def test_cambiar_su_propia_clave_no_cierra_su_sesion(self):
        r = self.editar(self.super, password1='Nueva.Clave.2026', password2='Nueva.Clave.2026')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse('panel_usuarios')).status_code, 200)


class EstadoTests(PanelBase):
    def test_desactivar_y_activar(self):
        u = geolab('rec', 'recepcion')
        self.client.post(reverse('panel_usuario_estado', args=[u.pk]))
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.client.post(reverse('panel_usuario_estado', args=[u.pk]))
        u.refresh_from_db()
        self.assertTrue(u.is_active)

    def test_no_se_desactiva_a_si_mismo(self):
        self.client.post(reverse('panel_usuario_estado', args=[self.super.pk]))
        self.super.refresh_from_db()
        self.assertTrue(self.super.is_active)

    def test_solo_post(self):
        u = geolab('rec2', 'recepcion')
        self.assertEqual(self.client.get(reverse('panel_usuario_estado', args=[u.pk])).status_code, 405)


class ListaTests(PanelBase):
    def test_filtros_por_rol_y_busqueda(self):
        geolab('tecnico_uno', 'tecnico')
        self.crear('director', username='dir_marval', empresa=self.marval.pk)
        self.client.get(reverse('panel_usuarios'))  # consume el aviso de "creado"
        r = self.client.get(reverse('panel_usuarios') + '?rol=tecnico')
        self.assertContains(r, 'tecnico_uno')
        self.assertNotContains(r, 'dir_marval')
        r = self.client.get(reverse('panel_usuarios') + '?q=marval')
        self.assertContains(r, 'dir_marval')
        self.assertNotContains(r, 'tecnico_uno')

    def test_avisa_cuentas_incompletas(self):
        self.crear('residente', username='sin_obras', empresa=self.marval.pk)
        r = self.client.get(reverse('panel_usuarios') + '?problemas=1')
        self.assertContains(r, 'sin_obras')
        self.assertContains(r, 'Sin obras asignadas')
        self.assertNotContains(r, '>jefe<')

    def test_obras_de_la_empresa(self):
        r = self.client.get(reverse('panel_obras_empresa', args=[self.marval.pk]))
        self.assertEqual({o['codigo_obra'] for o in r.json()['obras']}, {'BUC46-1', 'BUC46-2'})
