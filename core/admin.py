from django.contrib import admin
from .models import Obra, Informe

@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'constructora', 'fecha_creacion']
    search_fields = ['nombre', 'constructora__username']

@admin.register(Informe)
class InformeAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'obra', 'fecha_creacion']
    search_fields = ['titulo']