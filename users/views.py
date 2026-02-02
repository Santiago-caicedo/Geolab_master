from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.db.models import Q, Count

from .models import ClienteExterno, Constructora
from .forms import ClienteExternoForm
from core.models import Obra


@login_required
def lista_usuarios_cliente(request):
    """
    Lista todos los usuarios cliente (Directores y Residentes).
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para ver esta página.')
        return redirect('home')

    clientes = ClienteExterno.objects.select_related(
        'user', 'empresa'
    ).prefetch_related('obras_asignadas').order_by('empresa__nombre', 'user__last_name')

    # Filtros
    busqueda = request.GET.get('q', '')
    if busqueda:
        clientes = clientes.filter(
            Q(user__username__icontains=busqueda) |
            Q(user__first_name__icontains=busqueda) |
            Q(user__last_name__icontains=busqueda) |
            Q(user__email__icontains=busqueda) |
            Q(empresa__nombre__icontains=busqueda)
        )

    rol_filtro = request.GET.get('rol', '')
    if rol_filtro:
        clientes = clientes.filter(rol=rol_filtro)

    empresa_filtro = request.GET.get('empresa', '')
    if empresa_filtro:
        clientes = clientes.filter(empresa_id=empresa_filtro)

    # Estadísticas
    total_directores = ClienteExterno.objects.filter(rol='director').count()
    total_residentes = ClienteExterno.objects.filter(rol='residente').count()

    context = {
        'clientes': clientes,
        'busqueda': busqueda,
        'rol_filtro': rol_filtro,
        'empresa_filtro': empresa_filtro,
        'empresas': Constructora.objects.all().order_by('nombre'),
        'total_directores': total_directores,
        'total_residentes': total_residentes,
    }
    return render(request, 'users/lista_usuarios.html', context)


@login_required
def crear_usuario_cliente(request):
    """
    Crea un nuevo usuario cliente (Director o Residente).
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para realizar esta acción.')
        return redirect('home')

    if request.method == 'POST':
        form = ClienteExternoForm(request.POST)
        if form.is_valid():
            cliente = form.save()
            messages.success(
                request,
                f'Usuario {cliente.user.get_full_name()} creado exitosamente.'
            )
            return redirect('lista_usuarios_cliente')
    else:
        form = ClienteExternoForm()

    context = {
        'form': form,
        'titulo': 'Nuevo Usuario Cliente',
        'es_edicion': False,
    }
    return render(request, 'users/form_usuario.html', context)


@login_required
def editar_usuario_cliente(request, pk):
    """
    Edita un usuario cliente existente.
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para realizar esta acción.')
        return redirect('home')

    cliente = get_object_or_404(ClienteExterno, pk=pk)

    if request.method == 'POST':
        form = ClienteExternoForm(request.POST, instance=cliente)
        if form.is_valid():
            cliente = form.save()
            messages.success(
                request,
                f'Usuario {cliente.user.get_full_name()} actualizado exitosamente.'
            )
            return redirect('lista_usuarios_cliente')
    else:
        form = ClienteExternoForm(instance=cliente)

    context = {
        'form': form,
        'cliente': cliente,
        'titulo': f'Editar: {cliente.user.get_full_name()}',
        'es_edicion': True,
    }
    return render(request, 'users/form_usuario.html', context)


@login_required
def detalle_usuario_cliente(request, pk):
    """
    Muestra el detalle de un usuario cliente.
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para ver esta página.')
        return redirect('home')

    cliente = get_object_or_404(
        ClienteExterno.objects.select_related('user', 'empresa'),
        pk=pk
    )

    # Obtener obras que puede ver este cliente
    if cliente.rol == 'director':
        obras_acceso = Obra.objects.filter(constructora=cliente.empresa)
    else:
        obras_acceso = cliente.obras_asignadas.all()

    context = {
        'cliente': cliente,
        'obras_acceso': obras_acceso,
    }
    return render(request, 'users/detalle_usuario.html', context)


@login_required
def toggle_estado_usuario(request, pk):
    """
    Activa o desactiva un usuario cliente (AJAX).
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'Sin permisos'}, status=403)

    cliente = get_object_or_404(ClienteExterno, pk=pk)
    user = cliente.user
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])

    return JsonResponse({
        'success': True,
        'is_active': user.is_active,
        'message': f'Usuario {"activado" if user.is_active else "desactivado"}'
    })


@login_required
def obtener_obras_empresa(request, empresa_pk):
    """
    API para obtener las obras de una empresa (para el formulario dinámico).
    Solo accesible para Staff Geolab.
    """
    if not request.user.es_geolab:
        return JsonResponse({'error': 'Sin permisos'}, status=403)

    obras = Obra.objects.filter(constructora_id=empresa_pk).values('id', 'nombre', 'codigo_obra')
    return JsonResponse({'obras': list(obras)})
