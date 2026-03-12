import json
import logging
import re
import os

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncMonth
from django.http import JsonResponse, Http404, HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.conf import settings

from .models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio, Factura,
)
from .forms import (
    CategoriaServicioForm, TipoServicioForm, PrecioServicioForm,
    PrecioServicioFormSet, ImpuestoForm, RegistroServicioForm,
    FiltroHistoricoForm, GenerarFacturaForm,
)
from users.models import Constructora
from core.models import Obra

logger = logging.getLogger(__name__)


def staff_required(view_func):
    """Decorador: requiere login + es_geolab + es_admin_geolab."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.es_geolab or not request.user.es_admin_geolab:
            messages.error(request, 'No tienes permiso para acceder a Facturación.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def dashboard_facturacion(request):
    """Dashboard de facturación con KPIs y gráfica."""
    hoy = timezone.now().date()
    primer_dia_mes = hoy.replace(day=1)

    # KPIs
    total_constructoras = Constructora.objects.count()
    total_obras = Obra.objects.count()

    facturas_mes = Factura.objects.filter(
        fecha_emision__gte=primer_dia_mes
    ).exclude(estado='ANULADA')
    facturas_mes_count = facturas_mes.count()
    facturas_mes_total = facturas_mes.aggregate(
        total=Sum('total')
    )['total'] or Decimal('0')

    registros_mes = RegistroServicio.objects.filter(
        fecha_creacion__date__gte=primer_dia_mes
    ).count()

    registros_pendientes = RegistroServicio.objects.filter(
        factura__isnull=True
    ).count()

    # Top 3 clientes por facturación histórica
    top_clientes = Constructora.objects.filter(
        facturas__isnull=False
    ).exclude(
        facturas__estado='ANULADA'
    ).annotate(
        total_facturado=Sum('facturas__total')
    ).order_by('-total_facturado')[:3]

    # Top 3 servicios más registrados (últimos 90 días)
    hace_90_dias = hoy - timezone.timedelta(days=90)
    top_servicios = TipoServicio.objects.filter(
        registros__fecha_realizacion__gte=hace_90_dias
    ).annotate(
        total_registros=Count('registros')
    ).order_by('-total_registros')[:3]

    context = {
        'total_constructoras': total_constructoras,
        'total_obras': total_obras,
        'facturas_mes_count': facturas_mes_count,
        'facturas_mes_total': facturas_mes_total,
        'registros_mes': registros_mes,
        'registros_pendientes': registros_pendientes,
        'top_clientes': top_clientes,
        'top_servicios': top_servicios,
    }
    return render(request, 'facturacion/dashboard.html', context)


@staff_required
def api_facturacion_mensual(request):
    """API: facturación mensual últimos 6 meses para Chart.js."""
    hoy = timezone.now().date()
    hace_6_meses = hoy.replace(day=1) - timezone.timedelta(days=180)

    datos = Factura.objects.filter(
        fecha_emision__gte=hace_6_meses
    ).exclude(
        estado='ANULADA'
    ).annotate(
        mes=TruncMonth('fecha_emision')
    ).values('mes').annotate(
        total=Sum('total')
    ).order_by('mes')

    labels = []
    data = []
    meses_es = [
        '', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
        'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'
    ]
    for item in datos:
        mes = item['mes']
        labels.append(f"{meses_es[mes.month]} {mes.year}")
        data.append(float(item['total']))

    return JsonResponse({'labels': labels, 'data': data})


# ═══════════════════════════════════════════════════════════════════════════════
# CATÁLOGO DE SERVICIOS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def catalogo_servicios(request):
    """Lista de servicios agrupados por categoría."""
    categorias = CategoriaServicio.objects.prefetch_related('servicios').all()

    # Búsqueda
    q = request.GET.get('q', '')
    if q:
        servicios_filtrados = TipoServicio.objects.filter(
            Q(codigo__icontains=q) | Q(nombre__icontains=q) | Q(norma__icontains=q)
        ).select_related('categoria')
        context = {
            'servicios_filtrados': servicios_filtrados,
            'q': q,
            'categorias': categorias,
        }
    else:
        context = {
            'categorias': categorias,
            'q': q,
        }

    return render(request, 'facturacion/catalogo_servicios.html', context)


@staff_required
def crear_categoria(request):
    """Crear nueva categoría de servicio."""
    if request.method == 'POST':
        form = CategoriaServicioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría creada exitosamente.')
            return redirect('catalogo_servicios')
    else:
        form = CategoriaServicioForm()
    return render(request, 'facturacion/categoria_form.html', {
        'form': form, 'titulo': 'Nueva Categoría'
    })


@staff_required
def editar_categoria(request, pk):
    """Editar categoría existente."""
    categoria = get_object_or_404(CategoriaServicio, pk=pk)
    if request.method == 'POST':
        form = CategoriaServicioForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría actualizada.')
            return redirect('catalogo_servicios')
    else:
        form = CategoriaServicioForm(instance=categoria)
    return render(request, 'facturacion/categoria_form.html', {
        'form': form, 'titulo': f'Editar: {categoria.nombre}'
    })


@staff_required
def crear_servicio(request):
    """Crear nuevo tipo de servicio."""
    if request.method == 'POST':
        form = TipoServicioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Servicio creado exitosamente.')
            return redirect('catalogo_servicios')
    else:
        form = TipoServicioForm()
    return render(request, 'facturacion/servicio_form.html', {
        'form': form, 'titulo': 'Nuevo Servicio'
    })


@staff_required
def editar_servicio(request, pk):
    """Editar tipo de servicio existente."""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    if request.method == 'POST':
        form = TipoServicioForm(request.POST, instance=servicio)
        if form.is_valid():
            form.save()
            messages.success(request, 'Servicio actualizado.')
            return redirect('catalogo_servicios')
    else:
        form = TipoServicioForm(instance=servicio)
    return render(request, 'facturacion/servicio_form.html', {
        'form': form, 'titulo': f'Editar: {servicio.nombre}'
    })


@staff_required
def eliminar_servicio(request, pk):
    """Eliminar tipo de servicio (solo si no tiene registros)."""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    if request.method == 'POST':
        if servicio.registros.exists():
            messages.error(
                request,
                'No se puede eliminar: tiene registros asociados.'
            )
        else:
            nombre = servicio.nombre
            servicio.delete()
            messages.success(request, f'Servicio "{nombre}" eliminado.')
        return redirect('catalogo_servicios')
    return render(request, 'facturacion/eliminar_confirm.html', {
        'objeto': servicio, 'tipo': 'servicio', 'nombre': servicio.nombre,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PRECIOS POR OBRA
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def gestionar_precios_obra(request, obra_pk):
    """
    Gestionar lista de precios de una obra.
    Crea PrecioServicio para cada TipoServicio que no exista.
    """
    obra = get_object_or_404(Obra.objects.select_related('constructora'), pk=obra_pk)

    # Asegurar que exista un PrecioServicio para cada TipoServicio
    servicios_existentes = set(
        PrecioServicio.objects.filter(obra=obra).values_list('tipo_servicio_id', flat=True)
    )
    todos_servicios = TipoServicio.objects.all()

    nuevos = [
        PrecioServicio(obra=obra, tipo_servicio=s)
        for s in todos_servicios if s.pk not in servicios_existentes
    ]
    if nuevos:
        PrecioServicio.objects.bulk_create(nuevos)

    # Obtener precios organizados por categoría
    precios = PrecioServicio.objects.filter(
        obra=obra
    ).select_related(
        'tipo_servicio', 'tipo_servicio__categoria'
    ).order_by('tipo_servicio__categoria__codigo', 'tipo_servicio__codigo')

    if request.method == 'POST':
        formset = PrecioServicioFormSet(request.POST, queryset=precios)
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Precios actualizados correctamente.')
            return redirect('gestionar_precios_obra', obra_pk=obra.pk)
    else:
        formset = PrecioServicioFormSet(queryset=precios)

    # Agrupar por categoría para mejor visualización
    precios_por_categoria = {}
    for precio, form in zip(precios, formset):
        cat = precio.tipo_servicio.categoria
        if cat.pk not in precios_por_categoria:
            precios_por_categoria[cat.pk] = {
                'categoria': cat,
                'items': [],
            }
        precios_por_categoria[cat.pk]['items'].append({
            'precio': precio,
            'form': form,
        })

    context = {
        'obra': obra,
        'formset': formset,
        'precios_por_categoria': precios_por_categoria.values(),
    }
    return render(request, 'facturacion/gestionar_precios.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
# IMPUESTOS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def lista_impuestos(request):
    """Lista y gestión de impuestos."""
    impuestos = Impuesto.objects.all()
    return render(request, 'facturacion/lista_impuestos.html', {
        'impuestos': impuestos,
    })


@staff_required
def crear_impuesto(request):
    if request.method == 'POST':
        form = ImpuestoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Impuesto creado.')
            return redirect('lista_impuestos')
    else:
        form = ImpuestoForm()
    return render(request, 'facturacion/impuesto_form.html', {
        'form': form, 'titulo': 'Nuevo Impuesto'
    })


@staff_required
def editar_impuesto(request, pk):
    impuesto = get_object_or_404(Impuesto, pk=pk)
    if request.method == 'POST':
        form = ImpuestoForm(request.POST, instance=impuesto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Impuesto actualizado.')
            return redirect('lista_impuestos')
    else:
        form = ImpuestoForm(instance=impuesto)
    return render(request, 'facturacion/impuesto_form.html', {
        'form': form, 'titulo': f'Editar: {impuesto.nombre}'
    })


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRO DE SERVICIOS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def crear_registro(request):
    """
    Crear registro(s) de servicio.
    GET: formulario multi-paso.
    POST (AJAX JSON): creación atómica de múltiples registros.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'JSON inválido.'}, status=400)

        obra_id = data.get('obra_id')
        fecha_str = data.get('fecha_realizacion')
        servicios = data.get('servicios', [])

        if not obra_id or not fecha_str or not servicios:
            return JsonResponse({
                'status': 'error',
                'message': 'Faltan datos requeridos (obra, fecha, servicios).'
            }, status=400)

        try:
            obra = Obra.objects.get(pk=obra_id)
        except Obra.DoesNotExist:
            return JsonResponse({
                'status': 'error', 'message': 'Obra no encontrada.'
            }, status=404)

        errores = []
        registros_creados = 0

        try:
            with transaction.atomic():
                for i, srv in enumerate(servicios, 1):
                    tipo_id = srv.get('tipo_servicio_id')
                    num_informe = srv.get('numero_informe', '').strip()
                    cantidad = int(srv.get('cantidad', 1))

                    if not tipo_id or not num_informe:
                        errores.append(f"Línea {i}: faltan datos.")
                        continue

                    try:
                        tipo_servicio = TipoServicio.objects.get(pk=tipo_id)
                    except TipoServicio.DoesNotExist:
                        errores.append(f"Línea {i}: servicio no encontrado.")
                        continue

                    try:
                        precio_obj = PrecioServicio.objects.get(
                            obra=obra, tipo_servicio=tipo_servicio
                        )
                        if precio_obj.precio is None:
                            errores.append(
                                f"Línea {i}: {tipo_servicio.codigo} no tiene precio "
                                f"configurado para esta obra."
                            )
                            continue
                        precio = precio_obj.precio
                    except PrecioServicio.DoesNotExist:
                        errores.append(
                            f"Línea {i}: no existe precio para {tipo_servicio.codigo} "
                            f"en esta obra."
                        )
                        continue

                    RegistroServicio.objects.create(
                        obra=obra,
                        tipo_servicio=tipo_servicio,
                        fecha_realizacion=fecha_str,
                        cantidad=cantidad,
                        numero_informe=num_informe,
                        precio_unitario_congelado=precio,
                        creado_por=request.user,
                    )
                    registros_creados += 1

                if errores and registros_creados == 0:
                    raise ValueError("Ningún registro pudo crearse.")

        except ValueError:
            return JsonResponse({
                'status': 'error',
                'message': ' | '.join(errores),
            }, status=400)

        except Exception as e:
            logger.exception(f"Error creando registros: {e}")
            return JsonResponse({
                'status': 'error',
                'message': 'Error interno al crear registros.',
            }, status=500)

        msg = f'{registros_creados} registro(s) creado(s) exitosamente.'
        if errores:
            msg += f' Advertencias: {"; ".join(errores)}'

        return JsonResponse({'status': 'success', 'message': msg})

    # GET: renderizar formulario
    constructoras = Constructora.objects.all().order_by('nombre')
    servicios = TipoServicio.objects.select_related('categoria').order_by(
        'categoria__codigo', 'codigo'
    )

    context = {
        'constructoras': constructoras,
        'servicios': servicios,
        'fecha_hoy': timezone.now().date().isoformat(),
    }
    return render(request, 'facturacion/crear_registro.html', context)


