import logging
import mimetypes

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, Http404

from .models import AreaCalidad, Carpeta, Documento, AccesoAreaUsuario
from .forms import SubirDocumentoForm, CrearCarpetaForm
from users.models import UsuarioBase

logger = logging.getLogger(__name__)


def _usuario_tiene_acceso(user, area, requiere_edicion=False):
    """Verifica si un usuario Geolab tiene acceso a un área de calidad."""
    if not user.es_geolab:
        return False
    if user.es_admin_geolab:
        return True
    acceso = AccesoAreaUsuario.objects.filter(usuario=user, area=area).first()
    if not acceso:
        return False
    return acceso.puede_editar if requiere_edicion else True


@login_required
def explorador_calidad(request):
    """Landing page: muestra las 8 áreas de calidad como grid."""
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder al Sistema de Calidad.")
        return redirect('home')

    areas = AreaCalidad.objects.all()

    if not request.user.es_admin_geolab:
        # Filtrar solo áreas a las que tiene acceso
        ids_con_acceso = AccesoAreaUsuario.objects.filter(
            usuario=request.user
        ).values_list('area_id', flat=True)
        areas = areas.filter(pk__in=ids_con_acceso)

    # Contar carpetas y documentos por área
    areas_info = []
    for area in areas:
        num_carpetas = Carpeta.objects.filter(area=area).count()
        num_documentos = Documento.objects.filter(carpeta__area=area).count()
        areas_info.append({
            'area': area,
            'num_carpetas': num_carpetas,
            'num_documentos': num_documentos,
        })

    return render(request, 'calidad/explorador.html', {
        'areas_info': areas_info,
    })


@login_required
def contenido_area_raiz(request, pk):
    """Muestra carpetas raíz de un área (carpetas sin padre)."""
    area = get_object_or_404(AreaCalidad, pk=pk)

    if not _usuario_tiene_acceso(request.user, area):
        messages.error(request, "No tienes acceso a esta área.")
        return redirect('explorador_calidad')

    carpetas = Carpeta.objects.filter(area=area, padre=None)
    documentos = []  # No hay documentos sueltos en la raíz del área
    puede_editar = _usuario_tiene_acceso(request.user, area, requiere_edicion=True)

    return render(request, 'calidad/carpeta.html', {
        'area': area,
        'carpeta_actual': None,
        'carpetas': carpetas,
        'documentos': documentos,
        'breadcrumb': [],
        'puede_editar': puede_editar,
        'es_raiz_area': True,
    })


@login_required
def contenido_carpeta(request, pk):
    """Muestra subcarpetas y documentos dentro de una carpeta."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area', 'padre'), pk=pk
    )
    area = carpeta.area

    if not _usuario_tiene_acceso(request.user, area):
        messages.error(request, "No tienes acceso a esta área.")
        return redirect('explorador_calidad')

    carpetas = carpeta.subcarpetas.all()
    documentos = carpeta.documentos.all()
    puede_editar = _usuario_tiene_acceso(request.user, area, requiere_edicion=True)

    return render(request, 'calidad/carpeta.html', {
        'area': area,
        'carpeta_actual': carpeta,
        'carpetas': carpetas,
        'documentos': documentos,
        'breadcrumb': carpeta.ruta_breadcrumb,
        'puede_editar': puede_editar,
        'es_raiz_area': False,
    })


@login_required
def subir_documento(request, pk):
    """Sube uno o múltiples documentos a una carpeta."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area'), pk=pk
    )
    area = carpeta.area

    if not _usuario_tiene_acceso(request.user, area, requiere_edicion=True):
        messages.error(request, "No tienes permiso para subir archivos en esta área.")
        return redirect('contenido_carpeta', pk=carpeta.pk)

    if request.method == 'POST':
        form = SubirDocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            archivos = request.FILES.getlist('archivos')
            count = 0
            for archivo in archivos:
                Documento.objects.create(
                    nombre=archivo.name,
                    carpeta=carpeta,
                    archivo=archivo,
                    tamano_bytes=archivo.size,
                    subido_por=request.user,
                )
                count += 1
            messages.success(request, f'{count} archivo(s) subido(s) correctamente.')
            return redirect('contenido_carpeta', pk=carpeta.pk)
    else:
        form = SubirDocumentoForm()

    return render(request, 'calidad/subir_documento.html', {
        'form': form,
        'carpeta': carpeta,
        'area': area,
        'breadcrumb': carpeta.ruta_breadcrumb,
    })


