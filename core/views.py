from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Count, Q
from django.contrib import messages
from django.utils import timezone
from .forms import ConstructoraForm, ObraForm
from users.models import Constructora
from .models import Informe, Obra

@login_required
def dashboard_router(request):
    """Redirige al dashboard correcto según el tipo de usuario"""
    if request.user.es_geolab:
        # Verificar si es tecnico de laboratorio
        if request.user.es_tecnico_laboratorio:
            return redirect('dashboard_tecnico')
        # Roles confinados al SGC (coordinador y usuarios de calidad)
        if request.user.es_confinado_a_calidad:
            return redirect('explorador_calidad')
        return dashboard_staff(request)
    elif request.user.es_cliente:
        # Verificar si es remitente (nuevo rol)
        if request.user.es_remitente:
            return redirect('dashboard_remitente')
        return dashboard_client(request)
    else:
        return render(request, 'core/pending.html') # Usuario sin rol definido

@login_required
def dashboard_staff(request):
    """Vista Tipo Torre de Control para Geolab"""
    from users.models import Constructora
    from solicitudes.models import RemisionMuestras, Muestra
    from django.utils import timezone
    from datetime import timedelta

    # Estadísticas Globales
    total_empresas = Constructora.objects.count()
    total_obras = Obra.objects.count()
    total_informes = Informe.objects.count()

    # Remisiones
    remisiones_pendientes = RemisionMuestras.objects.filter(estado='enviada').count()
    remisiones_completadas = RemisionMuestras.objects.filter(estado='completada').count()

    # Ensayos programados para hoy
    hoy = timezone.now().date()
    ensayos_hoy = Muestra.objects.filter(
        remision__estado='completada',
        fecha_toma__lte=hoy
    ).annotate(
        fecha_ensayo=models.ExpressionWrapper(
            models.F('fecha_toma') + timedelta(days=1) * models.F('edad_ensayo_dias'),
            output_field=models.DateField()
        )
    ).filter(fecha_ensayo=hoy).count()

    # Últimos 8 informes cargados al sistema
    ultimos_informes = Informe.objects.select_related('obra', 'obra__constructora').order_by('-fecha_creacion')[:8]

    # Últimas 5 remisiones
    ultimas_remisiones = RemisionMuestras.objects.select_related('obra', 'obra__constructora').order_by('-fecha_creacion')[:5]

    # Obras con más actividad reciente (últimos 30 días)
    hace_30_dias = timezone.now() - timedelta(days=30)
    obras_activas = Obra.objects.annotate(
        informes_recientes=Count('informes', filter=Q(informes__fecha_creacion__gte=hace_30_dias)),
        remisiones_recientes=Count('remisiones', filter=Q(remisiones__fecha_creacion__gte=hace_30_dias))
    ).filter(
        Q(informes_recientes__gt=0) | Q(remisiones_recientes__gt=0)
    ).order_by('-informes_recientes', '-remisiones_recientes')[:5]

    context = {
        'total_empresas': total_empresas,
        'total_obras': total_obras,
        'total_informes': total_informes,
        'remisiones_pendientes': remisiones_pendientes,
        'remisiones_completadas': remisiones_completadas,
        'ensayos_hoy': ensayos_hoy,
        'ultimos_informes': ultimos_informes,
        'ultimas_remisiones': ultimas_remisiones,
        'obras_activas': obras_activas,
    }
    return render(request, 'core/home_staff.html', context)

@login_required
def dashboard_client(request):
    """
    Dashboard principal para clientes.
    Muestra tarjetas de obras disponibles y últimos informes.
    """
    perfil = request.user.perfil_cliente

    # 1. FILTRADO DE SEGURIDAD - Obras según rol
    if perfil.rol == 'director':
        # Director ve todas las obras de su empresa
        obras = Obra.objects.filter(constructora=perfil.empresa)
        informes = Informe.objects.filter(obra__constructora=perfil.empresa)
    else:
        # Residente ve solo sus obras asignadas
        obras = perfil.obras_asignadas.all()
        informes = Informe.objects.filter(obra__in=obras)

    # 2. Anotar conteo de informes por obra
    obras = obras.annotate(num_informes=Count('informes')).order_by('nombre')

    # 3. Últimos 5 informes para vista rápida
    ultimos_informes = informes.select_related('obra').order_by('-fecha_creacion')[:5]

    # 4. Total de informes disponibles
    total_informes = informes.count()

    context = {
        'perfil': perfil,
        'mis_obras': obras,
        'ultimos_informes': ultimos_informes,
        'total_informes': total_informes,
    }
    return render(request, 'core/home_client.html', context)


