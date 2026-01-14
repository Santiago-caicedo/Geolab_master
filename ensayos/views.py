from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, F, Value, ExpressionWrapper, DateField
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta

from .models import HojaTrabajo, ResultadoMuestra
from .forms import ResultadoMuestraForm
from core.models import Obra


@login_required
def lista_hojas_trabajo(request):
    """
    Lista todas las hojas de trabajo (F-GT-05).
    Solo accesible por staff de Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    hojas = HojaTrabajo.objects.select_related(
        'remision',
        'remision__obra',
        'remision__obra__constructora',
        'realizado_por'
    ).prefetch_related('resultados')

    # Filtros
    estado = request.GET.get('estado', '')
    busqueda = request.GET.get('q', '')

    if estado:
        hojas = hojas.filter(estado=estado)

    if busqueda:
        hojas = hojas.filter(
            Q(remision__obra__nombre__icontains=busqueda) |
            Q(remision__obra__constructora__nombre__icontains=busqueda) |
            Q(numero_informe__icontains=busqueda)
        )

    # Ordenar por fecha de creación (más recientes primero)
    hojas = hojas.order_by('-fecha_creacion')

    # Paginación
    paginator = Paginator(hojas, 15)
    page = request.GET.get('page', 1)
    hojas_page = paginator.get_page(page)

    context = {
        'hojas': hojas_page,
        'estado_filtro': estado,
        'busqueda': busqueda,
        'estados': HojaTrabajo.ESTADOS,
    }
    return render(request, 'ensayos/lista_hojas_trabajo.html', context)


@login_required
def muestras_para_hoy(request):
    """
    Dashboard del técnico: muestra las muestras que deben fallarse hoy.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    hoy = timezone.now().date()

    # Obtener todos los resultados pendientes
    resultados_pendientes = ResultadoMuestra.objects.filter(
        estado='pendiente'
    ).select_related(
        'hoja_trabajo',
        'hoja_trabajo__remision',
        'hoja_trabajo__remision__obra',
        'muestra'
    )

    # Filtrar los que deben fallarse hoy (en Python porque es una property)
    muestras_hoy = []
    muestras_vencidas = []
    muestras_proximas = []

    for resultado in resultados_pendientes:
        fecha_falla = resultado.fecha_falla_programada
        if fecha_falla:
            if fecha_falla == hoy:
                muestras_hoy.append(resultado)
            elif fecha_falla < hoy:
                muestras_vencidas.append(resultado)
            elif (fecha_falla - hoy).days <= 3:
                muestras_proximas.append(resultado)

    context = {
        'muestras_hoy': muestras_hoy,
        'muestras_vencidas': muestras_vencidas,
        'muestras_proximas': muestras_proximas,
        'fecha_hoy': hoy,
    }
    return render(request, 'ensayos/muestras_para_hoy.html', context)


