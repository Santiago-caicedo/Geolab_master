from django.contrib import admin
from .models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio, Factura,
)


@admin.register(CategoriaServicio)
class CategoriaServicioAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre')
    search_fields = ('codigo', 'nombre')


@admin.register(TipoServicio)
class TipoServicioAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'categoria', 'norma')
    list_filter = ('categoria',)
    search_fields = ('codigo', 'nombre', 'norma')


@admin.register(PrecioServicio)
class PrecioServicioAdmin(admin.ModelAdmin):
    list_display = ('obra', 'tipo_servicio', 'precio')
    list_filter = ('obra__constructora',)
    search_fields = ('obra__nombre', 'tipo_servicio__nombre')


@admin.register(Impuesto)
class ImpuestoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'porcentaje', 'activo')


@admin.register(RegistroServicio)
class RegistroServicioAdmin(admin.ModelAdmin):
    list_display = (
        'obra', 'tipo_servicio', 'fecha_realizacion',
        'cantidad', 'precio_unitario_congelado', 'subtotal', 'factura'
    )
    list_filter = ('fecha_realizacion', 'obra__constructora')
    search_fields = ('numero_informe', 'obra__nombre', 'tipo_servicio__nombre')
    raw_id_fields = ('obra', 'tipo_servicio', 'factura')


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = (
        'pk', 'constructora', 'obra', 'fecha_emision',
        'subtotal', 'monto_iva', 'total', 'estado'
    )
    list_filter = ('estado', 'fecha_emision')
    search_fields = ('constructora__nombre', 'obra__nombre')
    raw_id_fields = ('constructora', 'obra')
