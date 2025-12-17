from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import UsuarioBase, Constructora, FuncionarioGeolab, ClienteExterno

# Configuración para ver los perfiles dentro del mismo usuario
class FuncionarioInline(admin.StackedInline):
    model = FuncionarioGeolab
    can_delete = False
    verbose_name_plural = 'Perfil Geolab (Si aplica)'

class ClienteInline(admin.StackedInline):
    model = ClienteExterno
    can_delete = False
    verbose_name_plural = 'Perfil Cliente (Si aplica)'

@admin.register(UsuarioBase)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'es_geolab', 'es_cliente', 'is_staff')
    
    # --- AQUÍ ESTÁ LA SOLUCIÓN ---
    # Le decimos a Django: "Usa los campos normales Y agrega los nuestros al final"
    fieldsets = UserAdmin.fieldsets + (
        ('Roles de Sistema (Geolab)', {'fields': ('es_geolab', 'es_cliente')}),
    )
    # -----------------------------
    
    inlines = [FuncionarioInline, ClienteInline]

@admin.register(Constructora)
class ConstructoraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo', 'id_wp_original')
    search_fields = ('nombre', 'codigo')

@admin.register(ClienteExterno)
class ClienteExternoAdmin(admin.ModelAdmin):
    list_display = ('user', 'empresa', 'rol', 'cargo')
    list_filter = ('empresa', 'rol')
    search_fields = ('user__username', 'empresa__nombre')