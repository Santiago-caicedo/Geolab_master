from django.urls import path
from . import views

urlpatterns = [
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
