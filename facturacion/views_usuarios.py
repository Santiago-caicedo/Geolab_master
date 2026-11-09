"""
Administración de los Usuarios de Facturación (solo superusuarios).

Un Usuario de Facturación es un UsuarioBase con es_geolab=True, perfil
FuncionarioGeolab(area='facturacion') y un AccesoFacturacion con sus ciudades
y secciones. Los tres se crean en una transacción: nunca existe un usuario
es_geolab=True sin perfil (el fallback de es_admin_geolab lo dejaría como
administrador total, ver nota 22 del CLAUDE.md).
"""

import logging

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.models import FuncionarioGeolab, UsuarioBase

from . import permisos
from .forms_usuarios import UsuarioFacturacionForm
from .models import AccesoFacturacion
from .views import superusuario_required

logger = logging.getLogger(__name__)


def _usuarios_facturacion():
    return UsuarioBase.objects.filter(perfil_geolab__area='facturacion')


def _contexto_form(form, usuario=None):
    elegidas = set(form['secciones'].value() or [])
    return {
        'form': form,
        'usuario_editado': usuario,
        'grupos': [
            (grupo, [(clave, nombre, desc, clave in elegidas) for clave, nombre, desc in items])
            for grupo, items in permisos.grupos()
        ],
        'ciudades_elegidas': set(form['ciudades'].value() or []),
    }


@superusuario_required
def usuarios_facturacion(request):
    usuarios = list(
        _usuarios_facturacion().select_related('acceso_facturacion')
        .order_by('-is_active', 'first_name', 'last_name', 'username')
    )
    for u in usuarios:
        acceso = permisos.acceso_de(u)
        u.fx_ciudades = acceso.ciudades if acceso else []
        u.fx_secciones = [permisos.NOMBRES[c] for c in permisos.CLAVES if acceso and c in acceso.secciones]
        u.fx_todas = bool(acceso) and set(permisos.CLAVES) <= set(acceso.secciones)
    return render(request, 'facturacion/usuarios_facturacion.html', {
        'usuarios': usuarios,
        'total_secciones': len(permisos.CLAVES),
    })


@superusuario_required
def crear_usuario_facturacion(request):
    form = UsuarioFacturacionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        with transaction.atomic():
            usuario = UsuarioBase(
                username=datos['username'], first_name=datos['nombre'], last_name=datos['apellido'],
                email=datos['email'], es_geolab=True, es_cliente=False,
                is_staff=False, is_superuser=False, is_active=True,
            )
            usuario.set_password(datos['password1'])
            usuario.save()
            FuncionarioGeolab.objects.create(user=usuario, area='facturacion')
            AccesoFacturacion.objects.create(
                usuario=usuario, ciudades=datos['ciudades'],
                secciones=form.secciones_ordenadas(), actualizado_por=request.user,
            )
        logger.info("Usuario de facturación '%s' creado por '%s' (ciudades=%s, secciones=%s)",
                    usuario.username, request.user.username, datos['ciudades'], form.secciones_ordenadas())
        messages.success(request, f'Usuario "{usuario.username}" creado. Ya puede iniciar sesión.')
        return redirect('usuarios_facturacion')
    return render(request, 'facturacion/usuario_facturacion_form.html', _contexto_form(form))


@superusuario_required
def editar_usuario_facturacion(request, pk):
    # El filtro por área garantiza que desde aquí no se toca a un admin, técnico ni superusuario
    usuario = get_object_or_404(_usuarios_facturacion(), pk=pk, is_superuser=False)
    acceso = permisos.acceso_de(usuario)
    inicial = {
        'username': usuario.username, 'nombre': usuario.first_name,
        'apellido': usuario.last_name, 'email': usuario.email,
        'ciudades': acceso.ciudades if acceso else [],
        'secciones': acceso.secciones if acceso else [],
    }
    form = UsuarioFacturacionForm(request.POST or None, initial=inicial, usuario=usuario)
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        with transaction.atomic():
            usuario.username = datos['username']
            usuario.first_name = datos['nombre']
            usuario.last_name = datos['apellido']
            usuario.email = datos['email']
            if datos.get('password1'):
                usuario.set_password(datos['password1'])
            usuario.save()
            AccesoFacturacion.objects.update_or_create(
                usuario=usuario,
                defaults={'ciudades': datos['ciudades'], 'secciones': form.secciones_ordenadas(),
                          'actualizado_por': request.user},
            )
        logger.info("Usuario de facturación '%s' editado por '%s' (ciudades=%s, secciones=%s)",
                    usuario.username, request.user.username, datos['ciudades'], form.secciones_ordenadas())
        aviso = ' La contraseña cambió.' if datos.get('password1') else ''
        messages.success(request, f'Permisos de "{usuario.username}" guardados. Se aplican desde su próximo clic.{aviso}')
        return redirect('usuarios_facturacion')
    return render(request, 'facturacion/usuario_facturacion_form.html', _contexto_form(form, usuario))


@superusuario_required
@require_POST
def estado_usuario_facturacion(request, pk):
    usuario = get_object_or_404(_usuarios_facturacion(), pk=pk, is_superuser=False)
    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=['is_active'])
    logger.info("Usuario de facturación '%s' %s por '%s'", usuario.username,
                'activado' if usuario.is_active else 'desactivado', request.user.username)
    if usuario.is_active:
        messages.success(request, f'"{usuario.username}" puede volver a entrar.')
    else:
        messages.success(request, f'"{usuario.username}" desactivado: ya no puede entrar y su sesión abierta se cierra.')
    return redirect('usuarios_facturacion')
