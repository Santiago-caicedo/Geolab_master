from django.contrib import admin
from .models import HojaTrabajo, ResultadoMuestra, ConsecutivoInforme, InformeEnsayo


@admin.register(ConsecutivoInforme)
class ConsecutivoInformeAdmin(admin.ModelAdmin):
    list_display = ['anio', 'ultimo']
    list_editable = ['ultimo']


@admin.register(InformeEnsayo)
class InformeEnsayoAdmin(admin.ModelAdmin):
    list_display = ['numero_informe', 'obra', 'tipo', 'fecha_falla', 'fecha_emision', 'ciudad']
    list_filter = ['tipo', 'ciudad', 'fecha_emision']
    search_fields = ['numero_informe', 'obra__nombre', 'obra__codigo_obra']
    readonly_fields = ['fecha_emision']


class ResultadoMuestraInline(admin.TabularInline):
    """Inline para ver/editar resultados dentro de la hoja de trabajo"""
    model = ResultadoMuestra
    extra = 0
    readonly_fields = [
        'muestra',
        'diametro_real_display',
        'longitud_real_display',
        'area_display',
        'esfuerzo_display',
        'porcentaje_display',
        'fecha_falla_display',
    ]
    fields = [
        'muestra',
        'estado',
        'fecha_falla_display',
        'diametro_d1', 'diametro_d2', 'diametro_d3',
        'diametro_real_display',
        'longitud_l1', 'longitud_l2', 'longitud_l3',
        'longitud_real_display',
        'peso_gramos',
        'carga_maxima_kn',
        'area_display',
        'esfuerzo_display',
        'porcentaje_display',
        'forma_falla',
        'fecha_ensayo',
    ]

    def diametro_real_display(self, obj):
        return f"{obj.diametro_real} mm" if obj.diametro_real else "-"
    diametro_real_display.short_description = "Ø Real"

    def longitud_real_display(self, obj):
        return f"{obj.longitud_real} mm" if obj.longitud_real else "-"
    longitud_real_display.short_description = "Long. Real"

    def area_display(self, obj):
        return f"{obj.area_mm2} mm²" if obj.area_mm2 else "-"
    area_display.short_description = "Área"

    def esfuerzo_display(self, obj):
        return f"{obj.esfuerzo_mpa} MPa" if obj.esfuerzo_mpa else "-"
    esfuerzo_display.short_description = "Esfuerzo"

    def porcentaje_display(self, obj):
        if obj.porcentaje_desarrollo is not None:
            icon = "✅" if obj.cumple_resistencia else "⚠️"
            return f"{obj.porcentaje_desarrollo}% {icon}"
        return "-"
    porcentaje_display.short_description = "% Desarrollo"

    def fecha_falla_display(self, obj):
        if obj.fecha_falla_programada:
            if obj.debe_fallarse_hoy:
                return f"🔴 {obj.fecha_falla_programada} (HOY)"
            dias = obj.dias_para_falla
            if dias and dias > 0:
                return f"⏳ {obj.fecha_falla_programada} (en {dias} días)"
            elif dias and dias < 0:
                return f"⚠️ {obj.fecha_falla_programada} (hace {abs(dias)} días)"
        return "-"
    fecha_falla_display.short_description = "Fecha Falla"