@login_required
def detalle_hoja_trabajo(request, pk):
    """
    Vista principal de la hoja de trabajo.
    Muestra todos los datos de la remisión y permite editar los resultados.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    hoja = get_object_or_404(
        HojaTrabajo.objects.select_related(
            'remision',
            'remision__obra',
            'remision__obra__constructora',
            'realizado_por'
        ),
        pk=pk
    )

    resultados = hoja.resultados.select_related('muestra').order_by(
        'muestra__numero_muestra',
        'muestra__edad_ensayo_dias'
    )

    # Agrupar resultados por número de muestra para mejor visualización
    resultados_agrupados = {}
    for resultado in resultados:
        num = resultado.muestra.numero_muestra
        if num not in resultados_agrupados:
            resultados_agrupados[num] = []
        resultados_agrupados[num].append(resultado)

    context = {
        'hoja': hoja,
        'resultados': resultados,
        'resultados_agrupados': resultados_agrupados,
        'fecha_hoy': timezone.now().date(),
    }
    return render(request, 'ensayos/detalle_hoja_trabajo.html', context)


@login_required
def editar_resultado(request, pk):
    """
    Editar un resultado individual.
    Usado con HTMX para actualizacion en tiempo real.
    Soporta actualizaciones parciales (solo los campos enviados).
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    resultado = get_object_or_404(ResultadoMuestra, pk=pk)

    if request.method == 'POST':
        # Campos permitidos para actualizacion parcial
        campos_permitidos = [
            'diametro_d1', 'diametro_d2', 'diametro_d3',
            'longitud_l1', 'longitud_l2', 'longitud_l3',
            'peso_gramos', 'carga_maxima_kn', 'forma_falla',
            'fecha_ensayo', 'observaciones', 'estado'
        ]

        # Detectar si es actualizacion parcial (AJAX desde hoja de trabajo)
        campos_enviados = [k for k in request.POST.keys() if k in campos_permitidos]

        if campos_enviados:
            # Actualizacion parcial - solo actualizar campos enviados
            from decimal import Decimal, InvalidOperation

            for campo in campos_enviados:
                valor = request.POST.get(campo, '').strip()

                if campo in ['diametro_d1', 'diametro_d2', 'diametro_d3',
                             'longitud_l1', 'longitud_l2', 'longitud_l3',
                             'peso_gramos', 'carga_maxima_kn']:
                    # Campos decimales
                    if valor:
                        try:
                            setattr(resultado, campo, Decimal(valor))
                        except (ValueError, InvalidOperation):
                            pass
                    else:
                        setattr(resultado, campo, None)

                elif campo == 'forma_falla':
                    # Campo choice
                    setattr(resultado, campo, valor if valor else '')

                elif campo == 'fecha_ensayo':
                    # Campo fecha
                    if valor:
                        from datetime import datetime
                        try:
                            setattr(resultado, campo, datetime.strptime(valor, '%Y-%m-%d').date())
                        except ValueError:
                            pass
                    else:
                        setattr(resultado, campo, None)

                elif campo == 'observaciones':
                    setattr(resultado, campo, valor)

                elif campo == 'estado':
                    if valor in ['pendiente', 'completado', 'fallido']:
                        setattr(resultado, campo, valor)

            # Auto-completar si tiene todas las mediciones
            if resultado.tiene_mediciones_completas and resultado.estado == 'pendiente':
                resultado.estado = 'completado'
                if not resultado.fecha_ensayo:
                    resultado.fecha_ensayo = timezone.now().date()

            resultado.save()

            # Actualizar estado de la hoja
            resultado.hoja_trabajo.actualizar_estado()

            # Respuesta JSON para AJAX
            return JsonResponse({
                'success': True,
                'pk': resultado.pk,
                'estado': resultado.estado,
                'diametro_real': str(resultado.diametro_real) if resultado.diametro_real else None,
                'longitud_real': str(resultado.longitud_real) if resultado.longitud_real else None,
                'area_mm2': str(resultado.area_mm2) if resultado.area_mm2 else None,
                'esfuerzo_mpa': str(resultado.esfuerzo_mpa) if resultado.esfuerzo_mpa else None,
                'porcentaje_desarrollo': str(resultado.porcentaje_desarrollo) if resultado.porcentaje_desarrollo else None,
                'cumple_resistencia': resultado.cumple_resistencia,
            })

        else:
            # Actualizacion completa via formulario
            form = ResultadoMuestraForm(request.POST, instance=resultado)
            if form.is_valid():
                resultado = form.save(commit=False)

                # Auto-completar si tiene todas las mediciones
                if resultado.tiene_mediciones_completas and resultado.estado == 'pendiente':
                    resultado.estado = 'completado'
                    if not resultado.fecha_ensayo:
                        resultado.fecha_ensayo = timezone.now().date()

                resultado.save()

                # Actualizar estado de la hoja
                resultado.hoja_trabajo.actualizar_estado()

                if request.headers.get('HX-Request'):
                    # Respuesta HTMX: renderizar solo la fila actualizada
                    return render(request, 'ensayos/partials/resultado_row.html', {
                        'resultado': resultado,
                        'fecha_hoy': timezone.now().date(),
                    })
                else:
                    messages.success(request, f"Resultado de muestra #{resultado.muestra.numero_muestra} actualizado.")
                    return redirect('detalle_hoja_trabajo', pk=resultado.hoja_trabajo.pk)
            else:
                if request.headers.get('HX-Request'):
                    return render(request, 'ensayos/partials/resultado_form.html', {
                        'form': form,
                        'resultado': resultado,
                    })
    else:
        form = ResultadoMuestraForm(instance=resultado)

    if request.headers.get('HX-Request'):
        return render(request, 'ensayos/partials/resultado_form.html', {
            'form': form,
            'resultado': resultado,
        })

    context = {
        'form': form,
        'resultado': resultado,
    }
    return render(request, 'ensayos/editar_resultado.html', context)


