from django.urls import path
from . import views

urlpatterns = [
    # Staff Geolab (requiere login)
    path('remisiones/', views.lista_remisiones, name='lista_remisiones'),
    path('obras/<int:obra_pk>/nueva-remision/', views.crear_remision, name='crear_remision'),
    path('obras/<int:obra_pk>/remisiones/', views.lista_remisiones_obra, name='lista_remisiones_obra'),
    path('remisiones/<int:pk>/', views.detalle_remision, name='detalle_remision'),
    path('remisiones/<int:pk>/pdf/', views.descargar_pdf_remision, name='descargar_pdf_remision'),

    # ==========================================
    # REMITENTE (usuario logueado con rol remitente)
    # ==========================================
    path('remitente/', views.dashboard_remitente, name='dashboard_remitente'),
    path('remitente/mis-remisiones/', views.mis_remisiones_remitente, name='mis_remisiones_remitente'),
    path('remitente/obras/<int:obra_pk>/nueva-remision/', views.crear_remision_cliente, name='crear_remision_cliente'),
    path('remitente/remisiones/<int:pk>/', views.detalle_remision_remitente, name='detalle_remision_remitente'),

    # ==========================================
    # NOTIFICACIONES
    # ==========================================
    path('notificaciones/', views.lista_notificaciones, name='lista_notificaciones'),
    path('notificaciones/<int:pk>/leida/', views.marcar_notificacion_leida, name='marcar_notificacion_leida'),
    path('notificaciones/marcar-todas/', views.marcar_todas_leidas, name='marcar_todas_leidas'),
    path('notificaciones/contar/', views.contar_notificaciones_no_leidas, name='contar_notificaciones_no_leidas'),
    path('notificaciones/recientes/', views.obtener_notificaciones_recientes, name='obtener_notificaciones_recientes'),

    # ==========================================
    # DEPRECADO: Sistema de tokens (mantener temporalmente)
    # ==========================================
    path('remision/<str:token>/', views.responder_remision, name='responder_remision'),
    path('remision/<str:token>/confirmacion/', views.confirmacion_remision, name='confirmacion_remision'),
]
