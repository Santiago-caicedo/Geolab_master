from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Obra
from solicitudes.models import Notificacion, RemisionMuestras
from users.models import Constructora, UsuarioBase


class NotificacionesTests(TestCase):
    """Campana: clic en una notificación la marca leída; marcar todas; comando."""

    def setUp(self):
        self.staff = UsuarioBase.objects.create_user('staff', password='x', es_geolab=True)
        self.otro = UsuarioBase.objects.create_user('otro', password='x', es_cliente=True)
        c = Constructora.objects.create(codigo='BUC1', nombre='UNO', ciudad='Bucaramanga')
        obra = Obra.objects.create(nombre='A', codigo_obra='BUC1-1', constructora=c)
        self.rem = RemisionMuestras.objects.create(obra=obra, estado='completada')
        self.n_staff = Notificacion.objects.create(tipo='nueva_remision', titulo='Nueva', mensaje='m',
                                                   remision=self.rem, solo_staff=True)
        self.n_otro = Notificacion.objects.create(tipo='sistema', titulo='Tuya', mensaje='m',
                                                  destinatario=self.otro, solo_staff=False)
        self.client.force_login(self.staff)

    def test_abrir_marca_leida_y_lleva_a_la_remision(self):
        r = self.client.get(reverse('abrir_notificacion', args=[self.n_staff.pk]))
        self.assertRedirects(r, reverse('detalle_remision', args=[self.rem.pk]), fetch_redirect_response=False)
        self.n_staff.refresh_from_db()
        self.assertTrue(self.n_staff.leida)
        self.assertIsNotNone(self.n_staff.fecha_lectura)

    def test_no_abre_la_notificacion_de_otro_usuario(self):
        r = self.client.get(reverse('abrir_notificacion', args=[self.n_otro.pk]))
        self.assertEqual(r.status_code, 404)
        self.n_otro.refresh_from_db()
        self.assertFalse(self.n_otro.leida)

    def test_marcar_todas_vuelve_a_la_pagina_de_origen(self):
        r = self.client.post(reverse('marcar_todas_leidas'), {'next': '/empresas/'})
        self.assertRedirects(r, '/empresas/', fetch_redirect_response=False)
        self.n_staff.refresh_from_db()
        self.assertTrue(self.n_staff.leida)
        self.n_otro.refresh_from_db()
        self.assertFalse(self.n_otro.leida)   # la de otro usuario no se toca
        # un next externo se ignora
        r = self.client.post(reverse('marcar_todas_leidas'), {'next': 'https://malo.com/'})
        self.assertRedirects(r, reverse('lista_notificaciones'), fetch_redirect_response=False)

    def test_comando_marca_todas_o_por_usuario(self):
        out = StringIO()
        call_command('marcar_notificaciones_leidas', '--dry-run', stdout=out)
        self.assertIn('[DRY-RUN] 2', out.getvalue())
        self.assertEqual(Notificacion.objects.filter(leida=False).count(), 2)
        call_command('marcar_notificaciones_leidas', '--usuario', 'otro', stdout=out)
        self.assertEqual(list(Notificacion.objects.filter(leida=False)), [self.n_staff])
        call_command('marcar_notificaciones_leidas', stdout=out)
        self.assertFalse(Notificacion.objects.filter(leida=False).exists())