@staff_required
def editar_registro(request, pk):
    """
    Editar registro no facturado.
    Al guardar, re-congela el precio desde PrecioServicio actual.
    """
    registro = get_object_or_404(RegistroServicio, pk=pk)

    if registro.esta_facturado:
        messages.error(request, 'No se puede editar un registro ya facturado.')
        return redirect('historico_facturacion')

    if request.method == 'POST':
        form = RegistroServicioForm(request.POST, instance=registro)
        if form.is_valid():
            registro = form.save(commit=False)
            # Re-congelar precio
            try:
                precio_obj = PrecioServicio.objects.get(
                    obra=registro.obra, tipo_servicio=registro.tipo_servicio
                )
                registro.precio_unitario_congelado = precio_obj.precio or Decimal('0')
            except PrecioServicio.DoesNotExist:
                registro.precio_unitario_congelado = Decimal('0')
            registro.save()
            messages.success(request, 'Registro actualizado correctamente.')
            return redirect('historico_facturacion')
    else:
        form = RegistroServicioForm(instance=registro)

    return render(request, 'facturacion/registro_editar.html', {
        'form': form, 'registro': registro,
    })


@staff_required
@require_POST
def eliminar_registro(request, pk):
    """Eliminar registro no facturado."""
    registro = get_object_or_404(RegistroServicio, pk=pk)
    if registro.esta_facturado:
        messages.error(request, 'No se puede eliminar un registro facturado.')
    else:
        registro.delete()
        messages.success(request, 'Registro eliminado.')
    return redirect('historico_facturacion')


