"""
Panel de usuarios: un solo lugar, solo para superusuarios, para crear, editar,
activar y dar permisos a TODAS las cuentas del portal (Geolab y clientes).

Las pantallas por módulo siguen existiendo para quien no es superusuario:
/usuarios/ (clientes, staff administrativo), /calidad/usuarios/ (coordinador) y
/facturacion/usuarios/.
"""

import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from calidad import permisos as permisos_sgc
from core.models import Obra
from facturacion import permisos as permisos_fx

from . import roles
from .forms_panel import UsuarioPanelForm
from .models import Constructora, UsuarioBase

logger = logging.getLogger(__name__)
POR_PAGINA = 40


def superusuario_requerido(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_superuser:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Solo un superusuario puede administrar usuarios.'}, status=403)
            messages.error(request, 'Solo un superusuario puede entrar al Panel de usuarios.')
            return redirect('home')
        return vista(request, *args, **kwargs)
    return envoltura


def _usuarios():
    return (UsuarioBase.objects
            .select_related('perfil_geolab', 'perfil_cliente__empresa', 'acceso_facturacion')
            .annotate(num_carpetas=Count('accesos_carpetas_calidad', distinct=True),
                      num_obras=Count('perfil_cliente__obras_asignadas', distinct=True),
                      num_areas=Count('accesos_calidad', distinct=True)))


def _alcance(u, rol):
    """Lo que la persona puede ver, en pocas palabras, para la lista."""
    if u.is_superuser:
        return 'Todo el portal y la administración'
    if rol in roles.TODO_EL_PORTAL:
        return 'Todo el portal'
    if rol == 'tecnico':
        return f'Ensayos · {u.num_areas} área(s) de Calidad' if u.num_areas else 'Ensayos'
    if rol == 'calidad':
        return 'Todo Calidad'
    if rol == 'calidad_usuario':
        return f'{u.num_carpetas} carpeta(s) de Calidad'
    if rol == 'facturacion':
        acceso = roles.acceso_facturacion(u)
        if not acceso:
            return 'Nada asignado'
        n = len(acceso.secciones)
        secciones = 'todas las secciones' if n >= len(permisos_fx.CLAVES) else f'{n} de {len(permisos_fx.CLAVES)} secciones'
        return f'{", ".join(acceso.ciudades) or "sin ciudad"} · {secciones}'
    cli = roles.perfil_cliente(u)
    if rol == 'director' and cli:
        return 'Todas las obras de su empresa'
    if rol in roles.CON_OBRAS:
        return f'{u.num_obras} obra(s)'
    return '—'


def _filtrar(qs, rol):
    if rol == 'superusuario':
        return qs.filter(is_superuser=True)
    if rol == 'sin_rol':
        return qs.filter(Q(es_geolab=True, perfil_geolab__isnull=True)
                         | Q(es_cliente=True, es_geolab=False, perfil_cliente__isnull=True)
                         | Q(es_geolab=False, es_cliente=False))
    r = roles.POR_CLAVE.get(rol)
    if not r:
        return qs
    if r.familia == 'geolab':
        return qs.filter(es_geolab=True, perfil_geolab__area=r.clave)
    return qs.filter(es_cliente=True, es_geolab=False, perfil_cliente__rol=r.clave)


@superusuario_requerido
def panel_usuarios(request):
    q = (request.GET.get('q') or '').strip()
    rol = request.GET.get('rol') or ''
    estado = request.GET.get('estado') or ''
    solo_problemas = request.GET.get('problemas') == '1'

    qs = _usuarios()
    if q:
        for palabra in q.split():
            qs = qs.filter(Q(username__icontains=palabra) | Q(first_name__icontains=palabra)
                           | Q(last_name__icontains=palabra) | Q(email__icontains=palabra)
                           | Q(perfil_cliente__empresa__nombre__icontains=palabra)
                           | Q(perfil_cliente__empresa__codigo__iexact=palabra))
    qs = _filtrar(qs, rol)
    if estado == 'activos':
        qs = qs.filter(is_active=True)
    elif estado == 'inactivos':
        qs = qs.filter(is_active=False)
    qs = qs.order_by('-is_active', 'first_name', 'last_name', 'username')

    filas = []
    for u in qs:
        clave = roles.rol_de(u)
        problemas = roles.problemas_de(u)
        if solo_problemas and not problemas:
            continue
        u.rol = roles.POR_CLAVE.get(clave)
        u.alcance = _alcance(u, clave)
        u.problemas = problemas
        u.empresa = getattr(roles.perfil_cliente(u), 'empresa', None)
        filas.append(u)

    # Conteos del encabezado y de cada rol (sobre todas las cuentas, no sobre el filtro)
    todos = list(_usuarios())
    conteo = {r.clave: 0 for r in roles.ROLES}
    con_problemas = 0
    for u in todos:
        clave = roles.rol_de(u)
        if clave:
            conteo[clave] += 1
        if roles.problemas_de(u):
            con_problemas += 1

    pagina = Paginator(filas, POR_PAGINA).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'users/panel/lista.html', {
        'pagina': pagina,
        'paginas': pagina.paginator.get_elided_page_range(pagina.number, on_each_side=2, on_ends=1),
        'total': len(todos),
        'activos': sum(1 for u in todos if u.is_active),
        'superusuarios': sum(1 for u in todos if u.is_superuser),
        'con_problemas': con_problemas,
        'grupos': [(roles.FAMILIAS['geolab'], [(r, conteo[r.clave]) for r in roles.GEOLAB]),
                   (roles.FAMILIAS['cliente'], [(r, conteo[r.clave]) for r in roles.CLIENTE])],
        'q': q, 'rol': rol, 'estado': estado, 'solo_problemas': solo_problemas,
        'filtrando': bool(q or rol or estado or solo_problemas),
        'querystring': params.urlencode(),
        'resultados': len(filas),
    })


