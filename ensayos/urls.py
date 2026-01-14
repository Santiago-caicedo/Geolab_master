from django.urls import path
from . import views

urlpatterns = [
    # ══════════════════════════════════════════════════════════════════════════
    # HOJAS DE TRABAJO POR OBRA (Arquitectura principal)
    # ══════════════════════════════════════════════════════════════════════════

    # Lista de OBRAS con sus hojas de trabajo
    path('hojas-trabajo/', views.lista_obras_hojas_trabajo, name='lista_obras_hojas_trabajo'),

    # Hoja de trabajo de UNA OBRA (todas las muestras de esa obra)
    path('hojas-trabajo/obra/<int:obra_pk>/', views.hoja_trabajo_obra, name='hoja_trabajo_obra'),

    # Dashboard: muestras para hoy (vista rapida)
    path('hojas-trabajo/hoy/', views.muestras_para_hoy, name='muestras_para_hoy'),

    # Dashboard para tecnicos de laboratorio (home del tecnico)
    path('dashboard-tecnico/', views.dashboard_tecnico, name='dashboard_tecnico'),

    # ══════════════════════════════════════════════════════════════════════════
    # ACCIONES Y EDICION
    # ══════════════════════════════════════════════════════════════════════════

    # Toggle seleccion individual (para checkboxes)
    path('resultado/<int:pk>/toggle-seleccion/', views.toggle_seleccion, name='toggle_seleccion'),

    # Acciones de seleccion masiva
    path('hojas-trabajo/seleccionar-hoy/', views.seleccionar_muestras_hoy, name='seleccionar_muestras_hoy'),
    path('hojas-trabajo/deseleccionar-todas/', views.deseleccionar_todas, name='deseleccionar_todas'),

    # ══════════════════════════════════════════════════════════════════════════
    # EDICION POR REMISION (para editar mediciones detalladas)
    # ══════════════════════════════════════════════════════════════════════════

    # Detalle de hoja de trabajo por remision (vista de edicion de mediciones)
    path('hojas-trabajo/remision/<int:pk>/', views.detalle_hoja_trabajo, name='detalle_hoja_trabajo'),

    # Editar resultado individual (para HTMX)
    path('resultado/<int:pk>/editar/', views.editar_resultado, name='editar_resultado'),

    # Marcar resultado como completado (HTMX)
    path('resultado/<int:pk>/completar/', views.completar_resultado, name='completar_resultado'),

    # ══════════════════════════════════════════════════════════════════════════
    # VISTAS LEGACY (mantener compatibilidad)
    # ══════════════════════════════════════════════════════════════════════════

    # Lista de hojas por remision (vista antigua)
    path('hojas-trabajo/por-remision/', views.lista_hojas_trabajo, name='lista_hojas_trabajo'),

    # Generar PDF (futuro)
    # path('hojas-trabajo/<int:pk>/pdf/', views.generar_pdf, name='generar_pdf_hoja'),
]