@login_required
def completar_resultado(request, pk):
    """
    Marcar un resultado como completado (vía HTMX).
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    resultado = get_object_or_404(ResultadoMuestra, pk=pk)

    if request.method == 'POST':
        if resultado.tiene_mediciones_completas:
            resultado.marcar_completado()
            messages.success(request, f"Muestra #{resultado.muestra.numero_muestra} marcada como completada.")
        else:
            messages.error(request, "Faltan mediciones para completar esta muestra.")

    if request.headers.get('HX-Request'):
        return render(request, 'ensayos/partials/resultado_row.html', {
            'resultado': resultado,
            'fecha_hoy': timezone.now().date(),
        })

    return redirect('detalle_hoja_trabajo', pk=resultado.hoja_trabajo.pk)


@login_required
def hojas_trabajo_obra(request, obra_pk):
    """
    Lista las hojas de trabajo de una obra específica.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    obra = get_object_or_404(Obra, pk=obra_pk)

    hojas = HojaTrabajo.objects.filter(
        remision__obra=obra
    ).select_related(
        'remision',
        'realizado_por'
    ).prefetch_related('resultados').order_by('-fecha_creacion')

    context = {
        'obra': obra,
        'hojas': hojas,
    }
    return render(request, 'ensayos/hojas_trabajo_obra.html', context)