@login_required
def crear_carpeta(request, pk):
    """Crea una subcarpeta dentro de una carpeta existente."""
    carpeta_padre = get_object_or_404(
        Carpeta.objects.select_related('area'), pk=pk
    )
    area = carpeta_padre.area

    if not _usuario_tiene_acceso(request.user, area, requiere_edicion=True):
        messages.error(request, "No tienes permiso para crear carpetas en esta área.")
        return redirect('contenido_carpeta', pk=carpeta_padre.pk)

    if request.method == 'POST':
        form = CrearCarpetaForm(request.POST)
        if form.is_valid():
            nueva = form.save(commit=False)
            nueva.area = area
            nueva.padre = carpeta_padre
            nueva.creado_por = request.user
            nueva.save()
            messages.success(request, f'Carpeta "{nueva.nombre}" creada.')
            return redirect('contenido_carpeta', pk=carpeta_padre.pk)
    else:
        form = CrearCarpetaForm()

    return render(request, 'calidad/crear_carpeta.html', {
        'form': form,
        'carpeta_padre': carpeta_padre,
        'area': area,
        'breadcrumb': carpeta_padre.ruta_breadcrumb,
    })


@login_required
def crear_carpeta_raiz(request, pk):
    """Crea una carpeta en la raíz de un área (sin padre)."""
    area = get_object_or_404(AreaCalidad, pk=pk)

    if not _usuario_tiene_acceso(request.user, area, requiere_edicion=True):
        messages.error(request, "No tienes permiso para crear carpetas en esta área.")
        return redirect('contenido_area_raiz', pk=area.pk)

    if request.method == 'POST':
        form = CrearCarpetaForm(request.POST)
        if form.is_valid():
            nueva = form.save(commit=False)
            nueva.area = area
            nueva.padre = None
            nueva.creado_por = request.user
            nueva.save()
            messages.success(request, f'Carpeta "{nueva.nombre}" creada.')
            return redirect('contenido_area_raiz', pk=area.pk)
    else:
        form = CrearCarpetaForm()

    return render(request, 'calidad/crear_carpeta.html', {
        'form': form,
        'carpeta_padre': None,
        'area': area,
        'breadcrumb': [],
    })


@login_required
def descargar_documento(request, pk):
    """Descarga un documento verificando acceso al área."""
    documento = get_object_or_404(
        Documento.objects.select_related('carpeta__area'), pk=pk
    )
    area = documento.carpeta.area

    if not _usuario_tiene_acceso(request.user, area):
        messages.error(request, "No tienes acceso a este documento.")
        return redirect('explorador_calidad')

    if not documento.archivo:
        raise Http404("Archivo no encontrado.")

    content_type, _ = mimetypes.guess_type(documento.archivo.name)
    response = FileResponse(
        documento.archivo.open('rb'),
        content_type=content_type or 'application/octet-stream',
    )
    response['Content-Disposition'] = f'inline; filename="{documento.nombre}"'
    return response


@login_required
def eliminar_documento(request, pk):
    """Elimina un documento (solo admins Geolab)."""
    documento = get_object_or_404(
        Documento.objects.select_related('carpeta__area'), pk=pk
    )

    if not request.user.es_admin_geolab:
        messages.error(request, "Solo administradores pueden eliminar documentos.")
        return redirect('contenido_carpeta', pk=documento.carpeta.pk)

    if request.method == 'POST':
        carpeta_pk = documento.carpeta.pk
        nombre = documento.nombre
        documento.archivo.delete(save=False)
        documento.delete()
        messages.success(request, f'Documento "{nombre}" eliminado.')
        return redirect('contenido_carpeta', pk=carpeta_pk)

    return render(request, 'calidad/eliminar_confirm.html', {
        'objeto': documento,
        'tipo': 'documento',
        'nombre': documento.nombre,
        'url_cancelar': documento.carpeta.pk,
    })


