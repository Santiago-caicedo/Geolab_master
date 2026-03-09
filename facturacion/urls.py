from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('facturacion/', views.dashboard_facturacion, name='dashboard_facturacion'),
    path('facturacion/api/facturacion-mensual/', views.api_facturacion_mensual, name='api_facturacion_mensual'),

    # Catálogo de servicios
    path('facturacion/catalogo/', views.catalogo_servicios, name='catalogo_servicios'),
    path('facturacion/categorias/nueva/', views.crear_categoria, name='crear_categoria_facturacion'),
    path('facturacion/categorias/<int:pk>/editar/', views.editar_categoria, name='editar_categoria_facturacion'),
    path('facturacion/servicios/nuevo/', views.crear_servicio, name='crear_servicio_facturacion'),
    path('facturacion/servicios/<int:pk>/editar/', views.editar_servicio, name='editar_servicio_facturacion'),
    path('facturacion/servicios/<int:pk>/eliminar/', views.eliminar_servicio, name='eliminar_servicio_facturacion'),

    # Precios por obra
    path('facturacion/obras/<int:obra_pk>/precios/', views.gestionar_precios_obra, name='gestionar_precios_obra'),

    # Impuestos
    path('facturacion/impuestos/', views.lista_impuestos, name='lista_impuestos'),
    path('facturacion/impuestos/nuevo/', views.crear_impuesto, name='crear_impuesto'),
    path('facturacion/impuestos/<int:pk>/editar/', views.editar_impuesto, name='editar_impuesto'),

    # Registro de servicios
    path('facturacion/registro/crear/', views.crear_registro, name='crear_registro_facturacion'),
    path('facturacion/registro/<int:pk>/editar/', views.editar_registro, name='editar_registro_facturacion'),
    path('facturacion/registro/<int:pk>/eliminar/', views.eliminar_registro, name='eliminar_registro_facturacion'),

    # Histórico
    path('facturacion/historico/', views.historico_facturacion, name='historico_facturacion'),

    # Generación de facturas
    path('facturacion/generar/', views.generar_factura, name='generar_factura'),
    path('facturacion/finalizar/', views.finalizar_factura, name='finalizar_factura'),

    # Repositorio de facturas (drill-down)
    path('facturacion/repositorio/', views.repositorio_clientes, name='repositorio_clientes'),
    path('facturacion/repositorio/cliente/<int:constructora_pk>/', views.repositorio_obras_cliente, name='repositorio_obras_cliente'),
    path('facturacion/repositorio/obra/<int:obra_pk>/', views.repositorio_facturas_obra, name='repositorio_facturas_obra'),

    # Acciones sobre facturas
    path('facturacion/factura/<int:pk>/anular/', views.anular_factura, name='anular_factura'),
    path('facturacion/factura/<int:pk>/pagada/', views.marcar_factura_pagada, name='marcar_factura_pagada'),
    path('facturacion/factura/<int:pk>/pdf/', views.descargar_factura_pdf, name='descargar_factura_pdf'),

    # APIs
    path('facturacion/api/obras/', views.api_get_obras, name='api_get_obras_facturacion'),
    path('facturacion/api/precio/', views.api_get_precio, name='api_get_precio'),
    path('facturacion/api/buscar-servicios/', views.api_buscar_servicios, name='api_buscar_servicios'),
]