@login_required
def lista_obras_hojas_trabajo(request):
    """
    Lista de OBRAS con sus hojas de trabajo.
    Cada obra tiene su propia hoja de trabajo que agrupa todas sus muestras.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    hoy = timezone.now().date()

    # Obtener obras que tienen al menos una hoja de trabajo (remision completada)
    obras_con_hojas = Obra.objects.filter(
        remisiones__hoja_trabajo__isnull=False
    ).distinct().select_related('constructora').order_by('nombre')

    # Filtros
    busqueda = request.GET.get('q', '')
    constructora_filtro = request.GET.get('constructora', '')

    if busqueda:
        obras_con_hojas = obras_con_hojas.filter(
            Q(nombre__icontains=busqueda) |
            Q(codigo_obra__icontains=busqueda) |
            Q(constructora__nombre__icontains=busqueda)
        )

    if constructora_filtro:
        obras_con_hojas = obras_con_hojas.filter(constructora__pk=constructora_filtro)

    # Preparar datos con estadisticas por obra
    obras_con_stats = []
    total_hoy = 0
    total_vencidas = 0

    for obra in obras_con_hojas:
        # Obtener todos los resultados de esta obra
        resultados = ResultadoMuestra.objects.filter(
            hoja_trabajo__remision__obra=obra
        ).select_related('muestra')

        total_muestras = resultados.count()
        completadas = resultados.filter(estado='completado').count()
        pendientes = resultados.filter(estado='pendiente').count()

        # Contar muestras para hoy y vencidas
        muestras_hoy = 0
        muestras_vencidas = 0

        for r in resultados.filter(estado='pendiente'):
            fecha_falla = r.fecha_falla_programada
            if fecha_falla:
                if fecha_falla == hoy:
                    muestras_hoy += 1
                elif fecha_falla < hoy:
                    muestras_vencidas += 1

        total_hoy += muestras_hoy
        total_vencidas += muestras_vencidas

        progreso = int((completadas / total_muestras) * 100) if total_muestras > 0 else 0

        obras_con_stats.append({
            'obra': obra,
            'total_muestras': total_muestras,
            'completadas': completadas,
            'pendientes': pendientes,
            'muestras_hoy': muestras_hoy,
            'muestras_vencidas': muestras_vencidas,
            'progreso': progreso,
        })

    # Obtener constructoras para el filtro
    from users.models import Constructora
    constructoras = Constructora.objects.filter(
        obras__remisiones__hoja_trabajo__isnull=False
    ).distinct().order_by('nombre')

    # Paginacion
    paginator = Paginator(obras_con_stats, 20)
    page = request.GET.get('page', 1)
    obras_page = paginator.get_page(page)

    context = {
        'obras': obras_page,
        'fecha_hoy': hoy,
        'busqueda': busqueda,
        'constructora_filtro': constructora_filtro,
        'constructoras': constructoras,
        'total_hoy': total_hoy,
        'total_vencidas': total_vencidas,
        'total_obras': len(obras_con_stats),
    }
    return render(request, 'ensayos/lista_obras_hojas_trabajo.html', context)


@login_required
def hoja_trabajo_obra(request, obra_pk):
    """
    Hoja de trabajo de UNA OBRA especifica.
    Muestra TODAS las muestras de TODAS las remisiones de esa obra.
    """
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    obra = get_object_or_404(Obra.objects.select_related('constructora'), pk=obra_pk)
    hoy = timezone.now().date()

    # Obtener TODOS los resultados de esta obra
    resultados = ResultadoMuestra.objects.filter(
        hoja_trabajo__remision__obra=obra
    ).select_related(
        'hoja_trabajo',
        'hoja_trabajo__remision',
        'muestra'
    ).order_by(
        'muestra__numero_muestra',
        'muestra__edad_ensayo_dias'
    )

    # Preparar datos con informacion de fecha de falla
    resultados_con_info = []
    conteo_hoy = 0
    conteo_vencidas = 0
    conteo_completadas = 0

    for resultado in resultados:
        fecha_falla = resultado.fecha_falla_programada
        es_hoy = False
        esta_vencida = False
        dias_restantes = None

        if resultado.estado == 'completado':
            conteo_completadas += 1
        elif fecha_falla:
            dias_restantes = (fecha_falla - hoy).days
            if dias_restantes == 0:
                es_hoy = True
                conteo_hoy += 1
            elif dias_restantes < 0:
                esta_vencida = True
                conteo_vencidas += 1

        resultados_con_info.append({
            'resultado': resultado,
            'muestra': resultado.muestra,  # Pasar muestra explicitamente
            'fecha_falla': fecha_falla,
            'es_hoy': es_hoy,
            'esta_vencida': esta_vencida,
            'dias_restantes': dias_restantes,
        })

    # Estadisticas
    total_muestras = len(resultados_con_info)
    progreso = int((conteo_completadas / total_muestras) * 100) if total_muestras > 0 else 0

    context = {
        'obra': obra,
        'resultados': resultados_con_info,
        'fecha_hoy': hoy,
        'conteo_hoy': conteo_hoy,
        'conteo_vencidas': conteo_vencidas,
        'conteo_completadas': conteo_completadas,
        'total_muestras': total_muestras,
        'progreso': progreso,
    }
    return render(request, 'ensayos/hoja_trabajo_obra.html', context)


@login_required
def toggle_seleccion(request, pk):
    """
    Alternar selección de una muestra (vía HTMX).
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    resultado = get_object_or_404(ResultadoMuestra, pk=pk)

    if request.method == 'POST':
        resultado.seleccionado = not resultado.seleccionado
        resultado.save(update_fields=['seleccionado'])

        if request.headers.get('HX-Request'):
            return JsonResponse({
                'seleccionado': resultado.seleccionado,
                'pk': resultado.pk
            })

    return JsonResponse({'seleccionado': resultado.seleccionado})


