from django.contrib import admin
from .models import RemisionMuestras, Muestra, Notificacion


class MuestraInline(admin.TabularInline):
    model = Muestra
    extra = 0
    readonly_fields = ['numero_muestra']


@admin.register(RemisionMuestras)
class RemisionMuestrasAdmin(admin.ModelAdmin):
    list_display = [
        'orden_trabajo',
        'obra',
        'estado',
        'total_muestras',
        'fecha_creacion',
        'fecha_respuesta',
    ]
    list_filter = ['estado', 'fecha_creacion', 'obra__constructora']
    search_fields = ['orden_trabajo', 'obra__nombre', 'obra__constructora__nombre']
    readonly_fields = [
        'token_acceso',
        'fecha_creacion',
        'fecha_envio',
        'fecha_respuesta',
        'firma_ip_address',
        'firma_user_agent',
        'firma_fecha',
    ]
    inlines = [MuestraInline]

    fieldsets = (
        ('Información Principal', {
            'fields': ('obra', 'orden_trabajo', 'estado', 'solicitado_por')
        }),
        ('Acceso', {
            'fields': ('token_acceso', 'email_destinatario'),
            'classes': ('collapse',)
        }),
        ('Datos del Proyecto', {
            'fields': ('cc',)
        }),
        ('Cadena de Custodia - Cliente', {
            'fields': (
                'cliente_fecha', 'cliente_cantidad', 'cliente_estado',
                'cliente_firma_nombre', 'cliente_observaciones'
            )
        }),
        ('Cadena de Custodia - Laboratorio', {
            'fields': (
                'lab_fecha', 'lab_cantidad', 'lab_estado',
                'lab_firma_nombre', 'lab_observaciones'
            )
        }),
        ('Control Interno', {
            'fields': ('revisado_por', 'programado', 'fecha_revision', 'firma_revision')
        }),
        ('Manifiesto del Firmante', {
            'fields': (
                'firmante_nombre', 'firmante_cedula', 'firmante_cargo',
                'firmante_email', 'firmante_telefono', 'acepta_veracidad'
            )
        }),
        ('Auditoría', {
            'fields': (
                'fecha_creacion', 'fecha_envio', 'fecha_respuesta',
                'firma_ip_address', 'firma_user_agent', 'firma_fecha'
            ),
            'classes': ('collapse',)
        }),
    )


@admin.register(Muestra)
class MuestraAdmin(admin.ModelAdmin):
    list_display = [
        'numero_muestra',
        'remision',
        'tipo_muestra',
        'localizacion',
        'fecha_toma',
        'edad_ensayo_dias',
    ]
    list_filter = ['tipo_muestra', 'remision__obra']
    search_fields = ['remision__orden_trabajo', 'localizacion']


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = [
        'titulo',
        'tipo',
        'destinatario',
        'solo_staff',
        'leida',
        'fecha_creacion',
    ]
    list_filter = ['tipo', 'solo_staff', 'leida', 'fecha_creacion']
    search_fields = ['titulo', 'mensaje', 'destinatario__username']
    readonly_fields = ['fecha_creacion', 'fecha_lectura']
    raw_id_fields = ['destinatario', 'remision']

    fieldsets = (
        ('Contenido', {
            'fields': ('tipo', 'titulo', 'mensaje')
        }),
        ('Destinatario', {
            'fields': ('destinatario', 'solo_staff', 'remision')
        }),
        ('Estado', {
            'fields': ('leida', 'fecha_creacion', 'fecha_lectura')
        }),
    )
