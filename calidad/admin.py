from django.contrib import admin
from .models import AreaCalidad, Carpeta, Documento, AccesoAreaUsuario


@admin.register(AreaCalidad)
class AreaCalidadAdmin(admin.ModelAdmin):
    list_display = ['numero', 'nombre', 'icono']
    ordering = ['numero']


class SubcarpetaInline(admin.TabularInline):
    model = Carpeta
    fk_name = 'padre'
    extra = 0
    fields = ['nombre', 'orden']


class DocumentoInline(admin.TabularInline):
    model = Documento
    extra = 0
    fields = ['nombre', 'archivo', 'tipo_archivo', 'tamano_bytes', 'subido_por']
    readonly_fields = ['tipo_archivo', 'tamano_bytes']


@admin.register(Carpeta)
class CarpetaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'area', 'padre', 'orden', 'fecha_creacion']
    list_filter = ['area']
    search_fields = ['nombre']
    inlines = [SubcarpetaInline, DocumentoInline]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'carpeta', 'tipo_archivo', 'tamano_legible', 'subido_por', 'fecha_subida']
    list_filter = ['tipo_archivo', 'carpeta__area']
    search_fields = ['nombre']
    readonly_fields = ['tipo_archivo', 'tamano_bytes', 'fecha_subida']

    def tamano_legible(self, obj):
        return obj.tamano_legible
    tamano_legible.short_description = 'Tamaño'


@admin.register(AccesoAreaUsuario)
class AccesoAreaUsuarioAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'area', 'puede_editar', 'asignado_por', 'fecha_asignacion']
    list_filter = ['area', 'puede_editar']
    search_fields = ['usuario__username', 'usuario__first_name', 'usuario__last_name']