@login_required
def informes_obra_cliente(request, pk):
    """
    Lista de informes de una obra específica para clientes.
    Incluye búsqueda, filtros por fecha y ordenamiento.
    """
    obra = get_object_or_404(Obra, pk=pk)

    # Verificar permisos del cliente
    if not request.user.es_cliente:
        return redirect('home')

    perfil = request.user.perfil_cliente

    # Verificar acceso según rol
    if perfil.rol == 'director':
        if obra.constructora != perfil.empresa:
            messages.error(request, 'No tienes acceso a esta obra.')
            return redirect('home')
    else:
        if obra not in perfil.obras_asignadas.all():
            messages.error(request, 'No tienes acceso a esta obra.')
            return redirect('home')

    # Obtener informes de la obra
    informes = Informe.objects.filter(obra=obra)

    # Filtro de búsqueda
    query = request.GET.get('q', '')
    if query:
        informes = informes.filter(titulo__icontains=query)

    # Filtro de fecha desde
    fecha_desde = request.GET.get('fecha_desde', '')
    if fecha_desde:
        informes = informes.filter(fecha_creacion__date__gte=fecha_desde)

    # Filtro de fecha hasta
    fecha_hasta = request.GET.get('fecha_hasta', '')
    if fecha_hasta:
        informes = informes.filter(fecha_creacion__date__lte=fecha_hasta)

    # Ordenamiento (más reciente o más antiguo)
    orden = request.GET.get('orden', 'reciente')
    if orden == 'antiguo':
        informes = informes.order_by('fecha_creacion')
    else:
        informes = informes.order_by('-fecha_creacion')

    # Paginación (15 por página)
    paginator = Paginator(informes, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'obra': obra,
        'page_obj': page_obj,
        'query': query,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'orden': orden,
        'total_informes': obra.informes.count(),
        'perfil': perfil,
    }
    return render(request, 'core/informes_obra_cliente.html', context)




@login_required
def lista_constructoras(request):
    """
    NIVEL 1: Directorio de todas las Empresas con Filtros Funcionales
    """
    # Seguridad: Solo staff de Geolab debe ver esto
    if not request.user.es_geolab:
        return redirect('home')

    # 1. QUERYSET BASE
    # Traemos las empresas y les pegamos el conteo de obras y usuarios
    queryset = Constructora.objects.annotate(
        num_obras=Count('obras'),
        num_usuarios=Count('usuarios')
    ).order_by('nombre')

    # 2. OBTENER LISTA DE CIUDADES (Para llenar el Select)
    # Buscamos todas las ciudades únicas, quitando las vacías o nulas
    ciudades_disponibles = Constructora.objects.exclude(ciudad__isnull=True).exclude(ciudad='').values_list('ciudad', flat=True).distinct().order_by('ciudad')

    # 3. RECIBIR PARÁMETROS DEL GET (Lo que viene del formulario)
    q = request.GET.get('q')           # Texto del buscador
    ciudad_filtro = request.GET.get('ciudad') # Ciudad seleccionada

    # 4. APLICAR FILTROS (Si existen)
    
    # Filtro de Texto (Búsqueda)
    if q:
        queryset = queryset.filter(
            Q(nombre__icontains=q) |   # Busca en Nombre...
            Q(codigo__icontains=q) |   # O en Código...
            Q(nit__icontains=q)        # O en NIT
        )
    
    # Filtro de Ciudad
    if ciudad_filtro:
        queryset = queryset.filter(ciudad=ciudad_filtro)

    # 5. ENVIAR AL TEMPLATE
    context = {
        'constructoras': queryset,
        'ciudades': ciudades_disponibles,
        # Pasamos los valores actuales para que el formulario no se resetee al filtrar
        'q_actual': q if q else '',
        'ciudad_actual': ciudad_filtro if ciudad_filtro else ''
    }
    return render(request, 'core/lista_constructoras.html', context)

