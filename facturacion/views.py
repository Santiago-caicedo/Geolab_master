import json
import logging
import re
import os
import uuid

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, Q, F, Min, Max
from django.db.models.functions import TruncMonth
from django.http import JsonResponse, Http404, HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.conf import settings

from .models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio, Factura,
)
from .forms import (
    CategoriaServicioForm, TipoServicioForm, PrecioServicioForm,
    ImpuestoForm, RegistroServicioForm,
    FiltroHistoricoForm, GenerarFacturaForm,
)
from users.models import Constructora
from core.models import Obra
from . import permisos, sede

logger = logging.getLogger(__name__)


def _rechazo_staff(request):
    """Respuesta de rechazo si el usuario no puede usar Facturación; None si pasa."""
    user = request.user
    if not user.is_authenticated:
        return redirect('login')
    if permisos.puede_entrar(user):
        return None
    if permisos.es_restringido(user):
        # Usuario de Facturación sin ciudades o sin secciones: no hay a dónde mandarlo
        # (el portal lo devolvería aquí), así que se le explica y se queda.
        return render(request, 'facturacion/sin_acceso.html', status=403)
    messages.error(request, 'No tienes permiso para acceder a Facturación.')
    return redirect('home')


def staff_sin_ciudad(view_func):
    """Decorador: requiere poder usar el módulo (sin ciudad)."""
    def wrapper(request, *args, **kwargs):
        rechazo = _rechazo_staff(request)
        if rechazo:
            return rechazo
        return view_func(request, *args, **kwargs)
    return wrapper


