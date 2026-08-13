from django.urls import path
from . import views

urlpatterns = [
    path('calidad/', views.explorador_calidad, name='explorador_calidad'),
    path('calidad/area/<int:pk>/', views.contenido_area_raiz, name='contenido_area_raiz'),
    path('calidad/carpeta/<int:pk>/', views.contenido_carpeta, name='contenido_carpeta'),
    path('calidad/carpeta/<int:pk>/subir/', views.subir_documento, name='subir_documento_calidad'),
    path('calidad/carpeta/<int:pk>/nueva-carpeta/', views.crear_carpeta, name='crear_carpeta_calidad'),
    path('calidad/area/<int:pk>/nueva-carpeta/', views.crear_carpeta_raiz, name='crear_carpeta_raiz_calidad'),
    path('calidad/documento/<int:pk>/descargar/', views.descargar_documento, name='descargar_documento_calidad'),
    path('calidad/documento/<int:pk>/eliminar/', views.eliminar_documento, name='eliminar_documento_calidad'),
    path('calidad/carpeta/<int:pk>/eliminar/', views.eliminar_carpeta, name='eliminar_carpeta_calidad'),
    path('calidad/accesos/', views.gestionar_accesos, name='gestionar_accesos'),

    # Gestion de Usuarios de Calidad (los crea el coordinador)
    path('calidad/usuarios/', views.usuarios_calidad, name='usuarios_calidad'),
    path('calidad/usuarios/nuevo/', views.crear_usuario_calidad, name='crear_usuario_calidad'),
    path('calidad/usuarios/<int:pk>/permisos/', views.permisos_usuario_calidad, name='permisos_usuario_calidad'),
    path('calidad/usuarios/<int:pk>/toggle/', views.toggle_usuario_calidad, name='toggle_usuario_calidad'),
]