@login_required
def eliminar_carpeta(request, pk):
    """Elimina una carpeta vacía (solo admins Geolab)."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area', 'padre'), pk=pk
    )

    if not request.user.es_admin_geolab:
        messages.error(request, "Solo administradores pueden eliminar carpetas.")
        return redirect('contenido_carpeta', pk=carpeta.pk)

    if not carpeta.esta_vacia:
        messages.error(request, "Solo se pueden eliminar carpetas vacías.")
        if carpeta.padre:
            return redirect('contenido_carpeta', pk=carpeta.padre.pk)
        return redirect('contenido_area_raiz', pk=carpeta.area.pk)

    if request.method == 'POST':
        padre_pk = carpeta.padre.pk if carpeta.padre else None
        area_pk = carpeta.area.pk
        nombre = carpeta.nombre
        carpeta.delete()
        messages.success(request, f'Carpeta "{nombre}" eliminada.')
        if padre_pk:
            return redirect('contenido_carpeta', pk=padre_pk)
        return redirect('contenido_area_raiz', pk=area_pk)

    url_cancelar = carpeta.padre.pk if carpeta.padre else None

    return render(request, 'calidad/eliminar_confirm.html', {
        'objeto': carpeta,
        'tipo': 'carpeta',
        'nombre': carpeta.nombre,
        'url_cancelar': url_cancelar,
        'area_pk': carpeta.area.pk,
    })


@login_required
def gestionar_accesos(request):
    """Gestión de accesos por área (solo admins Geolab)."""
    if not request.user.es_admin_geolab:
        messages.error(request, "Solo administradores pueden gestionar accesos.")
        return redirect('explorador_calidad')

    areas = AreaCalidad.objects.all()
    usuarios_geolab = UsuarioBase.objects.filter(
        es_geolab=True
    ).select_related('perfil_geolab').order_by('first_name', 'last_name')

    # Excluir admins (ya tienen acceso total)
    usuarios_geolab = [u for u in usuarios_geolab if not u.es_admin_geolab]

    if request.method == 'POST':
        # Procesar la matriz de checkboxes
        # Formato: acceso_{usuario_id}_{area_id} = "lectura" | "edicion"
        # Si no aparece, se elimina el acceso
        accesos_actualizados = 0

        for usuario in usuarios_geolab:
            for area in areas:
                key = f'acceso_{usuario.pk}_{area.pk}'
                valor = request.POST.get(key, '')

                acceso_existente = AccesoAreaUsuario.objects.filter(
                    usuario=usuario, area=area
                ).first()

                if valor == 'lectura':
                    if acceso_existente:
                        if acceso_existente.puede_editar:
                            acceso_existente.puede_editar = False
                            acceso_existente.save()
                            accesos_actualizados += 1
                    else:
                        AccesoAreaUsuario.objects.create(
                            usuario=usuario, area=area,
                            puede_editar=False, asignado_por=request.user
                        )
                        accesos_actualizados += 1
                elif valor == 'edicion':
                    if acceso_existente:
                        if not acceso_existente.puede_editar:
                            acceso_existente.puede_editar = True
                            acceso_existente.save()
                            accesos_actualizados += 1
                    else:
                        AccesoAreaUsuario.objects.create(
                            usuario=usuario, area=area,
                            puede_editar=True, asignado_por=request.user
                        )
                        accesos_actualizados += 1
                else:
                    # Sin acceso: eliminar si existía
                    if acceso_existente:
                        acceso_existente.delete()
                        accesos_actualizados += 1

        messages.success(request, f'Accesos actualizados ({accesos_actualizados} cambios).')
        return redirect('gestionar_accesos')

    # Construir la matriz para el template
    accesos_dict = {}
    for acceso in AccesoAreaUsuario.objects.filter(
        usuario__in=[u.pk for u in usuarios_geolab]
    ):
        accesos_dict[(acceso.usuario_id, acceso.area_id)] = acceso

    matriz = []
    for usuario in usuarios_geolab:
        fila = {
            'usuario': usuario,
            'areas': []
        }
        for area in areas:
            acceso = accesos_dict.get((usuario.pk, area.pk))
            if acceso:
                valor = 'edicion' if acceso.puede_editar else 'lectura'
            else:
                valor = ''
            fila['areas'].append({
                'area': area,
                'valor': valor,
            })
        matriz.append(fila)

    return render(request, 'calidad/gestionar_accesos.html', {
        'areas': areas,
        'matriz': matriz,
    })
