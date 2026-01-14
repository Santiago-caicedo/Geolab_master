from django.urls import path
from . import views

urlpatterns = [
    # Staff Geolab (requiere login)
    path('remisiones/', views.lista_remisiones, name='lista_remisiones'),
    path('obras/<int:obra_pk>/nueva-remision/', views.crear_remision, name='crear_remision'),
    path('obras/<int:obra_pk>/remisiones/', views.lista_remisiones_obra, name='lista_remisiones_obra'),
    path('remisiones/<int:pk>/', views.detalle_remision, name='detalle_remision'),

    # Cliente (acceso público con token)
    path('remision/<str:token>/', views.responder_remision, name='responder_remision'),
    path('remision/<str:token>/confirmacion/', views.confirmacion_remision, name='confirmacion_remision'),
]