@login_required
def seleccionar_muestras_hoy(request):
    """
    Seleccionar automáticamente todas las muestras que deben fallarse hoy.
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    if request.method == 'POST':
        hoy = timezone.now().date()

        # Obtener todas las muestras pendientes
        resultados = ResultadoMuestra.objects.filter(
            estado='pendiente'
        ).select_related('muestra')

        seleccionados = 0
        for resultado in resultados:
            fecha_falla = resultado.fecha_falla_programada
            if fecha_falla and (fecha_falla == hoy or fecha_falla < hoy):
                resultado.seleccionado = True
                resultado.save(update_fields=['seleccionado'])
                seleccionados += 1

        return JsonResponse({
            'success': True,
            'seleccionados': seleccionados,
            'mensaje': f'{seleccionados} muestras seleccionadas para hoy'
        })

    return JsonResponse({'error': 'Método no permitido'}, status=405)


@login_required
def deseleccionar_todas(request):
    """
    Deseleccionar todas las muestras.
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'No autorizado'}, status=403)

    if request.method == 'POST':
        ResultadoMuestra.objects.filter(seleccionado=True).update(seleccionado=False)
        return JsonResponse({
            'success': True,
            'mensaje': 'Todas las muestras deseleccionadas'
        })

    return JsonResponse({'error': 'Método no permitido'}, status=405)


@login_required
def dashboard_tecnico(request):
    """
    Dashboard para Técnicos de Laboratorio.
    Muestra las muestras del día y vencidas, agrupadas por obra.
    Vista simplificada con solo los campos que el técnico necesita llenar.
    """
    # Verificar que sea técnico de laboratorio o staff
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder a esta sección.")
        return redirect('home')

    hoy = timezone.now().date()

    # Obtener todos los resultados pendientes
    resultados_pendientes = ResultadoMuestra.objects.filter(
        estado='pendiente'
    ).select_related(
        'hoja_trabajo',
        'hoja_trabajo__remision',
        'hoja_trabajo__remision__obra',
        'hoja_trabajo__remision__obra__constructora',
        'muestra'
    )

    # Agrupar por obra, filtrando solo muestras de hoy y vencidas
    obras_con_muestras = {}
    total_hoy = 0
    total_vencidas = 0

    for resultado in resultados_pendientes:
        fecha_falla = resultado.fecha_falla_programada
        if fecha_falla:
            es_hoy = fecha_falla == hoy
            esta_vencida = fecha_falla < hoy

            if es_hoy or esta_vencida:
                obra = resultado.hoja_trabajo.remision.obra

                if obra.pk not in obras_con_muestras:
                    obras_con_muestras[obra.pk] = {
                        'obra': obra,
                        'muestras_hoy': [],
                        'muestras_vencidas': [],
                    }

                muestra_info = {
                    'resultado': resultado,
                    'muestra': resultado.muestra,
                    'fecha_falla': fecha_falla,
                    'dias_vencida': (hoy - fecha_falla).days if esta_vencida else 0,
                }

                if es_hoy:
                    obras_con_muestras[obra.pk]['muestras_hoy'].append(muestra_info)
                    total_hoy += 1
                else:
                    obras_con_muestras[obra.pk]['muestras_vencidas'].append(muestra_info)
                    total_vencidas += 1

    # Convertir a lista y ordenar por cantidad de muestras urgentes
    obras_lista = sorted(
        obras_con_muestras.values(),
        key=lambda x: len(x['muestras_vencidas']) + len(x['muestras_hoy']),
        reverse=True
    )

    context = {
        'obras': obras_lista,
        'fecha_hoy': hoy,
        'total_hoy': total_hoy,
        'total_vencidas': total_vencidas,
        'total_pendientes': total_hoy + total_vencidas,
    }
    return render(request, 'ensayos/dashboard_tecnico.html', context)
