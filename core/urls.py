from django.urls import path
from . import views

urlpatterns = [
    # La raíz apunta al enrutador
    path('', views.dashboard_router, name='home'),

    # URLs para clientes
    path('informes/', views.dashboard_client, name='lista_informes'),
    path('mis-obras/<int:pk>/informes/', views.informes_obra_cliente, name='informes_obra_cliente'),

    # URLs DE GESTIÓN (Staff Geolab)
    path('empresas/', views.lista_constructoras, name='lista_constructoras'),
    path('empresas/<int:pk>/', views.detalle_constructora, name='detalle_constructora'),
    path('empresas/<int:pk>/editar/', views.editar_constructora, name='editar_constructora'),


    path('obras/<int:pk>/', views.detalle_obra, name='detalle_obra'),
    path('obras/<int:pk>/editar/', views.editar_obra, name='editar_obra'),
    path('obras/<int:pk>/informes/', views.lista_informes_obra, name='lista_informes_obra'),

    # Cargar informes
    path('cargar-informe/', views.cargar_informe, name='cargar_informe'),
    path('obras/<int:pk>/cargar-informe/', views.cargar_informe_obra, name='cargar_informe_obra'),
]