@admin.register(HojaTrabajo)
class HojaTrabajoAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'codigo_formato',
        'remision_display',
        'obra_display',
        'estado',
        'progreso_display',
        'fecha_creacion',
    ]
    list_filter = ['estado', 'fecha_creacion', 'remision__obra__constructora']
    search_fields = [
        'remision__orden_trabajo',
        'remision__obra__nombre',
        'remision__obra__constructora__nombre',
        'numero_informe',
    ]
    readonly_fields = [
        'codigo_formato',
        'version_formato',
        'fecha_creacion',
        'fecha_actualizacion',
        'progreso_display',
        'total_muestras_display',
    ]
    inlines = [ResultadoMuestraInline]

    fieldsets = (
        ('Información del Formato', {
            'fields': ('codigo_formato', 'version_formato', 'remision')
        }),
        ('Estado y Progreso', {
            'fields': ('estado', 'progreso_display', 'total_muestras_display')
        }),
        ('Informe', {
            'fields': ('numero_informe', 'realizado_por', 'observaciones')
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )

    def remision_display(self, obj):
        return f"Remisión #{obj.remision.orden_trabajo}"
    remision_display.short_description = "Remisión"

    def obra_display(self, obj):
        return f"{obj.obra.nombre} ({obj.obra.codigo_obra})"
    obra_display.short_description = "Obra"

    def progreso_display(self, obj):
        return f"{obj.muestras_completadas}/{obj.total_muestras} ({obj.progreso}%)"
    progreso_display.short_description = "Progreso"

    def total_muestras_display(self, obj):
        return f"{obj.total_muestras} muestras"
    total_muestras_display.short_description = "Total Muestras"


@admin.register(ResultadoMuestra)
class ResultadoMuestraAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'hoja_trabajo',
        'muestra_display',
        'estado',
        'fecha_falla_display',
        'esfuerzo_display',
        'porcentaje_display',
    ]
    list_filter = ['estado', 'hoja_trabajo__remision__obra', 'forma_falla']
    search_fields = [
        'hoja_trabajo__remision__obra__nombre',
        'muestra__localizacion',
    ]
    readonly_fields = [
        'hoja_trabajo',
        'muestra',
        'fecha_falla_display',
        'diametro_real_display',
        'longitud_real_display',
        'area_display',
        'esfuerzo_display',
        'porcentaje_display',
    ]

    fieldsets = (
        ('Relaciones', {
            'fields': ('hoja_trabajo', 'muestra')
        }),
        ('Estado', {
            'fields': ('estado', 'fecha_falla_display', 'fecha_ensayo')
        }),
        ('Mediciones de Diámetro (mm)', {
            'fields': (
                ('diametro_d1', 'diametro_d2', 'diametro_d3'),
                'diametro_real_display'
            )
        }),
        ('Mediciones de Longitud (mm)', {
            'fields': (
                ('longitud_l1', 'longitud_l2', 'longitud_l3'),
                'longitud_real_display'
            )
        }),
        ('Peso y Carga', {
            'fields': (('peso_gramos', 'carga_maxima_kn'),)
        }),
        ('Resultados Calculados', {
            'fields': ('area_display', 'esfuerzo_display', 'porcentaje_display')
        }),
        ('Falla y Observaciones', {
            'fields': ('forma_falla', 'observaciones')
        }),
    )

    def muestra_display(self, obj):
        return f"#{obj.muestra.numero_muestra} - {obj.muestra.edad_ensayo_dias}d"
    muestra_display.short_description = "Muestra"

    def fecha_falla_display(self, obj):
        if obj.fecha_falla_programada:
            if obj.debe_fallarse_hoy:
                return f"🔴 {obj.fecha_falla_programada} (HOY)"
            dias = obj.dias_para_falla
            if dias and dias > 0:
                return f"⏳ {obj.fecha_falla_programada} (en {dias} días)"
            elif dias and dias < 0:
                return f"⚠️ {obj.fecha_falla_programada} (hace {abs(dias)} días)"
        return "-"
    fecha_falla_display.short_description = "Fecha Falla"

    def diametro_real_display(self, obj):
        return f"{obj.diametro_real} mm" if obj.diametro_real else "-"
    diametro_real_display.short_description = "Diámetro Real"

    def longitud_real_display(self, obj):
        return f"{obj.longitud_real} mm" if obj.longitud_real else "-"
    longitud_real_display.short_description = "Longitud Real"

    def area_display(self, obj):
        return f"{obj.area_mm2} mm²" if obj.area_mm2 else "-"
    area_display.short_description = "Área"

    def esfuerzo_display(self, obj):
        return f"{obj.esfuerzo_mpa} MPa" if obj.esfuerzo_mpa else "-"
    esfuerzo_display.short_description = "Esfuerzo"

    def porcentaje_display(self, obj):
        if obj.porcentaje_desarrollo is not None:
            icon = "✅" if obj.cumple_resistencia else "⚠️"
            return f"{obj.porcentaje_desarrollo}% {icon}"
        return "-"
    porcentaje_display.short_description = "% Desarrollo"