def superusuario_required(view_func):
    """Decorador: solo superusuarios (administración de los Usuarios de Facturación)."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_superuser:
            messages.error(request, 'Solo un superusuario puede administrar los usuarios de Facturación.')
            if permisos.puede_entrar(request.user):
                return redirect(permisos.url_inicio(request.user))
            return redirect('home')
        ciudad = sede.ciudad_actual(request)
        if ciudad:
            request.ciudad_facturacion = ciudad
        return view_func(request, *args, **kwargs)
    return wrapper


def _es_ajax(request):
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.content_type == 'application/json')


def staff_required(view_func):
    """
    Decorador: usuario del módulo + ciudad seleccionada + permiso sobre la vista.

    Todo el módulo trabaja sobre una ciudad (sede) guardada en la sesión.
    Si no hay ciudad, redirige a seleccionar_ciudad (las APIs JSON y las
    peticiones AJAX devuelven JSON en vez de redirigir: una pantalla que
    espera JSON y recibe el login mostraba "Error de conexión"). Deja la
    ciudad en `request.ciudad_facturacion` para vistas y templates.

    El Usuario de Facturación solo pasa con una ciudad suya y una vista que
    alguna de sus secciones abra (facturacion/permisos.py); si le quitan la
    ciudad que tenía en la sesión, vuelve al selector.
    """
    def wrapper(request, *args, **kwargs):
        rechazo = _rechazo_staff(request)
        if rechazo:
            if _es_ajax(request):
                return JsonResponse(
                    {'status': 'error', 'sesion': True,
                     'message': 'Tu sesión venció o no tienes permiso. Recarga la página e inicia sesión de nuevo.'},
                    status=401 if not request.user.is_authenticated else 403,
                )
            return rechazo
        user = request.user
        ciudad = sede.ciudad_actual(request)
        if ciudad and not permisos.puede_ciudad(user, ciudad):
            sede.olvidar_ciudad(request)
            ciudad = None
        if not ciudad:
            ciudad = permisos.ciudad_unica(user)
            if ciudad:
                sede.fijar_ciudad(request, ciudad)
        if not ciudad:
            if request.path.startswith('/facturacion/api/') or _es_ajax(request):
                return JsonResponse(
                    {'status': 'error', 'message': 'Selecciona una ciudad primero.'},
                    status=403,
                )
            url = reverse('seleccionar_ciudad_facturacion')
            return redirect(f'{url}?next={request.get_full_path()}')
        request.ciudad_facturacion = ciudad

        url_name = request.resolver_match.url_name if request.resolver_match else None
        if not permisos.puede_vista(user, url_name):
            texto = f'Tu usuario no tiene acceso a {permisos.nombre_de_vista(url_name)}.'
            if request.path.startswith('/facturacion/api/') or _es_ajax(request):
                return JsonResponse({'status': 'error', 'message': texto}, status=403)
            messages.error(request, texto)
            return redirect(permisos.url_inicio(user))
        return view_func(request, *args, **kwargs)
    return wrapper


def _porcentaje_iva():
    """(% del impuesto 'IVA' activo, True) o (0, False) si no hay. Con varios del mismo nombre, el más antiguo."""
    imp = Impuesto.objects.filter(nombre__iexact='IVA', activo=True).order_by('pk').first()
    return (imp.porcentaje, True) if imp else (Decimal('0'), False)


def _json_error(mensaje, status=400):
    return JsonResponse({'status': 'error', 'message': mensaje}, status=status)


# ═══════════════════════════════════════════════════════════════════════════════
# SELECCIÓN DE CIUDAD (SEDE)
# ═══════════════════════════════════════════════════════════════════════════════

@staff_sin_ciudad
def seleccionar_ciudad(request):
    """
    Puerta de entrada del módulo: elegir la ciudad con la que se trabaja.
    Se vuelve a pasar por aquí cada vez que se entra desde el portal o al
    pulsar "Cambiar" en el sidebar.
    """
    ciudades = permisos.ciudades_de(request.user)
    siguiente = request.POST.get('next') or request.GET.get('next') or ''
    if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        siguiente = ''

    unica = permisos.ciudad_unica(request.user)
    if unica:
        # Usuario de Facturación con una sola ciudad: no hay nada que elegir
        sede.fijar_ciudad(request, unica)
        return redirect(siguiente or permisos.url_inicio(request.user))

    if request.method == 'POST':
        ciudad = (request.POST.get('ciudad') or '').strip()
        if ciudad not in ciudades:
            messages.error(request, 'Selecciona una ciudad válida.')
        else:
            sede.fijar_ciudad(request, ciudad)
            return redirect(siguiente or permisos.url_inicio(request.user))

    conteo = {
        fila['ciudad']: fila['n']
        for fila in Constructora.objects.exclude(ciudad__isnull=True).exclude(ciudad='')
        .values('ciudad').annotate(n=Count('id'))
    }
    context = {
        'ciudades': [(c, conteo.get(c, 0)) for c in ciudades],
        'ciudad_actual': sede.ciudad_actual(request),
        'sin_ciudad': (0 if permisos.es_restringido(request.user)
                       else Constructora.objects.filter(Q(ciudad__isnull=True) | Q(ciudad='')).count()),
        'next': siguiente,
    }
    return render(request, 'facturacion/seleccionar_ciudad.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def dashboard_facturacion(request):
    """Panel de facturación de la sede activa: el mes, lo que falta facturar y cobrar, y la tendencia."""
    from datetime import date

    hoy = timezone.localdate()
    ciudad = request.ciudad_facturacion
    inicio_mes = hoy.replace(day=1)
    inicio_mes_ant = (inicio_mes - timezone.timedelta(days=1)).replace(day=1)
    facturas = sede.facturas_de(ciudad).exclude(estado='ANULADA')

    # El mes: lo facturado frente al mismo tramo del mes anterior (día 1 → día de hoy)
    mes = facturas.filter(fecha_emision__gte=inicio_mes).aggregate(n=Count('pk'), total=Sum('total'))
    dia_equiv = min(hoy.day, (inicio_mes - timezone.timedelta(days=1)).day)
    mes_ant = facturas.filter(fecha_emision__gte=inicio_mes_ant,
                              fecha_emision__lte=inicio_mes_ant.replace(day=dia_equiv)).aggregate(total=Sum('total'))
    total_mes = mes['total'] or Decimal('0')
    total_ant = mes_ant['total'] or Decimal('0')
    variacion = round((total_mes - total_ant) * 100 / total_ant) if total_ant else None

    # Por cobrar: facturas emitidas sin pagar
    por_cobrar = facturas.filter(estado='PENDIENTE').aggregate(n=Count('pk'), total=Sum('total'))

    # Por facturar: servicios sin factura, agrupados por obra (la lista de trabajo del panel)
    pendientes = sede.registros_de(ciudad).filter(factura__isnull=True)
    por_facturar = pendientes.aggregate(n=Count('pk'), total=Sum('subtotal'))
    obras_por_facturar = list(
        pendientes.values('obra', 'obra__nombre', 'obra__codigo_obra', 'obra__constructora__nombre')
        .annotate(n=Count('pk'), total=Sum('subtotal'), desde=Min('fecha_realizacion'), hasta=Max('fecha_realizacion'),
                  aplazados=Count('pk', filter=Q(facturar_despues=True)))
        .order_by('-total')[:8]
    )
    for o in obras_por_facturar:
        o['url'] = (reverse('generar_factura') + f"?obra={o['obra']}&fecha_inicio={o['desde']:%Y-%m-%d}"
                    f"&fecha_fin={o['hasta']:%Y-%m-%d}")
        o['dias'] = (hoy - o['desde']).days

    # Tendencia: 12 meses, incluidos los meses sin facturas (la barra queda en cero, no desaparece)
    meses = []
    a, m = inicio_mes.year, inicio_mes.month
    for _ in range(12):
        meses.append(date(a, m, 1))
        a, m = (a - 1, 12) if m == 1 else (a, m - 1)
    meses.reverse()
    por_mes = {f['mes']: f['total'] for f in facturas.filter(fecha_emision__gte=meses[0])
               .annotate(mes=TruncMonth('fecha_emision')).values('mes').annotate(total=Sum('total'))}
    serie = [{'mes': d, 'total': por_mes.get(d) or Decimal('0'), 'actual': d == inicio_mes} for d in meses]
    pico = max([x['total'] for x in serie] + [Decimal('1')])
    for x in serie:
        x['alto'] = round(float(x['total'] * 100 / pico), 1)
        x['pico'] = x['total'] == pico and x['total'] > 0

    # Clientes: lo facturado (sin anuladas) en los últimos 12 meses
    top_clientes = list(
        facturas.filter(fecha_emision__gte=meses[0]).values('constructora', 'constructora__nombre', 'constructora__codigo')
        .annotate(total=Sum('total'), n=Count('pk')).order_by('-total')[:5]
    )
    tope = top_clientes[0]['total'] if top_clientes else 1
    for c in top_clientes:
        c['ancho'] = round(float(c['total'] * 100 / tope))

    top_servicios = (
        sede.registros_de(ciudad).filter(fecha_realizacion__gte=hoy - timezone.timedelta(days=90))
        .values('tipo_servicio__codigo', 'tipo_servicio__nombre')
        .annotate(n=Sum('cantidad'), total=Sum('subtotal')).order_by('-n')[:5]
    )

    context = {
        'hoy': hoy,
        'total_mes': total_mes,
        'facturas_mes': mes['n'],
        'variacion': variacion,
        'por_cobrar_total': por_cobrar['total'] or Decimal('0'),
        'por_cobrar_n': por_cobrar['n'],
        'por_facturar_total': por_facturar['total'] or Decimal('0'),
        'por_facturar_n': por_facturar['n'],
        'obras_por_facturar': obras_por_facturar,
        'serie': serie,
        'total_12m': sum(x['total'] for x in serie),
        'top_clientes': top_clientes,
        'top_servicios': top_servicios,
        'ultimas_facturas': sede.facturas_de(ciudad).select_related('obra', 'constructora').order_by('-fecha_emision', '-pk')[:6],
        'total_constructoras': sede.constructoras_de(ciudad).count(),
        'total_obras': sede.obras_de(ciudad).count(),
    }
    return render(request, 'facturacion/dashboard.html', context)

@staff_required
def api_facturacion_mensual(request):
    """API: facturación mensual últimos 6 meses para Chart.js."""
    hoy = timezone.now().date()
    hace_6_meses = hoy.replace(day=1) - timezone.timedelta(days=180)

    datos = sede.facturas_de(request.ciudad_facturacion).filter(
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
    """Lista de servicios agrupados por categoría (catálogo de la ciudad activa)."""
    from django.db.models import OuterRef, Prefetch, Subquery
    from django.db.models.functions import Coalesce

    ciudad = request.ciudad_facturacion
    # Uso de cada servicio, con subconsultas (Count sobre dos joins se multiplicaría):
    # en cuántas obras tiene precio y cuántas veces se ha registrado (con registros no se puede eliminar).
    def _contar(modelo, **filtro):
        return Coalesce(Subquery(
            modelo.objects.filter(tipo_servicio=OuterRef('pk'), **filtro)
            .values('tipo_servicio').annotate(n=Count('pk')).values('n')
        ), 0)
    servicios = TipoServicio.objects.annotate(
        n_obras=_contar(PrecioServicio, precio__isnull=False),
        n_registros=_contar(RegistroServicio),
    ).order_by('clave_orden')
    categorias = list(sede.categorias_de(ciudad).prefetch_related(Prefetch('servicios', queryset=servicios)))
    total_servicios = sum(len(c.servicios.all()) for c in categorias)

    context = {
        'categorias': categorias,
        'total_servicios': total_servicios,
        'q': request.GET.get('q', '').strip(),   # la búsqueda filtra en la página, al instante
    }
    return render(request, 'facturacion/catalogo_servicios.html', context)


@staff_required
def crear_categoria(request):
    """Crear nueva categoría de servicio (en la ciudad activa)."""
    ciudad = request.ciudad_facturacion
    if request.method == 'POST':
        form = CategoriaServicioForm(request.POST, ciudad=ciudad)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría creada exitosamente.')
            return redirect('catalogo_servicios')
    else:
        form = CategoriaServicioForm(ciudad=ciudad)
    return render(request, 'facturacion/categoria_form.html', {
        'form': form, 'titulo': 'Nueva Categoría'
    })


@staff_required
def editar_categoria(request, pk):
    """Editar categoría existente."""
    categoria = get_object_or_404(sede.categorias_de(request.ciudad_facturacion), pk=pk)
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
    """Crear nuevo tipo de servicio (en la ciudad activa)."""
    ciudad = request.ciudad_facturacion
    if request.method == 'POST':
        form = TipoServicioForm(request.POST, ciudad=ciudad)
        if form.is_valid():
            form.save()
            messages.success(request, 'Servicio creado exitosamente.')
            return redirect('catalogo_servicios')
    else:
        form = TipoServicioForm(ciudad=ciudad)
    return render(request, 'facturacion/servicio_form.html', {
        'form': form, 'titulo': 'Nuevo Servicio'
    })


@staff_required
def editar_servicio(request, pk):
    """Editar tipo de servicio existente."""
    servicio = get_object_or_404(sede.servicios_de(request.ciudad_facturacion), pk=pk)
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
    servicio = get_object_or_404(sede.servicios_de(request.ciudad_facturacion), pk=pk)
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
def precios_obras(request):
    """
    Listado de obras para entrar a su lista de precios.
    Es la puerta de entrada del modulo a gestionar_precios_obra.
    """
    from django.db.models import OuterRef, Subquery
    from core.models import Informe
    from core.views import _orden_natural

    ciudad = request.ciudad_facturacion
    # Subconsultas (no Count/Max sobre joins: precios x informes se multiplicarían)
    n_precios = (PrecioServicio.objects.filter(obra=OuterRef('pk'), precio__isnull=False)
                 .values('obra').annotate(n=Count('pk')).values('n'))
    ultimo = (Informe.objects.filter(obra=OuterRef('pk'), fecha_creacion__isnull=False)
              .order_by('-fecha_creacion').values('fecha_creacion')[:1])
    obras = sede.obras_de(ciudad).select_related('constructora').annotate(
        n_precios=Subquery(n_precios), ultimo_informe=Subquery(ultimo),
    )

    ahora = timezone.now()
    grupos, por_empresa = [], {}
    resumen = {'con': 0, 'atender': 0, 'sin': 0}
    for obra in obras:
        obra.n_precios = obra.n_precios or 0
        dias = (ahora - obra.ultimo_informe).days if obra.ultimo_informe else None
        obra.dias_informe = dias
        obra.hace = _hace(dias)
        if obra.n_precios:
            obra.estado = 'con'
        elif dias is not None and dias <= DIAS_OBRA_ACTIVA:
            obra.estado = 'atender'          # recibe informes y no tiene lista: no se le puede facturar
        else:
            obra.estado = 'sin'
        resumen[obra.estado] += 1
        c = obra.constructora
        if c.pk not in por_empresa:
            por_empresa[c.pk] = {'constructora': c, 'obras': []}
            grupos.append(por_empresa[c.pk])
        por_empresa[c.pk]['obras'].append(obra)

    for g in grupos:
        g['obras'].sort(key=lambda o: _orden_natural(o.codigo_obra))
        g['con_lista'] = sum(1 for o in g['obras'] if o.estado == 'con')
        g['por_atender'] = sum(1 for o in g['obras'] if o.estado == 'atender')
    grupos.sort(key=lambda g: _orden_natural(g['constructora'].codigo))

    total = sum(resumen.values())
    tramos = [
        {'clave': 'con', 'nombre': 'Con lista de precios', 'n': resumen['con']},
        {'clave': 'atender', 'nombre': 'Activas sin lista', 'n': resumen['atender']},
        {'clave': 'sin', 'nombre': 'Sin lista, sin actividad reciente', 'n': resumen['sin']},
    ]
    for t in tramos:
        t['pct'] = round(100 * t['n'] / total, 2) if total else 0

    context = {
        'grupos': grupos,
        'tramos': tramos,
        'resumen': resumen,
        'total_obras': total,
        'total_servicios': sede.servicios_de(ciudad).count(),
        'dias_activa': DIAS_OBRA_ACTIVA,
        'query': request.GET.get('q', '').strip(),
        'estado_inicial': request.GET.get('estado', '') if request.GET.get('estado') in resumen else '',
    }
    return render(request, 'facturacion/precios_obras.html', context)


def _hace(dias):
    """Antigüedad del último informe en palabras: 'hoy', 'hace 3 días', 'hace 4 meses'."""
    if dias is None:
        return 'Sin informes'
    if dias < 1:
        return 'Hoy'
    if dias < 2:
        return 'Ayer'
    if dias < 45:
        return f'Hace {dias} días'
    if dias < 365:
        return f'Hace {round(dias / 30)} meses'
    anios = round(dias / 365)
    return 'Hace 1 año' if anios == 1 else f'Hace {anios} años'


# Una obra sin lista de precios que recibió informes en este plazo está trabajando:
# es la que hay que configurar primero (mismo umbral que el punto "media" del directorio).
DIAS_OBRA_ACTIVA = 180


@staff_required
def gestionar_precios_obra(request, obra_pk):
    """
    Gestionar lista de precios de una obra.
    Crea PrecioServicio para cada TipoServicio que no exista.
    """
    obra = get_object_or_404(
        sede.obras_de(request.ciudad_facturacion).select_related('constructora'), pk=obra_pk
    )

    # Asegurar que exista un PrecioServicio para cada TipoServicio
    servicios_existentes = set(
        PrecioServicio.objects.filter(obra=obra).values_list('tipo_servicio_id', flat=True)
    )
    todos_servicios = sede.servicios_de(request.ciudad_facturacion)

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
    ).order_by('tipo_servicio__categoria__clave_orden', 'tipo_servicio__clave_orden')

    # Cada precio se guarda solo, desde su fila (guardar_precio_obra); esta vista solo muestra.
    precios_por_categoria = {}
    con_precio = 0
    for precio in precios:
        precio.texto = _texto_precio(precio.precio)
        precio.valor = _valor_precio(precio.precio)
        con_precio += precio.precio is not None
        cat = precio.tipo_servicio.categoria
        grupo = precios_por_categoria.setdefault(cat.pk, {'categoria': cat, 'items': [], 'con_precio': 0})
        grupo['items'].append(precio)
        grupo['con_precio'] += precio.precio is not None

    context = {
        'obra': obra,
        'precios_por_categoria': precios_por_categoria.values(),
        'con_precio': con_precio,
        'total_servicios': len(precios),
    }
    return render(request, 'facturacion/gestionar_precios.html', context)


# Límites de PrecioServicio.precio (max_digits=12, decimal_places=2)
_PRECIO_MAXIMO = Decimal('9999999999.99')


def _valor_precio(valor):
    """Decimal -> texto canónico para el navegador ('18500.00'); None -> ''."""
    return '' if valor is None else f'{valor:.2f}'


def _texto_precio(valor):
    """Decimal -> texto con miles a la colombiana: 18500 -> '18.500', 6750.5 -> '6.750,50'."""
    from .formato import texto_precio
    return texto_precio(valor)


def _leer_precio(dato):
    """
    Valor que manda el navegador -> (Decimal | None, error | None).
    Llega canónico ('18500', '6750.5') o null/'' para quitar el precio. Se rechaza todo lo
    demás en vez de adivinar: '18.500' con punto de miles NO se interpreta (el navegador
    ya lo convierte), así un error del lado del cliente no guarda 18,5 en lugar de 18.500.
    """
    from decimal import InvalidOperation
    if dato is None or (isinstance(dato, str) and not dato.strip()):
        return None, None
    if isinstance(dato, bool) or not isinstance(dato, (str, int)):
        return None, 'El precio debe enviarse como texto.'
    texto = str(dato).strip()
    if not re.fullmatch(r'\d{1,10}(\.\d{1,2})?', texto):
        return None, 'Precio no válido: use solo números, con hasta 2 decimales.'
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None, 'Precio no válido.'
    if valor > _PRECIO_MAXIMO:
        return None, 'El precio es demasiado alto.'
    return valor.quantize(Decimal('0.01')), None


@require_POST
@staff_required
def guardar_precio_obra(request, obra_pk, precio_pk):
    """
    Guarda UN precio de la lista de una obra (el chulito de la fila). JSON:
        {"precio": "18500" | null, "anterior": "18500.00" | ""}
    `anterior` es lo que la pantalla creía guardado: si en la base hay otra cosa (otra
    persona lo cambió mientras tanto) no se sobrescribe y se responde 409 con el valor actual.
    """
    obra = get_object_or_404(sede.obras_de(request.ciudad_facturacion), pk=obra_pk)
    try:
        datos = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Solicitud mal formada.'}, status=400)
    if not isinstance(datos, dict) or 'precio' not in datos or 'anterior' not in datos:
        return JsonResponse({'status': 'error', 'message': 'Solicitud mal formada.'}, status=400)

    nuevo, error = _leer_precio(datos['precio'])
    if error:
        return JsonResponse({'status': 'error', 'message': error}, status=400)
    anterior, error = _leer_precio(datos['anterior'])
    if error:
        return JsonResponse({'status': 'error', 'message': 'Solicitud mal formada.'}, status=400)

    with transaction.atomic():
        try:
            precio = PrecioServicio.objects.select_for_update().get(pk=precio_pk, obra=obra)
        except PrecioServicio.DoesNotExist:
            raise Http404('Ese servicio no está en la lista de esta obra.')
        if precio.precio != anterior:
            return JsonResponse({
                'status': 'conflicto',
                'message': 'Otra persona cambió este precio mientras tanto. Revise el valor actual y vuelva a guardar.',
                'valor': _valor_precio(precio.precio), 'texto': _texto_precio(precio.precio),
            }, status=409)
        if precio.precio != nuevo:
            precio.precio = nuevo
            precio.save(update_fields=['precio'])

    con_precio = PrecioServicio.objects.filter(obra=obra, precio__isnull=False).count()
    return JsonResponse({
        'status': 'ok',
        'valor': _valor_precio(precio.precio), 'texto': _texto_precio(precio.precio),
        'con_precio': con_precio,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# IMPUESTOS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def lista_impuestos(request):
    """Lista y gestión de impuestos (globales: valen para todas las sedes)."""
    impuestos = Impuesto.objects.order_by('-activo', 'nombre', 'pk')
    # El que usa generar_factura: el "IVA" activo más antiguo (mismo criterio que _porcentaje_iva)
    iva = Impuesto.objects.filter(nombre__iexact='IVA', activo=True).order_by('pk').first()
    return render(request, 'facturacion/lista_impuestos.html', {
        'impuestos': impuestos,
        'iva_en_uso': iva,
        'ivas_activos': Impuesto.objects.filter(nombre__iexact='IVA', activo=True).count(),
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
    POST (AJAX JSON): creación de varios registros, todos o ninguno.
    `envio_id` identifica el envío: si la respuesta se perdió y el usuario
    reintenta, no se vuelven a crear.
    """
    ciudad = request.ciudad_facturacion
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return _json_error('JSON inválido.')

        obra_id = data.get('obra_id')
        fecha_str = data.get('fecha_realizacion')
        servicios = data.get('servicios', [])
        try:
            envio_id = uuid.UUID(str(data.get('envio_id'))) if data.get('envio_id') else None
        except ValueError:
            envio_id = None

        if not obra_id or not fecha_str or not servicios:
            return _json_error('Faltan datos requeridos (obra, fecha, servicios).')

        # Reintento de un envío que ya quedó guardado (se perdió la respuesta): no se duplica
        if envio_id:
            previos = sede.registros_de(ciudad).filter(envio_id=envio_id).count()
            if previos:
                return JsonResponse({
                    'status': 'success', 'repetido': True,
                    'message': f'Estos {previos} registro(s) ya se habían guardado en el envío anterior; no se crearon de nuevo.',
                })

        fecha = parse_date(str(fecha_str))
        if fecha is None:
            return _json_error('La fecha de realización no es válida.')
        if fecha > timezone.localdate():
            return _json_error('La fecha de realización no puede ser futura.')

        try:
            obra = sede.obras_de(ciudad).get(pk=obra_id)
        except (Obra.DoesNotExist, ValueError):
            return _json_error('Obra no encontrada.', status=404)

        errores = []
        nuevos = []
        for i, srv in enumerate(servicios, 1):
            tipo_id = srv.get('tipo_servicio_id')
            num_informe = (srv.get('numero_informe') or '').strip()
            try:
                cantidad = int(srv.get('cantidad', 1))
            except (TypeError, ValueError):
                cantidad = 0
            if not tipo_id or not num_informe:
                errores.append(f'Línea {i}: faltan datos.')
                continue
            if cantidad < 1:
                errores.append(f'Línea {i}: la cantidad debe ser 1 o más.')
                continue
            try:
                tipo_servicio = sede.servicios_de(ciudad).get(pk=tipo_id)
            except (TipoServicio.DoesNotExist, ValueError):
                errores.append(f'Línea {i}: servicio no encontrado.')
                continue
            precio = PrecioServicio.objects.filter(
                obra=obra, tipo_servicio=tipo_servicio
            ).values_list('precio', flat=True).first()
            if precio is None:
                errores.append(
                    f'Línea {i}: {tipo_servicio.codigo} no tiene precio configurado para esta obra.'
                )
                continue
            nuevos.append(RegistroServicio(
                obra=obra, tipo_servicio=tipo_servicio, fecha_realizacion=fecha,
                cantidad=cantidad, numero_informe=num_informe,
                precio_unitario_congelado=precio, creado_por=request.user, envio_id=envio_id,
            ))

        # Todos o ninguno: guardar solo las líneas buenas obligaba a reenviar y duplicaba
        if errores:
            return _json_error('No se guardó ningún registro. ' + ' | '.join(errores))

        try:
            with transaction.atomic():
                for r in nuevos:
                    r.save()
        except Exception as e:
            logger.exception(f"Error creando registros: {e}")
            return _json_error('Error interno al crear registros.', status=500)

        return JsonResponse({
            'status': 'success',
            'message': f'{len(nuevos)} registro(s) creado(s) exitosamente.',
        })

    # GET: renderizar formulario
    constructoras = sede.constructoras_de(ciudad).order_by('nombre')
    servicios = sede.servicios_de(ciudad).select_related('categoria').order_by(
        'categoria__clave_orden', 'clave_orden'
    )

    context = {
        'constructoras': constructoras,
        'servicios': servicios,
        # Para el JavaScript vía json_script: nombres con comillas o pulgadas (4") no rompen el script
        'servicios_json': [
            {'id': s.pk, 'codigo': s.codigo, 'nombre': s.nombre, 'categoria': s.categoria.nombre}
            for s in servicios
        ],
        'fecha_hoy': timezone.localdate().isoformat(),
    }
    return render(request, 'facturacion/crear_registro.html', context)


