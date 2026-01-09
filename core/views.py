from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.contrib import messages
from .forms import ConstructoraForm, ObraForm
from users.models import Constructora
from .models import Informe, Obra

@login_required
def dashboard_router(request):

    """Redirige al dashboard correcto según el tipo de usuario"""
    if request.user.es_geolab:
        return dashboard_staff(request)
    elif request.user.es_cliente:
        return dashboard_client(request)
    else:
        return render(request, 'core/pending.html') # Usuario sin rol definido

@login_required
def dashboard_staff(request):
    """Vista Tipo Torre de Control para Geolab"""
    # Estadísticas Globales
    total_informes = Informe.objects.count()
    obras_activas = Obra.objects.count()
    
    # Últimos 10 informes cargados al sistema (de cualquier cliente)
    ultimos_informes = Informe.objects.select_related('obra', 'obra__constructora').order_by('-fecha_creacion')[:10]

    context = {
        'total_informes': total_informes,
        'obras_activas': obras_activas,
        'ultimos_informes': ultimos_informes
    }
    return render(request, 'core/home_staff.html', context)

@login_required
def dashboard_client(request):
    """Vista Tipo Portal Bancario para Clientes"""
    perfil = request.user.perfil_cliente
    
    # 1. FILTRADO DE SEGURIDAD
    if perfil.rol == 'director':
        # Ve todo lo de su empresa
        obras = Obra.objects.filter(constructora=perfil.empresa)
        informes = Informe.objects.filter(obra__constructora=perfil.empresa)
    else:
        # Residente: Solo sus obras asignadas
        obras = perfil.obras_asignadas.all()
        informes = Informe.objects.filter(obra__in=obras)

    # 2. BÚSQUEDA
    query = request.GET.get('q')
    if query:
        informes = informes.filter(
            Q(titulo__icontains=query) |
            Q(obra__nombre__icontains=query)
        )

    # 3. DATOS PARA EL DASHBOARD
    # Paginación de informes
    paginator = Paginator(informes.order_by('-fecha_creacion'), 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    context = {
        'perfil': perfil,
        'mis_obras': obras, # Para mostrar tarjetas de obras
        'page_obj': page_obj,
        'query': query
    }
    return render(request, 'core/home_client.html', context)




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

    return render(request, 'core/editar_form.html', {
        'form': form, 
        'titulo': f'Editar Empresa: {empresa.nombre}',
        'btn_texto': 'Guardar Cambios'
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

    return render(request, 'core/editar_form.html', {
        'form': form, 
        'titulo': f'Editar Obra: {obra.nombre}',
        'btn_texto': 'Actualizar Obra'
    })
