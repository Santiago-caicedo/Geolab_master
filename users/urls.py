from django.urls import path
from . import views, views_panel

urlpatterns = [
    # Panel de usuarios (solo superusuarios): todas las cuentas del portal en un lugar
    path('usuarios/panel/', views_panel.panel_usuarios, name='panel_usuarios'),
    path('usuarios/panel/nuevo/', views_panel.panel_usuario_nuevo, name='panel_usuario_nuevo'),
    path('usuarios/panel/<int:pk>/', views_panel.panel_usuario, name='panel_usuario'),
    path('usuarios/panel/<int:pk>/estado/', views_panel.panel_usuario_estado, name='panel_usuario_estado'),
    path('usuarios/panel/<int:pk>/carpetas/', views_panel.panel_usuario_carpetas, name='panel_usuario_carpetas'),
    path('usuarios/panel/api/obras/<int:empresa_pk>/', views_panel.panel_obras_empresa, name='panel_obras_empresa'),

    # Lista de usuarios cliente
    path('usuarios/', views.lista_usuarios_cliente, name='lista_usuarios_cliente'),

    # CRUD de usuarios
    path('usuarios/nuevo/', views.crear_usuario_cliente, name='crear_usuario_cliente'),
    path('usuarios/<int:pk>/', views.detalle_usuario_cliente, name='detalle_usuario_cliente'),
    path('usuarios/<int:pk>/editar/', views.editar_usuario_cliente, name='editar_usuario_cliente'),

    # API para toggle estado (AJAX)
    path('usuarios/<int:pk>/toggle-estado/', views.toggle_estado_usuario, name='toggle_estado_usuario'),

    # API para obtener obras de una empresa (AJAX)
    path('usuarios/api/obras-empresa/<int:empresa_pk>/', views.obtener_obras_empresa, name='obtener_obras_empresa'),
]