@staff_required
def editar_registro(request, pk):
    """
    Editar registro no facturado.
    El precio congelado se conserva; solo se vuelve a tomar de la lista de la
    obra si cambia la obra o el servicio, y si no hay precio no se guarda.
    """
    ciudad = request.ciudad_facturacion
    registro = get_object_or_404(sede.registros_de(ciudad), pk=pk)

    if registro.esta_facturado:
        messages.error(request, 'No se puede editar un registro ya facturado.')
        return redirect('historico_facturacion')

    if request.method == 'POST':
        form = RegistroServicioForm(request.POST, instance=registro, ciudad=ciudad)
        if form.is_valid():
            registro = form.save(commit=False)
            if 'obra' in form.changed_data or 'tipo_servicio' in form.changed_data:
                precio = PrecioServicio.objects.filter(
                    obra=registro.obra, tipo_servicio=registro.tipo_servicio
                ).values_list('precio', flat=True).first()
                if precio is None:
                    form.add_error(None, (
                        f'{registro.tipo_servicio.codigo} no tiene precio en {registro.obra.nombre}: '
                        'configúralo en Precios por obra antes de mover el registro.'
                    ))
                else:
                    registro.precio_unitario_congelado = precio
            if form.is_valid():
                with transaction.atomic():
                    # Si alguien lo facturó mientras se editaba, no se toca
                    bloqueado = RegistroServicio.objects.select_for_update(of=('self',)).get(pk=pk)
                    if bloqueado.factura_id:
                        messages.error(request, 'Este registro se facturó mientras lo editabas; no se guardaron los cambios.')
                        return redirect('historico_facturacion')
                    registro.save()
                messages.success(request, 'Registro actualizado correctamente.')
                return redirect('historico_facturacion')
    else:
        form = RegistroServicioForm(instance=registro, ciudad=ciudad)

    return render(request, 'facturacion/registro_editar.html', {
        'form': form, 'registro': registro,
    })