@login_required
def detalle_constructora(request, pk):
    """NIVEL 2: Expediente de la Empresa (Lista de Obras)"""
    empresa = get_object_or_404(Constructora, pk=pk)
    
    # Validamos permiso: Solo Staff o el Director de esa empresa pueden ver esto
    es_director_propio = request.user.es_cliente and request.user.perfil_cliente.empresa == empresa and request.user.perfil_cliente.rol == 'director'
    
    if not (request.user.es_geolab or es_director_propio):
        return render(request, 'core/pending.html') # O un 403 Forbidden

    # Traemos las obras de esta empresa con conteo de informes
    obras = empresa.obras.annotate(num_informes=Count('informes')).order_by('-fecha_creacion')

    return render(request, 'core/detalle_constructora.html', {
        'empresa': empresa,
        'obras': obras
    })

@login_required
def detalle_obra(request, pk):
    """NIVEL 3: Detalle de Obra y sus Informes"""
    obra = get_object_or_404(Obra, pk=pk)
    
    # Validaciones de seguridad (simplificadas por brevedad, pero vitales)
    # ... (Aquí iría lógica para asegurar que el usuario tiene derecho a ver esta obra)

    # Buscador interno de informes dentro de la obra
    informes = obra.informes.all().order_by('-fecha_creacion')
    query = request.GET.get('q')
    if query:
        informes = informes.filter(titulo__icontains=query)

    # Paginación
    paginator = Paginator(informes, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'core/detalle_obra.html', {
        'obra': obra,
        'page_obj': page_obj,
        'query': query
    })



@login_required
def crear_constructora(request):
    """Creación de Empresa (Solo Staff Geolab)"""
    if not request.user.es_geolab:
        return redirect('home')

    if request.method == 'POST':
        form = ConstructoraForm(request.POST)
        if form.is_valid():
            empresa = form.save()
            messages.success(request, f'Empresa "{empresa.nombre}" creada correctamente.')
            return redirect('detalle_constructora', pk=empresa.pk)
    else:
        form = ConstructoraForm()

    return render(request, 'core/constructora_form.html', {
        'form': form,
        'titulo': 'Nueva Empresa',
        'btn_texto': 'Crear Empresa'
    })