def _contexto_form(form, usuario=None):
    elegidas = set(form['secciones'].value() or [])
    obras_iniciales = []
    empresa_id = form['empresa'].value()
    if empresa_id:
        obras_iniciales = list(Obra.objects.filter(constructora_id=empresa_id)
                               .order_by('codigo_obra', 'nombre').values('id', 'nombre', 'codigo_obra'))
    marcadas = {str(o) for o in (form['obras'].value() or [])}
    familia = roles.familia_de(usuario) if usuario else None
    return {
        'form': form,
        'usuario_editado': usuario,
        'familia_fija': familia,
        'grupos_rol': [(roles.FAMILIAS[f], [r for r in roles.ROLES if r.familia == f])
                       for f in ('geolab', 'cliente') if not familia or familia == f],
        'rol_actual': form['rol'].value() or '',
        'grupos_fx': [(grupo, [(c, n, desc, c in elegidas) for c, n, desc in items])
                      for grupo, items in permisos_fx.grupos()],
        'ciudades_elegidas': set(form['ciudades'].value() or []),
        'obras_iniciales': obras_iniciales,
        'obras_marcadas': marcadas,
        'empresas': Constructora.objects.order_by('nombre').values('id', 'nombre', 'codigo', 'ciudad'),
        'problemas': roles.problemas_de(usuario) if usuario else [],
        'es_yo': bool(usuario and usuario.pk == form.actor.pk),
    }


@superusuario_requerido
def panel_usuario_nuevo(request):
    inicial = {}
    if request.GET.get('rol') in roles.POR_CLAVE:
        inicial['rol'] = request.GET['rol']
    form = UsuarioPanelForm(request.POST or None, initial=inicial, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        usuario = form.save()
        rol = form.rol_elegido()
        logger.info("Panel de usuarios: '%s' creó a '%s' (%s)", request.user.username, usuario.username, rol.clave)
        if rol.clave == 'calidad_usuario':
            messages.success(request, f'"{usuario.username}" creado. Ahora márquele sus carpetas: sin ellas no ve nada.')
            return redirect('panel_usuario_carpetas', pk=usuario.pk)
        messages.success(request, f'"{usuario.username}" creado como {rol.nombre}. Ya puede iniciar sesión.')
        return redirect('panel_usuarios')
    return render(request, 'users/panel/form.html', _contexto_form(form))


@superusuario_requerido
def panel_usuario(request, pk):
    usuario = get_object_or_404(UsuarioBase, pk=pk)
    form = UsuarioPanelForm(request.POST or None, initial=UsuarioPanelForm.iniciales(usuario),
                            usuario=usuario, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        cambio_clave = bool(form.cleaned_data.get('password1'))
        usuario = form.save()
        if cambio_clave and usuario.pk == request.user.pk:
            update_session_auth_hash(request, usuario)  # cambiar la propia clave no cierra su sesión
        logger.info("Panel de usuarios: '%s' editó a '%s' (%s)", request.user.username, usuario.username,
                    form.cleaned_data['rol'])
        aviso = ' La contraseña cambió.' if cambio_clave else ''
        messages.success(request, f'Cambios de "{usuario.username}" guardados. Se aplican desde su próximo clic.{aviso}')
        if form.cleaned_data['rol'] == 'calidad_usuario' and not usuario.accesos_carpetas_calidad.exists():
            messages.warning(request, 'Todavía no tiene carpetas de Calidad: márquelas aquí.')
            return redirect('panel_usuario_carpetas', pk=usuario.pk)
        return redirect('panel_usuarios')
    return render(request, 'users/panel/form.html', _contexto_form(form, usuario))


@superusuario_requerido
@require_POST
def panel_usuario_estado(request, pk):
    usuario = get_object_or_404(UsuarioBase, pk=pk)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puede desactivar su propia cuenta.')
        return redirect('panel_usuarios')
    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=['is_active'])
    logger.info("Panel de usuarios: '%s' %s a '%s'", request.user.username,
                'activó' if usuario.is_active else 'desactivó', usuario.username)
    if usuario.is_active:
        messages.success(request, f'"{usuario.username}" puede volver a entrar.')
    else:
        messages.success(request, f'"{usuario.username}" desactivado: ya no puede entrar y su sesión abierta se cierra.')
    destino = request.POST.get('volver')
    if destino == 'ficha':
        return redirect('panel_usuario', pk=usuario.pk)
    return redirect('panel_usuarios')


@superusuario_requerido
def panel_usuario_carpetas(request, pk):
    usuario = get_object_or_404(UsuarioBase, pk=pk, es_geolab=True, perfil_geolab__area='calidad_usuario')
    if request.method == 'POST':
        with transaction.atomic():
            n = permisos_sgc.guardar_permisos(usuario, request.POST, request.user)
        logger.info("Panel de usuarios: '%s' dejó a '%s' con %s carpeta(s)", request.user.username, usuario.username, n)
        messages.success(request, f'Carpetas de "{usuario.username}" guardadas: {n} con acceso.')
        return redirect('panel_usuarios')
    return render(request, 'users/panel/carpetas.html', {
        'usuario_editado': usuario,
        'secciones': permisos_sgc.arbol_permisos(usuario),
    })


@superusuario_requerido
def panel_obras_empresa(request, empresa_pk):
    obras = (Obra.objects.filter(constructora_id=empresa_pk)
             .order_by('codigo_obra', 'nombre').values('id', 'nombre', 'codigo_obra'))
    return JsonResponse({'obras': list(obras)})
