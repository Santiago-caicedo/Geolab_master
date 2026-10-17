from django.contrib import admin
from .models import Obra, Informe, InformeEliminado

@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'constructora', 'fecha_creacion']
    search_fields = ['nombre', 'constructora__username']

@admin.register(Informe)
class InformeAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'obra', 'fecha_creacion']
    search_fields = ['titulo']


@admin.register(InformeEliminado)
class InformeEliminadoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'obra_codigo', 'eliminado_por', 'fecha_eliminacion']
    search_fields = ['titulo', 'obra_codigo', 'obra_nombre']
    list_filter = ['fecha_eliminacion']
    readonly_fields = [f.name for f in InformeEliminado._meta.fields]

    def has_add_permission(self, request):
        return False