@login_required
def editar_constructora(request, pk):
    """Edición de Empresa (Solo Staff Geolab)"""
    empresa = get_object_or_404(Constructora, pk=pk)
    
    if not request.user.es_geolab:
        return redirect('home') # Seguridad

    if request.method == 'POST':
        form = ConstructoraForm(request.POST, instance=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos de la empresa actualizados correctamente.')
            return redirect('detalle_constructora', pk=pk)
    else:
        form = ConstructoraForm(instance=empresa)

    return render(request, 'core/constructora_form.html', {
        'form': form,
        'titulo': f'Editar Empresa: {empresa.nombre}',
        'btn_texto': 'Guardar Cambios'
    })

@login_required
def crear_obra(request, pk):
    """Crear una obra dentro de una empresa (Solo Staff Geolab)."""
    empresa = get_object_or_404(Constructora, pk=pk)

    if not request.user.es_geolab:
        return redirect('home')

    if request.method == 'POST':
        form = ObraForm(request.POST, constructora=empresa)
        if form.is_valid():
            obra = form.save(commit=False)
            obra.constructora = empresa
            obra.fecha_creacion = timezone.now()
            obra.save()
            messages.success(request, f'Obra "{obra.nombre}" creada correctamente.')
            return redirect('detalle_constructora', pk=empresa.pk)
    else:
        form = ObraForm(constructora=empresa)

    return render(request, 'core/obra_form.html', {
        'form': form,
        'titulo': f'Nueva Obra · {empresa.nombre}',
        'btn_texto': 'Crear Obra'
    })


@login_required
def editar_obra(request, pk):
    """Edición de Obra (Solo Staff Geolab)"""
    obra = get_object_or_404(Obra, pk=pk)
    
    if not request.user.es_geolab:
        return redirect('home')

    if request.method == 'POST':
        form = ObraForm(request.POST, instance=obra)
        if form.is_valid():
            form.save()
            messages.success(request, 'Obra actualizada correctamente.')
            return redirect('detalle_obra', pk=pk)
    else:
        form = ObraForm(instance=obra)

    return render(request, 'core/obra_form.html', {
        'form': form,
        'titulo': f'Editar Obra: {obra.nombre}',
        'btn_texto': 'Actualizar Obra'
    })


@login_required
def lista_informes_obra(request, pk):
    """
    Lista completa de informes de una obra con paginación.
    Página separada para ver todos los documentos técnicos.
    """
    obra = get_object_or_404(Obra, pk=pk)

    # Verificar permisos
    if not request.user.es_geolab:
        if hasattr(request.user, 'perfil_cliente'):
            perfil = request.user.perfil_cliente
            if perfil.rol == 'director':
                if obra.constructora != perfil.empresa:
                    return redirect('home')
            else:
                if obra not in perfil.obras_asignadas.all():
                    return redirect('home')
        else:
            return redirect('home')

    # Obtener informes
    informes = Informe.objects.filter(obra=obra).order_by('-fecha_creacion')

    # Búsqueda por palabras, sin importar tildes ni separadores:
    # "INF 0340" encuentra "INF-0340-2026...", "compresión" encuentra "COMPRESION"
    query = (request.GET.get('q') or '').strip()
    for palabra in _palabras_busqueda(query):
        informes = informes.filter(titulo__icontains=palabra)

    # Filtro de fecha
    fecha_desde = request.GET.get('fecha_desde')
    fecha_hasta = request.GET.get('fecha_hasta')
    if fecha_desde:
        informes = informes.filter(fecha_creacion__date__gte=fecha_desde)
    if fecha_hasta:
        informes = informes.filter(fecha_creacion__date__lte=fecha_hasta)

    # Paginación (50 por página: las filas son compactas)
    paginator = Paginator(informes, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    paginas = paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)

    context = {
        'obra': obra,
        'page_obj': page_obj,
        'paginas': paginas,
        'query': query,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'hay_filtros': bool(query or fecha_desde or fecha_hasta),
        'total_informes': obra.informes.count(),
        'ultimo_informe': obra.informes.exclude(fecha_creacion__isnull=True)
                              .order_by('-fecha_creacion').values_list('fecha_creacion', flat=True).first(),
        'puede_eliminar': request.user.is_superuser,
    }
    return render(request, 'core/lista_informes_obra.html', context)


def _palabras_busqueda(texto):
    """'INF 0340 compresión' -> ['INF', '0340', 'compresion'] (sin tildes; separadores fuera)."""
    import re
    import unicodedata
    plano = ''.join(c for c in unicodedata.normalize('NFKD', texto or '') if not unicodedata.combining(c))
    return [p for p in re.split(r'[\s_\-.]+', plano) if p]


@login_required
def eliminar_informes(request, pk):
    """
    Borra uno o varios informes de una obra (solo superusuarios, por POST).
    Deja cada borrado en InformeEliminado (bitácora) para que la sincronización
    con WordPress no los vuelva a traer, y borra el PDF del almacenamiento.
    """
    from django.db import transaction
    from django.utils.http import url_has_allowed_host_and_scheme
    from .models import InformeEliminado

    obra = get_object_or_404(Obra, pk=pk)
    volver = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(volver, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        volver = reverse('lista_informes_obra', args=[obra.pk])

    if request.method != 'POST':
        return redirect(volver)
    if not request.user.is_superuser:
        messages.error(request, 'Solo un superadministrador puede eliminar informes.')
        return redirect(volver)

    ids = [int(i) for i in request.POST.getlist('informes') if str(i).isdigit()]
    informes = list(obra.informes.filter(pk__in=ids))
    if not informes:
        messages.warning(request, 'No se eliminó nada: no se eligió ningún informe de esta obra.')
        return redirect(volver)

    archivos = [i.archivo.name for i in informes if i.archivo]
    with transaction.atomic():
        InformeEliminado.objects.bulk_create([
            InformeEliminado(
                titulo=i.titulo, obra_codigo=obra.codigo_obra, obra_nombre=obra.nombre,
                id_wp_original=i.id_wp_original, archivo=i.archivo.name if i.archivo else '',
                fecha_informe=i.fecha_creacion, eliminado_por=request.user,
            )
            for i in informes
        ])
        Informe.objects.filter(pk__in=[i.pk for i in informes]).delete()
        transaction.on_commit(lambda: _borrar_archivos(archivos))

    if len(informes) == 1:
        messages.success(request, f'Informe "{informes[0].titulo}" eliminado.')
    else:
        messages.success(request, f'{len(informes)} informes eliminados.')
    return redirect(volver)


def _borrar_archivos(nombres):
    """Borra los PDF del almacenamiento (S3 en producción). Un fallo no deshace el borrado."""
    import logging
    from django.core.files.storage import default_storage

    for nombre in nombres:
        try:
            default_storage.delete(nombre)
        except Exception:  # noqa: BLE001 - el registro ya quedó; solo se avisa en el log
            logging.getLogger(__name__).exception('No se pudo borrar el archivo %s', nombre)


def _guardar_informes(request, form, obra):
    """Crea un Informe por cada PDF del formulario (todos o ninguno) y deja el mensaje."""
    from django.db import transaction
    from .forms import titulo_desde_archivo

    repetidos = form.informes_repetidos(obra)
    fecha = form.fecha_creacion()
    with transaction.atomic():
        informes = [
            Informe.objects.create(
                titulo=titulo_desde_archivo(archivo.name), obra=obra,
                archivo=archivo, fecha_creacion=fecha,
            )
            for archivo in form.cleaned_data['archivos']
        ]
    if len(informes) == 1:
        messages.success(request, f'Informe "{informes[0].titulo}" cargado exitosamente en {obra.nombre}.')
    else:
        messages.success(request, f'{len(informes)} informes cargados exitosamente en {obra.nombre}.')
    if repetidos:
        messages.warning(
            request,
            f'Ya había informes con el mismo nombre en esta obra: {", ".join(repetidos)}. '
            'Se cargaron igual; revisa si alguno sobra.'
        )
    return informes


@login_required
def cargar_informe(request):
    """
    Vista para cargar nuevos informes técnicos.
    Solo accesible para Staff Geolab.
    """
    from .forms import InformeForm

    if not request.user.es_geolab:
        return redirect('home')

    if request.method == 'POST':
        form = InformeForm(request.POST, request.FILES)
        if form.is_valid():
            obra = form.cleaned_data['obra']
            _guardar_informes(request, form, obra)
            # Redirigir al detalle de la obra
            return redirect('detalle_obra', pk=obra.pk)
    else:
        # Si viene de una obra específica, pre-seleccionar
        obra_id = request.GET.get('obra')
        initial = {}
        if obra_id:
            initial['obra'] = obra_id
        form = InformeForm(initial=initial)

    # Obtener estadísticas para mostrar
    total_informes = Informe.objects.count()

    # Obtener todas las constructoras para el buscador jerárquico
    constructoras = Constructora.objects.all().order_by('nombre')

    context = {
        'form': form,
        'total_informes': total_informes,
        'constructoras': constructoras,
    }
    return render(request, 'core/cargar_informe.html', context)


@login_required
def cargar_informe_obra(request, pk):
    """
    Vista para cargar informe directamente a una obra específica.
    """
    from .forms import InformeForm

    if not request.user.es_geolab:
        return redirect('home')

    obra = get_object_or_404(Obra, pk=pk)

    if request.method == 'POST':
        form = InformeForm(request.POST, request.FILES, constructora=obra.constructora)
        if form.is_valid():
            _guardar_informes(request, form, obra)  # la obra de la URL manda
            return redirect('detalle_obra', pk=obra.pk)
    else:
        form = InformeForm(initial={'obra': obra.pk}, constructora=obra.constructora)

    context = {
        'form': form,
        'obra': obra,
    }
    return render(request, 'core/cargar_informe_obra.html', context)
