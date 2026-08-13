"""
Tests del rol Coordinador de Calidad.

Cubren las dos mitades del rol:
  1. Manda dentro del SGC (ve las 8 areas, sube, elimina, gestiona accesos).
  2. No puede salir de /calidad/ (RestriccionCalidadMiddleware).
"""

from django.test import TestCase

from calidad.models import (
    AreaCalidad, Carpeta, Documento, AccesoAreaUsuario, AccesoCarpetaUsuario,
)
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


class UsuariosCalidadTest(TestCase):
    """
    Rol Usuario de Calidad: creado por el coordinador, confinado al SGC y
    limitado a las carpetas asignadas con permisos ver/cargar/eliminar.
    """

    @classmethod
    def setUpTestData(cls):
        cls.area = AreaCalidad.objects.create(numero=1, nombre='Gestion Directiva')
        cls.area2 = AreaCalidad.objects.create(numero=2, nombre='Gestion Comercial')
        # Arbol: raiz_a > sub_b > subsub_c ; raiz_d (sin acceso)
        cls.raiz_a = Carpeta.objects.create(nombre='Raiz A', area=cls.area)
        cls.sub_b = Carpeta.objects.create(nombre='Sub B', area=cls.area, padre=cls.raiz_a)
        cls.subsub_c = Carpeta.objects.create(nombre='Subsub C', area=cls.area, padre=cls.sub_b)
        cls.raiz_d = Carpeta.objects.create(nombre='Raiz D', area=cls.area)
        cls.coordinador = crear_geolab('coord', 'calidad')

    def crear_usuario_via_vista(self):
        self.client.force_login(self.coordinador)
        self.client.post('/calidad/usuarios/nuevo/', {
            'username': 'ucalidad', 'nombre': 'Uriel', 'apellido': 'Calidad',
            'email': 'u@geolab.com',
            'password1': 'Clave.Calidad.2026', 'password2': 'Clave.Calidad.2026',
        })
        return UsuarioBase.objects.get(username='ucalidad')

    def asignar(self, usuario, carpeta, ver=True, cargar=False, eliminar=False):
        return AccesoCarpetaUsuario.objects.create(
            usuario=usuario, carpeta=carpeta, puede_ver=ver,
            puede_cargar=cargar, puede_eliminar=eliminar,
        )

    # ── creacion por el coordinador ───────────────────────────────────────

    def test_coordinador_crea_usuario_con_rol_correcto(self):
        u = self.crear_usuario_via_vista()
        self.assertTrue(u.es_usuario_calidad)
        self.assertTrue(u.es_confinado_a_calidad)
        self.assertFalse(u.es_admin_sgc)
        self.assertFalse(u.es_admin_geolab)
        self.assertFalse(u.is_staff)
        self.assertTrue(u.check_password('Clave.Calidad.2026'))

    def test_un_no_admin_no_puede_crear_usuarios(self):
        tecnico = crear_geolab('tec', 'tecnico')
        self.client.force_login(tecnico)
        resp = self.client.post('/calidad/usuarios/nuevo/', {
            'username': 'x', 'nombre': 'X', 'apellido': 'X',
            'password1': 'Clave.Calidad.2026', 'password2': 'Clave.Calidad.2026',
        })
        self.assertEqual(resp.url, '/calidad/')
        self.assertFalse(UsuarioBase.objects.filter(username='x').exists())

    def test_matriz_no_puede_tocar_al_staff(self):
        tecnico = crear_geolab('tec', 'tecnico')
        self.client.force_login(self.coordinador)
        resp = self.client.get(f'/calidad/usuarios/{tecnico.pk}/permisos/')
        self.assertEqual(resp.status_code, 404)

    def test_matriz_guarda_grants_y_cargar_implica_ver(self):
        u = self.crear_usuario_via_vista()
        self.client.post(f'/calidad/usuarios/{u.pk}/permisos/', {
            f'ver_{self.raiz_a.pk}': 'on',
            f'cargar_{self.sub_b.pk}': 'on',  # sin marcar ver: debe implicarlo
        })
        grants = {g.carpeta_id: g for g in AccesoCarpetaUsuario.objects.filter(usuario=u)}
        self.assertEqual(set(grants), {self.raiz_a.pk, self.sub_b.pk})
        self.assertTrue(grants[self.sub_b.pk].puede_ver)
        self.assertTrue(grants[self.sub_b.pk].puede_cargar)
        self.assertFalse(grants[self.raiz_a.pk].puede_cargar)

    # ── visibilidad y bloqueo ─────────────────────────────────────────────

    def test_sin_carpetas_no_ve_ningun_area(self):
        u = self.crear_usuario_via_vista()
        self.client.force_login(u)
        resp = self.client.get('/calidad/')
        self.assertEqual(len(resp.context['areas_info']), 0)

    def test_ve_su_carpeta_y_ancestro_de_paso_pero_no_hermanas(self):
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b)  # solo Sub B
        self.client.force_login(u)

        # Area visible (1 carpeta asignada)
        resp = self.client.get('/calidad/')
        self.assertEqual(len(resp.context['areas_info']), 1)

        # Raiz del area: ve Raiz A (de paso), NO Raiz D
        resp = self.client.get(f'/calidad/area/{self.area.pk}/')
        nombres = [c.nombre for c in resp.context['carpetas']]
        self.assertEqual(nombres, ['Raiz A'])

        # Raiz A es de paso: navegable pero sin acciones
        resp = self.client.get(f'/calidad/carpeta/{self.raiz_a.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['es_de_paso'])
        self.assertFalse(resp.context['puede_cargar'])

        # Sub B: acceso pleno de lectura
        resp = self.client.get(f'/calidad/carpeta/{self.sub_b.pk}/')
        self.assertFalse(resp.context['es_de_paso'])

        # Subsub C (hija no asignada) y Raiz D: bloqueadas
        for carpeta in (self.subsub_c, self.raiz_d):
            resp = self.client.get(f'/calidad/carpeta/{carpeta.pk}/')
            self.assertEqual(resp.url, '/calidad/')

    def test_carpeta_de_paso_oculta_documentos(self):
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b)
        Documento.objects.create(nombre='secreto.pdf', carpeta=self.raiz_a)
        self.client.force_login(u)
        resp = self.client.get(f'/calidad/carpeta/{self.raiz_a.pk}/')
        self.assertEqual(len(resp.context['documentos']), 0)
        # Y su descarga tambien esta bloqueada
        doc = Documento.objects.get(nombre='secreto.pdf')
        resp = self.client.get(f'/calidad/documento/{doc.pk}/descargar/')
        self.assertEqual(resp.url, '/calidad/')

    # ── niveles de permiso ────────────────────────────────────────────────

    def test_solo_ver_no_puede_subir_ni_eliminar(self):
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b)  # ver solamente
        doc = Documento.objects.create(nombre='doc.pdf', carpeta=self.sub_b)
        self.client.force_login(u)

        resp = self.client.post(f'/calidad/carpeta/{self.sub_b.pk}/subir/', {})
        self.assertEqual(resp.url, f'/calidad/carpeta/{self.sub_b.pk}/')
        resp = self.client.post(f'/calidad/documento/{doc.pk}/eliminar/')
        self.assertTrue(Documento.objects.filter(pk=doc.pk).exists())

    def test_con_cargar_sube_archivos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import tempfile
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b, cargar=True)
        self.client.force_login(u)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            resp = self.client.post(f'/calidad/carpeta/{self.sub_b.pk}/subir/', {
                'archivos': SimpleUploadedFile('acta.pdf', b'%PDF-1.4 test'),
            })
        self.assertEqual(resp.url, f'/calidad/carpeta/{self.sub_b.pk}/')
        self.assertTrue(Documento.objects.filter(nombre='acta.pdf', carpeta=self.sub_b).exists())

    def test_con_cargar_crea_subcarpeta_y_hereda_su_permiso(self):
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b, cargar=True)
        self.client.force_login(u)
        self.client.post(f'/calidad/carpeta/{self.sub_b.pk}/nueva-carpeta/', {'nombre': 'Mi Carpeta'})
        nueva = Carpeta.objects.get(nombre='Mi Carpeta')
        grant = AccesoCarpetaUsuario.objects.get(usuario=u, carpeta=nueva)
        self.assertTrue(grant.puede_ver)
        self.assertTrue(grant.puede_cargar)
        self.assertFalse(grant.puede_eliminar)

    def test_con_eliminar_borra_documentos(self):
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b, eliminar=True)
        doc = Documento.objects.create(nombre='viejo.pdf', carpeta=self.sub_b)
        self.client.force_login(u)
        self.client.post(f'/calidad/documento/{doc.pk}/eliminar/')
        self.assertFalse(Documento.objects.filter(pk=doc.pk).exists())

    # ── confinamiento y matrices ──────────────────────────────────────────

    def test_confinado_fuera_de_calidad(self):
        u = self.crear_usuario_via_vista()
        self.client.force_login(u)
        for ruta in ['/empresas/', '/remisiones/', '/usuarios/', '/facturacion/', '/admin/']:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).url, '/calidad/')
        # Y tampoco entra a la gestion de usuarios del SGC
        self.assertEqual(self.client.get('/calidad/usuarios/').url, '/calidad/')

    def test_matriz_de_areas_del_staff_no_lista_usuarios_de_calidad(self):
        u = self.crear_usuario_via_vista()
        tecnico = crear_geolab('tec', 'tecnico')
        self.client.force_login(self.coordinador)
        resp = self.client.get('/calidad/accesos/')
        listados = [f['usuario'].pk for f in resp.context['matriz']]
        self.assertIn(tecnico.pk, listados)
        self.assertNotIn(u.pk, listados)

    def test_toggle_desactiva_el_acceso(self):
        u = self.crear_usuario_via_vista()
        self.client.post(f'/calidad/usuarios/{u.pk}/toggle/')
        u.refresh_from_db()
        self.assertFalse(u.is_active)

    def test_subida_multiple_de_archivos(self):
        """Regresion: el FileField estandar rechazaba la lista del widget multiple."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        import tempfile
        u = self.crear_usuario_via_vista()
        self.asignar(u, self.sub_b, cargar=True)
        self.client.force_login(u)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            self.client.post(f'/calidad/carpeta/{self.sub_b.pk}/subir/', {
                'archivos': [
                    SimpleUploadedFile('uno.pdf', b'%PDF a'),
                    SimpleUploadedFile('dos.pdf', b'%PDF b'),
                ],
            })
        self.assertEqual(self.sub_b.documentos.count(), 2)
