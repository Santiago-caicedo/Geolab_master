from django.urls import path
from . import views

urlpatterns = [
    # La raíz apunta al enrutador
    path('', views.dashboard_router, name='home'),
    # Mantenemos esta ruta específica por si alguien quiere ver solo la lista
    path('informes/', views.dashboard_client, name='lista_informes'), 

    #URLS DE GESTIÓN
    path('empresas/', views.lista_constructoras, name='lista_constructoras'),
    path('empresas/<int:pk>/', views.detalle_constructora, name='detalle_constructora'),
    path('empresas/<int:pk>/editar/', views.editar_constructora, name='editar_constructora'),


    path('obras/<int:pk>/', views.detalle_obra, name='detalle_obra'),
    path('obras/<int:pk>/editar/', views.editar_obra, name='editar_obra'),
]