@staff_required
@require_POST
def eliminar_registro(request, pk):
    """Eliminar registro no facturado (con la fila bloqueada: no se borra lo que se está facturando)."""
    with transaction.atomic():
        registro = get_object_or_404(
            sede.registros_de(request.ciudad_facturacion).select_for_update(of=('self',)), pk=pk
        )
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
    ciudad = request.ciudad_facturacion
    registros = sede.registros_de(ciudad).select_related(
        'obra', 'obra__constructora', 'tipo_servicio',
        'tipo_servicio__categoria', 'factura',
    )

    form = FiltroHistoricoForm(request.GET or None, ciudad=ciudad)

    # Aplicar filtros (un id o una fecha mal escritos en la URL se ignoran, no dan error 500)
    for param, campo in (('constructora', 'obra__constructora_id'), ('obra', 'obra_id'),
                         ('tipo_servicio', 'tipo_servicio_id')):
        valor = request.GET.get(param, '')
        if valor.isdigit():
            registros = registros.filter(**{campo: int(valor)})
    for param, campo in (('fecha_inicio', 'fecha_realizacion__gte'), ('fecha_fin', 'fecha_realizacion__lte')):
        try:
            fecha = parse_date(request.GET.get(param) or '')
        except ValueError:
            fecha = None
        if fecha:
            registros = registros.filter(**{campo: fecha})

    from django.db.models import DecimalField, ExpressionWrapper
    importe = ExpressionWrapper(F('cantidad') * F('precio_unitario_congelado'),
                                output_field=DecimalField(max_digits=16, decimal_places=2))
    totales = registros.aggregate(
        total=Sum(importe),
        pendiente=Sum(importe, filter=Q(factura__isnull=True)),
        n_pendientes=Count('pk', filter=Q(factura__isnull=True)),
    )

    # Paginación: los enlaces conservan los filtros
    paginator = Paginator(registros, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    filtros = request.GET.copy()
    filtros.pop('page', None)

    context = {
        'page_obj': page_obj,
        'form': form,
        'total_registros': paginator.count,
        'totales': totales,
        'filtros_qs': filtros.urlencode(),
        'hay_filtros': any(v for k, v in request.GET.items() if k != 'page'),
    }
    return render(request, 'facturacion/historico.html', context)


# ═══════════════════════════════════════════════════════════════════════════════
# GENERACIÓN DE FACTURAS
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def generar_factura(request):
    """
    Preview de factura.
    Muestra registros pendientes separados en normales y transporte. Los ids
    de lo que se muestra viajan en el formulario: la factura se hace sobre
    exactamente esos registros.
    """
    ciudad = request.ciudad_facturacion
    form = GenerarFacturaForm(request.GET or None, ciudad=ciudad)
    registros_normales = []
    registros_transporte = []
    subtotal_normales = Decimal('0')
    subtotal_transporte = Decimal('0')
    iva_porcentaje, hay_iva = Decimal('0'), True
    obra = None
    tiene_registros = False

    if request.GET.get('obra') and request.GET.get('fecha_inicio') and request.GET.get('fecha_fin'):
        obra_id = request.GET.get('obra')
        fecha_inicio = parse_date(request.GET.get('fecha_inicio'))
        fecha_fin = parse_date(request.GET.get('fecha_fin'))
        if not fecha_inicio or not fecha_fin or fecha_inicio > fecha_fin:
            messages.error(request, 'El periodo no es válido: revisa las fechas.')
            return render(request, 'facturacion/generar_factura.html', {'form': form})

        try:
            obra = sede.obras_de(ciudad).select_related('constructora').get(pk=obra_id)
        except (Obra.DoesNotExist, ValueError):
            messages.error(request, 'Obra no encontrada.')
            return render(request, 'facturacion/generar_factura.html', {'form': form})

        # Obtener registros pendientes en el periodo
        registros = RegistroServicio.objects.filter(
            obra=obra,
            fecha_realizacion__range=(fecha_inicio, fecha_fin),
            factura__isnull=True,
        ).select_related(
            'tipo_servicio', 'tipo_servicio__categoria'
        ).order_by('fecha_realizacion', 'tipo_servicio__clave_orden')

        for r in registros:
            if r.es_transporte:
                registros_transporte.append(r)
                subtotal_transporte += r.subtotal
            else:
                registros_normales.append(r)
                subtotal_normales += r.subtotal

        tiene_registros = len(registros_normales) > 0 or len(registros_transporte) > 0
        iva_porcentaje, hay_iva = _porcentaje_iva()
        periodo = (fecha_inicio, fecha_fin)
    else:
        periodo = None

    context = {
        'form': form,
        'obra': obra,
        'periodo': periodo,
        'registros_normales': registros_normales,
        'registros_transporte': registros_transporte,
        'subtotal_normales': subtotal_normales,
        'subtotal_transporte': subtotal_transporte,
        'subtotal_total': subtotal_normales + subtotal_transporte,
        'iva_porcentaje': iva_porcentaje,
        'hay_iva': hay_iva,
        'tiene_registros': tiene_registros,
        # Recién generada por quien no tiene el repositorio: el aviso trae el enlace al PDF
        'generada': (sede.facturas_de(ciudad).filter(pk=request.GET['generada']).first()
                     if request.GET.get('generada', '').isdigit() else None),
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

    Se factura exactamente lo que se vio en la vista previa (`registro_ids`),
    con las filas bloqueadas: si cambiaron, o si ya se facturaron (doble
    envío), no se crea nada y se avisa.
    """
    obra_id = request.POST.get('obra_id')
    fecha_inicio = parse_date(request.POST.get('fecha_inicio') or '')
    fecha_fin = parse_date(request.POST.get('fecha_fin') or '')
    ids_transporte_con_iva = set(request.POST.getlist('transporte_con_iva'))
    ids_vistos = {int(x) for x in request.POST.getlist('registro_ids') if x.isdigit()}

    if not obra_id or not fecha_inicio or not fecha_fin or fecha_inicio > fecha_fin:
        messages.error(request, 'Datos incompletos.')
        return redirect('generar_factura')
    if not ids_vistos:
        messages.error(request, 'La vista previa no trajo servicios. Vuelve a generarla.')
        return redirect('generar_factura')

    obra = get_object_or_404(
        sede.obras_de(request.ciudad_facturacion).select_related('constructora'), pk=obra_id
    )
    volver_a_previa = (reverse('generar_factura')
                       + f'?obra={obra.pk}&fecha_inicio={fecha_inicio:%Y-%m-%d}&fecha_fin={fecha_fin:%Y-%m-%d}')

    try:
        with transaction.atomic():
            registros_a_facturar = list(
                RegistroServicio.objects.select_for_update(of=('self',)).filter(
                    obra=obra,
                    fecha_realizacion__range=(fecha_inicio, fecha_fin),
                    factura__isnull=True,
                ).select_related('tipo_servicio__categoria')
            )
            actuales = {r.pk for r in registros_a_facturar}

            if actuales != ids_vistos:
                ya = (Factura.objects.filter(registros__pk__in=ids_vistos)
                      .exclude(estado='ANULADA').distinct().first())
                if ya and not actuales:
                    # Doble clic o doble pestaña: la factura ya existe, no se crea otra
                    messages.info(request, f'La factura #{ya.pk} ya se había generado con estos servicios.')
                    return _ir_a_factura(request, ya)
                messages.error(request, (
                    'Los servicios pendientes de esta obra cambiaron desde la vista previa '
                    '(alguien registró, editó o facturó algo). Revisa la vista previa de nuevo.'
                ))
                return redirect(volver_a_previa)

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

            iva_porcentaje, _ = _porcentaje_iva()

            base_para_iva = base_iva_normales + base_iva_transporte
            monto_iva = base_para_iva * (iva_porcentaje / 100)
            total = subtotal_completo + monto_iva

            # Crear factura
            factura = Factura.objects.create(
                constructora=obra.constructora,
                obra=obra,
                fecha_inicio_periodo=fecha_inicio,
                fecha_fin_periodo=fecha_fin,
                fecha_emision=timezone.localdate(),
                subtotal=subtotal_completo,
                monto_iva=monto_iva.quantize(Decimal('0.01')),
                total=total.quantize(Decimal('0.01')),
                iva_transporte_facturado=any(
                    r.es_transporte and str(r.pk) in ids_transporte_con_iva for r in registros_a_facturar
                ),
                emitida_por=request.user,
            )

            # Vincular registros (solo los bloqueados)
            RegistroServicio.objects.filter(pk__in=actuales).update(factura=factura)

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
        return _ir_a_factura(request, factura)

    except Exception as e:
        logger.exception(f"Error finalizando factura: {e}")
        messages.error(request, 'Error al generar la factura. Intente nuevamente.')
        return redirect(volver_a_previa)


def _ir_a_factura(request, factura):
    """Después de generar: al repositorio de la obra, o (sin ese permiso) a Generar con el enlace al PDF."""
    if permisos.puede_seccion(request.user, 'repositorio'):
        return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)
    return redirect(reverse('generar_factura') + f'?generada={factura.pk}')


def _generar_pdf_factura(factura, request):
    """Genera el PDF de una factura usando WeasyPrint."""
    from weasyprint import HTML

    registros = factura.registros.select_related(
        'tipo_servicio', 'tipo_servicio__categoria'
    ).order_by('tipo_servicio__categoria__clave_orden', 'fecha_realizacion')

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

def _regenerar_pdf(factura, request):
    """Vuelve a generar el PDF tras un cambio de estado, para que el archivo no diga 'Pendiente'."""
    try:
        _generar_pdf_factura(factura, request)
    except Exception as e:
        logger.exception(f"Error regenerando PDF de factura #{factura.pk}: {e}")
        messages.warning(request, 'El estado cambió, pero no se pudo actualizar el PDF.')


@staff_required
@require_POST
def anular_factura(request, pk):
    """
    Anula una factura: desvincula registros y marca como ANULADA.
    Los registros quedan disponibles para re-facturación.
    Una factura PAGADA no se anula (habría que devolverla a pendiente primero).
    """
    with transaction.atomic():
        factura = get_object_or_404(
            sede.facturas_de(request.ciudad_facturacion).select_for_update(of=('self',)), pk=pk
        )
        if factura.esta_anulada:
            messages.warning(request, 'Esta factura ya está anulada.')
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)
        if factura.estado == 'PAGADA':
            messages.error(request, (
                f'La factura #{factura.pk} está pagada y no se puede anular. '
                'Si el pago fue un error, primero devuélvela a pendiente.'
            ))
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)

        factura.registros.all().update(factura=None)
        factura.estado = 'ANULADA'
        factura.save(update_fields=['estado'])
        logger.info(f"Factura #{factura.pk} anulada por {request.user.username}")

    _regenerar_pdf(factura, request)
    messages.success(request, f'Factura #{factura.pk} anulada correctamente.')
    return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)


@staff_required
@require_POST
def marcar_factura_pagada(request, pk):
    """Marca una factura como pagada."""
    with transaction.atomic():
        factura = get_object_or_404(
            sede.facturas_de(request.ciudad_facturacion).select_for_update(of=('self',)), pk=pk
        )
        if factura.esta_anulada:
            messages.error(request, 'No se puede marcar como pagada una factura anulada.')
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)
        if factura.estado == 'PAGADA':
            messages.info(request, f'La factura #{factura.pk} ya estaba marcada como pagada.')
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)
        factura.estado = 'PAGADA'
        factura.save(update_fields=['estado'])
    _regenerar_pdf(factura, request)
    messages.success(request, f'Factura #{factura.pk} marcada como pagada.')
    return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)


@staff_required
@require_POST
def marcar_factura_pendiente(request, pk):
    """Devuelve a PENDIENTE una factura marcada como pagada por error."""
    with transaction.atomic():
        factura = get_object_or_404(
            sede.facturas_de(request.ciudad_facturacion).select_for_update(of=('self',)), pk=pk
        )
        if factura.estado != 'PAGADA':
            messages.error(request, 'Solo una factura pagada se puede devolver a pendiente.')
            return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)
        factura.estado = 'PENDIENTE'
        factura.save(update_fields=['estado'])
        logger.info(f"Factura #{factura.pk} devuelta a pendiente por {request.user.username}")
    _regenerar_pdf(factura, request)
    messages.success(request, f'Factura #{factura.pk} volvió a pendiente.')
    return redirect('repositorio_facturas_obra', obra_pk=factura.obra_id)


# ═══════════════════════════════════════════════════════════════════════════════
# REPOSITORIO DE FACTURAS (Drill-down 3 niveles)
# ═══════════════════════════════════════════════════════════════════════════════

@staff_required
def repositorio_clientes(request):
    """Nivel 1: Constructoras con facturas."""
    constructoras = sede.constructoras_de(request.ciudad_facturacion).filter(
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
    constructora = get_object_or_404(
        sede.constructoras_de(request.ciudad_facturacion), pk=constructora_pk
    )

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
    obra = get_object_or_404(
        sede.obras_de(request.ciudad_facturacion).select_related('constructora'), pk=obra_pk
    )

    facturas = Factura.objects.filter(obra=obra).order_by('-fecha_emision')

    context = {
        'obra': obra,
        'facturas': facturas,
    }
    return render(request, 'facturacion/repositorio_facturas.html', context)


@staff_required
def descargar_factura_pdf(request, pk):
    """Descarga el PDF de una factura."""
    factura = get_object_or_404(sede.facturas_de(request.ciudad_facturacion), pk=pk)

    if not factura.pdf_archivo:
        # Intentar regenerar
        try:
            _generar_pdf_factura(factura, request)
            factura.refresh_from_db()
        except Exception:
            messages.error(request, 'No se pudo generar el PDF.')
            return _ir_a_factura(request, factura)

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
    obras = sede.obras_de(request.ciudad_facturacion).filter(
        constructora_id=constructora_id
    ).values('id', 'nombre', 'codigo_obra').order_by('nombre')
    return JsonResponse({'obras': list(obras)})


@staff_required
def api_get_precio(request):
    """API: obtener precio de un servicio para una obra (de la sede activa). $0 es un precio válido."""
    obra_id = request.GET.get('obra_id')
    tipo_id = request.GET.get('tiposervicio_id')
    if not obra_id or not tipo_id:
        return JsonResponse({'precio': None})
    try:
        precio = PrecioServicio.objects.get(
            obra__in=sede.obras_de(request.ciudad_facturacion), obra_id=obra_id, tipo_servicio_id=tipo_id
        )
    except (PrecioServicio.DoesNotExist, ValueError):
        return JsonResponse({'precio': None})
    return JsonResponse({'precio': str(precio.precio) if precio.precio is not None else None})


@staff_required
def api_buscar_servicios(request):
    """API: buscar servicios por texto."""
    q = request.GET.get('q', '')
    if len(q) < 2:
        return JsonResponse({'servicios': []})
    servicios = sede.servicios_de(request.ciudad_facturacion).filter(
        Q(codigo__icontains=q) | Q(nombre__icontains=q)
    ).values('id', 'codigo', 'nombre', 'categoria__nombre')[:20]
    return JsonResponse({'servicios': list(servicios)})