# ═══════════════════════════════════════════════════════════════════════════════
# HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def historico_facturacion(request):
    """Histórico de todos los registros de servicio con filtros."""
    registros = RegistroServicio.objects.select_related(
        'obra', 'obra__constructora', 'tipo_servicio',
        'tipo_servicio__categoria', 'factura',
    ).all()

    form = FiltroHistoricoForm(request.GET or None)

    # Aplicar filtros
    constructora = request.GET.get('constructora')
    if constructora:
        registros = registros.filter(obra__constructora_id=constructora)

    obra = request.GET.get('obra')
    if obra:
        registros = registros.filter(obra_id=obra)

    tipo_servicio = request.GET.get('tipo_servicio')
    if tipo_servicio:
        registros = registros.filter(tipo_servicio_id=tipo_servicio)

    fecha_inicio = request.GET.get('fecha_inicio')
    if fecha_inicio:
        registros = registros.filter(fecha_realizacion__gte=fecha_inicio)

    fecha_fin = request.GET.get('fecha_fin')
    if fecha_fin:
        registros = registros.filter(fecha_realizacion__lte=fecha_fin)

    # Paginación
    paginator = Paginator(registros, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'form': form,
        'total_registros': registros.count(),
    }
    return render(request, 'facturacion/historico.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
# GENERACIÓN DE FACTURAS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def generar_factura(request):
    """
    Preview de factura.
    Muestra registros pendientes separados en normales y transporte.
    """
    form = GenerarFacturaForm(request.GET or None)
    registros_normales = []
    registros_transporte = []
    subtotal_normales = Decimal('0')
    subtotal_transporte = Decimal('0')
    iva_porcentaje = Decimal('0')
    obra = None
    tiene_registros = False

    if request.GET.get('obra') and request.GET.get('fecha_inicio') and request.GET.get('fecha_fin'):
        obra_id = request.GET.get('obra')
        fecha_inicio = request.GET.get('fecha_inicio')
        fecha_fin = request.GET.get('fecha_fin')

        try:
            obra = Obra.objects.select_related('constructora').get(pk=obra_id)
        except Obra.DoesNotExist:
            messages.error(request, 'Obra no encontrada.')
            return render(request, 'facturacion/generar_factura.html', {'form': form})

        # Obtener registros pendientes en el periodo
        registros = RegistroServicio.objects.filter(
            obra=obra,
            fecha_realizacion__range=(fecha_inicio, fecha_fin),
            factura__isnull=True,
        ).select_related(
            'tipo_servicio', 'tipo_servicio__categoria'
        ).order_by('fecha_realizacion', 'tipo_servicio__codigo')

        for r in registros:
            if r.es_transporte:
                registros_transporte.append(r)
                subtotal_transporte += r.subtotal
            else:
                registros_normales.append(r)
                subtotal_normales += r.subtotal

        tiene_registros = len(registros_normales) > 0 or len(registros_transporte) > 0

        # Obtener IVA
        try:
            impuesto = Impuesto.objects.get(nombre__iexact='IVA', activo=True)
            iva_porcentaje = impuesto.porcentaje
        except Impuesto.DoesNotExist:
            iva_porcentaje = Decimal('0')

    context = {
        'form': form,
        'obra': obra,
        'registros_normales': registros_normales,
        'registros_transporte': registros_transporte,
        'subtotal_normales': subtotal_normales,
        'subtotal_transporte': subtotal_transporte,
        'subtotal_total': subtotal_normales + subtotal_transporte,
        'iva_porcentaje': iva_porcentaje,
        'tiene_registros': tiene_registros,
    }
    return render(request, 'facturacion/generar_factura.html', context)


@staff_required
@require_POST
def finalizar_factura(request):
    """
    Finaliza la factura: calcula IVA, crea Factura, vincula registros, genera PDF.

    REGLA DE IVA:
    - Servicios normales: SIEMPRE en base IVA
    - Transporte (categoría '7'): SOLO si seleccionado via checkbox
    """
    obra_id = request.POST.get('obra_id')
    fecha_inicio = request.POST.get('fecha_inicio')
    fecha_fin = request.POST.get('fecha_fin')
    ids_transporte_con_iva = request.POST.getlist('transporte_con_iva')

    if not obra_id or not fecha_inicio or not fecha_fin:
        messages.error(request, 'Datos incompletos.')
        return redirect('generar_factura')

    obra = get_object_or_404(Obra.objects.select_related('constructora'), pk=obra_id)

    try:
        with transaction.atomic():
            # Obtener registros a facturar
            registros_a_facturar = RegistroServicio.objects.filter(
                obra=obra,
                fecha_realizacion__range=(fecha_inicio, fecha_fin),
                factura__isnull=True,
            ).select_related('tipo_servicio__categoria')

            if not registros_a_facturar.exists():
                messages.error(request, 'No hay registros pendientes en ese periodo.')
                return redirect('generar_factura')

            # Calcular montos
            subtotal_completo = Decimal('0')
            base_iva_normales = Decimal('0')
            base_iva_transporte = Decimal('0')

            for r in registros_a_facturar:
                subtotal_completo += r.subtotal
                if r.es_transporte:
                    if str(r.pk) in ids_transporte_con_iva:
                        base_iva_transporte += r.subtotal
                else:
                    base_iva_normales += r.subtotal

            # Obtener IVA
            try:
                impuesto = Impuesto.objects.get(nombre__iexact='IVA', activo=True)
                iva_porcentaje = impuesto.porcentaje
            except Impuesto.DoesNotExist:
                iva_porcentaje = Decimal('0')

            base_para_iva = base_iva_normales + base_iva_transporte
            monto_iva = base_para_iva * (iva_porcentaje / 100)
            total = subtotal_completo + monto_iva

            # Crear factura
            factura = Factura.objects.create(
                constructora=obra.constructora,
                obra=obra,
                fecha_inicio_periodo=fecha_inicio,
                fecha_fin_periodo=fecha_fin,
                subtotal=subtotal_completo,
                monto_iva=monto_iva.quantize(Decimal('0.01')),
                total=total.quantize(Decimal('0.01')),
                iva_transporte_facturado=bool(ids_transporte_con_iva),
                emitida_por=request.user,
            )

            # Vincular registros
            registros_a_facturar.update(factura=factura)

            # Generar PDF
            try:
                _generar_pdf_factura(factura, request)
            except Exception as e:
                logger.exception(f"Error generando PDF de factura #{factura.pk}: {e}")
                messages.warning(
                    request,
                    'Factura creada pero hubo un error al generar el PDF.'
                )

            logger.info(
                f"Factura #{factura.pk} creada por {request.user.username}. "
                f"Obra: {obra.nombre}. Total: ${total}"
            )

        messages.success(
            request,
            f'Factura #{factura.pk} generada exitosamente. Total: ${total:,.2f}'
        )
        return redirect('repositorio_facturas_obra', obra_pk=obra.pk)

    except Exception as e:
        logger.exception(f"Error finalizando factura: {e}")
        messages.error(request, 'Error al generar la factura. Intente nuevamente.')
        return redirect('generar_factura')


def _generar_pdf_factura(factura, request):
    """Genera el PDF de una factura usando WeasyPrint."""
    from weasyprint import HTML

    registros = factura.registros.select_related(
        'tipo_servicio', 'tipo_servicio__categoria'
    ).order_by('tipo_servicio__categoria__codigo', 'fecha_realizacion')

    logo_file = os.path.join(settings.BASE_DIR, 'static', 'img', 'geolab-logo.png')
    logo_path = 'file:///' + logo_file.replace('\\', '/')

    # Separar registros para el PDF
    registros_normales = [r for r in registros if not r.es_transporte]
    registros_transporte = [r for r in registros if r.es_transporte]

    context = {
        'factura': factura,
        'registros': registros,
        'registros_normales': registros_normales,
        'registros_transporte': registros_transporte,
        'logo_path': logo_path,
    }

    html_string = render_to_string('facturacion/factura_pdf.html', context)
    base_url = 'file:///' + str(settings.BASE_DIR).replace('\\', '/') + '/'
    pdf_content = HTML(string=html_string, base_url=base_url).write_pdf()

    # Guardar usando FileField
    nombre_limpio = re.sub(r'[^\w\s\-]', '', factura.obra.nombre).strip()
    fecha_str = factura.fecha_emision.strftime('%Y-%m')
    filename = f"Factura_{factura.pk}_{nombre_limpio}_{fecha_str}.pdf"

    from django.core.files.base import ContentFile
    factura.pdf_archivo.save(filename, ContentFile(pdf_content), save=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ANULACIÓN DE FACTURAS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
@require_POST
def anular_factura(request, pk):
    """
    Anula una factura: desvincula registros y marca como ANULADA.
    Los registros quedan disponibles para re-facturación.
    """
    factura = get_object_or_404(Factura, pk=pk)

    if factura.esta_anulada:
        messages.warning(request, 'Esta factura ya está anulada.')
        return redirect('repositorio_facturas_obra', obra_pk=factura.obra.pk)

    try:
        with transaction.atomic():
            # Liberar registros
            factura.registros.all().update(factura=None)
            # Marcar como anulada
            factura.estado = 'ANULADA'
            factura.save(update_fields=['estado'])

            logger.info(
                f"Factura #{factura.pk} anulada por {request.user.username}"
            )

        messages.success(request, f'Factura #{factura.pk} anulada correctamente.')
    except Exception as e:
        logger.exception(f"Error anulando factura #{factura.pk}: {e}")
        messages.error(request, 'Error al anular la factura.')

    return redirect('repositorio_facturas_obra', obra_pk=factura.obra.pk)


@staff_required
@require_POST
def marcar_factura_pagada(request, pk):
    """Marca una factura como pagada."""
    factura = get_object_or_404(Factura, pk=pk)
    if factura.esta_anulada:
        messages.error(request, 'No se puede marcar como pagada una factura anulada.')
    else:
        factura.estado = 'PAGADA'
        factura.save(update_fields=['estado'])
        messages.success(request, f'Factura #{factura.pk} marcada como pagada.')
    return redirect('repositorio_facturas_obra', obra_pk=factura.obra.pk)


# ═══════════════════════════════════════════════════════════════════════════════
# REPOSITORIO DE FACTURAS (Drill-down 3 niveles)
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def repositorio_clientes(request):
    """Nivel 1: Constructoras con facturas."""
    constructoras = Constructora.objects.filter(
        facturas__isnull=False
    ).distinct().annotate(
        total_facturas=Count('facturas'),
        total_facturado=Sum('facturas__total', filter=~Q(facturas__estado='ANULADA')),
    ).order_by('nombre')

    context = {
        'constructoras': constructoras,
    }
    return render(request, 'facturacion/repositorio_clientes.html', context)


@staff_required
def repositorio_obras_cliente(request, constructora_pk):
    """Nivel 2: Obras de una constructora con facturas."""
    constructora = get_object_or_404(Constructora, pk=constructora_pk)

    obras = Obra.objects.filter(
        constructora=constructora,
        facturas__isnull=False,
    ).distinct().annotate(
        total_facturas=Count('facturas'),
        total_facturado=Sum('facturas__total', filter=~Q(facturas__estado='ANULADA')),
    ).order_by('nombre')

    context = {
        'constructora': constructora,
        'obras': obras,
    }
    return render(request, 'facturacion/repositorio_obras.html', context)


@staff_required
def repositorio_facturas_obra(request, obra_pk):
    """Nivel 3: Facturas de una obra."""
    obra = get_object_or_404(Obra.objects.select_related('constructora'), pk=obra_pk)

    facturas = Factura.objects.filter(obra=obra).order_by('-fecha_emision')

    context = {
        'obra': obra,
        'facturas': facturas,
    }
    return render(request, 'facturacion/repositorio_facturas.html', context)


@staff_required
def descargar_factura_pdf(request, pk):
    """Descarga el PDF de una factura."""
    factura = get_object_or_404(Factura, pk=pk)

    if not factura.pdf_archivo:
        # Intentar regenerar
        try:
            _generar_pdf_factura(factura, request)
            factura.refresh_from_db()
        except Exception:
            messages.error(request, 'No se pudo generar el PDF.')
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra.pk)

    # Redirigir a la URL del archivo (S3 en prod, media local en dev)
    return redirect(factura.pdf_archivo.url)


# ═══════════════════════════════════════════════════════════════════════════════
# APIs JSON
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def api_get_obras(request):
    """API: obtener obras de una constructora."""
    constructora_id = request.GET.get('constructora_id')
    if not constructora_id:
        return JsonResponse({'obras': []})
    obras = Obra.objects.filter(
        constructora_id=constructora_id
    ).values('id', 'nombre', 'codigo_obra').order_by('nombre')
    return JsonResponse({'obras': list(obras)})


@staff_required
def api_get_precio(request):
    """API: obtener precio de un servicio para una obra."""
    obra_id = request.GET.get('obra_id')
    tipo_id = request.GET.get('tiposervicio_id')
    if not obra_id or not tipo_id:
        return JsonResponse({'precio': None})
    try:
        precio = PrecioServicio.objects.get(
            obra_id=obra_id, tipo_servicio_id=tipo_id
        )
        return JsonResponse({
            'precio': str(precio.precio) if precio.precio else None
        })
    except PrecioServicio.DoesNotExist:
        return JsonResponse({'precio': None})


@staff_required
def api_buscar_servicios(request):
    """API: buscar servicios por texto."""
    q = request.GET.get('q', '')
    if len(q) < 2:
        return JsonResponse({'servicios': []})
    servicios = TipoServicio.objects.filter(
        Q(codigo__icontains=q) | Q(nombre__icontains=q)
    ).values('id', 'codigo', 'nombre', 'categoria__nombre')[:20]
    return JsonResponse({'servicios': list(servicios)})
