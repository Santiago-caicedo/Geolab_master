import logging
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import (
    AreaCalidad, Carpeta, Documento,
    AccesoAreaUsuario, AccesoCarpetaUsuario,
)
from .forms import SubirDocumentoForm, CrearCarpetaForm, CrearUsuarioCalidadForm
from . import permisos as permisos_sgc
from users.models import UsuarioBase, FuncionarioGeolab

logger = logging.getLogger(__name__)


def _usuario_tiene_acceso(user, area, requiere_edicion=False):
    """
    Acceso POR AREA para el staff Geolab (AccesoAreaUsuario).
    Los Usuarios de Calidad NO pasan por aqui: su acceso es por carpeta
    (ver permisos.py) y se resuelve en cada vista.
    """
    if not user.es_geolab or user.es_usuario_calidad:
        return False
    if user.es_admin_sgc:
        return True
    acceso = AccesoAreaUsuario.objects.filter(usuario=user, area=area).first()
    if not acceso:
        return False
    return acceso.puede_editar if requiere_edicion else True


# ══════════════════════════════════════════════════════════════════════════
# EXPLORADOR
# ══════════════════════════════════════════════════════════════════════════

@login_required
def explorador_calidad(request):
    """Landing page: muestra las areas de calidad como grid."""
    if not request.user.es_geolab:
        messages.error(request, "No tienes permiso para acceder al Sistema de Calidad.")
        return redirect('home')

    areas_info = []

    if request.user.es_usuario_calidad:
        # Solo las areas donde tiene al menos una carpeta asignada
        for area, num_carpetas in permisos_sgc.areas_visibles(request.user):
            num_documentos = Documento.objects.filter(
                carpeta__area=area,
                carpeta__accesos_usuarios__usuario=request.user,
            ).count()
            areas_info.append({
                'area': area,
                'num_carpetas': num_carpetas,
                'num_documentos': num_documentos,
            })
    else:
        areas = AreaCalidad.objects.all()
        if not request.user.es_admin_sgc:
            ids_con_acceso = AccesoAreaUsuario.objects.filter(
                usuario=request.user
            ).values_list('area_id', flat=True)
            areas = areas.filter(pk__in=ids_con_acceso)

        for area in areas:
            areas_info.append({
                'area': area,
                'num_carpetas': Carpeta.objects.filter(area=area).count(),
                'num_documentos': Documento.objects.filter(carpeta__area=area).count(),
            })

    return render(request, 'calidad/explorador.html', {
        'areas_info': areas_info,
    })


@login_required
def contenido_area_raiz(request, pk):
    """Muestra carpetas raiz de un area (carpetas sin padre)."""
    area = get_object_or_404(AreaCalidad, pk=pk)

    if request.user.es_usuario_calidad:
        visibles, _ = permisos_sgc.mapa_visibilidad_area(request.user, area)
        if not visibles:
            messages.error(request, "No tienes carpetas asignadas en esta área.")
            return redirect('explorador_calidad')
        carpetas = Carpeta.objects.filter(area=area, padre=None, pk__in=visibles)
        puede_crear_raiz = False
        puede_eliminar_carpetas = False
    else:
        if not _usuario_tiene_acceso(request.user, area):
            messages.error(request, "No tienes acceso a esta área.")
            return redirect('explorador_calidad')
        carpetas = Carpeta.objects.filter(area=area, padre=None)
        puede_crear_raiz = _usuario_tiene_acceso(request.user, area, requiere_edicion=True)
        puede_eliminar_carpetas = request.user.es_admin_sgc

    return render(request, 'calidad/carpeta.html', {
        'area': area,
        'carpeta_actual': None,
        'carpetas': carpetas,
        'documentos': [],  # No hay documentos sueltos en la raíz del área
        'breadcrumb': [],
        'puede_cargar': False,
        'puede_crear_raiz': puede_crear_raiz,
        'puede_eliminar_docs': False,
        'puede_eliminar_carpetas': puede_eliminar_carpetas,
        'es_de_paso': False,
        'es_raiz_area': True,
    })


@login_required
def contenido_carpeta(request, pk):
    """Muestra subcarpetas y documentos dentro de una carpeta."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area', 'padre'), pk=pk
    )
    area = carpeta.area

    if request.user.es_usuario_calidad:
        permisos = permisos_sgc.permisos_en_carpeta(request.user, carpeta)
        if permisos is None:
            messages.error(request, "No tienes acceso a esta carpeta.")
            return redirect('explorador_calidad')
        visibles, _ = permisos_sgc.mapa_visibilidad_area(request.user, area)
        carpetas = carpeta.subcarpetas.filter(pk__in=visibles)
        documentos = carpeta.documentos.all() if permisos['ver'] else []
        contexto_permisos = {
            'puede_cargar': permisos['cargar'],
            'puede_eliminar_docs': permisos['eliminar'],
            'puede_eliminar_carpetas': False,
            'es_de_paso': permisos['de_paso'],
        }
    else:
        if not _usuario_tiene_acceso(request.user, area):
            messages.error(request, "No tienes acceso a esta área.")
            return redirect('explorador_calidad')
        carpetas = carpeta.subcarpetas.all()
        documentos = carpeta.documentos.all()
        contexto_permisos = {
            'puede_cargar': _usuario_tiene_acceso(request.user, area, requiere_edicion=True),
            'puede_eliminar_docs': request.user.es_admin_sgc,
            'puede_eliminar_carpetas': request.user.es_admin_sgc,
            'es_de_paso': False,
        }

    return render(request, 'calidad/carpeta.html', {
        'area': area,
        'carpeta_actual': carpeta,
        'carpetas': carpetas,
        'documentos': documentos,
        'breadcrumb': carpeta.ruta_breadcrumb,
        'puede_crear_raiz': False,
        'es_raiz_area': False,
        **contexto_permisos,
    })


# ══════════════════════════════════════════════════════════════════════════
# OPERACIONES SOBRE CARPETAS Y DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════

def _puede_cargar_en(user, carpeta):
    """True si el usuario puede subir/crear dentro de la carpeta."""
    if user.es_usuario_calidad:
        permisos = permisos_sgc.permisos_en_carpeta(user, carpeta)
        return bool(permisos and permisos['cargar'])
    return _usuario_tiene_acceso(user, carpeta.area, requiere_edicion=True)


@login_required
def subir_documento(request, pk):
    """Sube uno o múltiples documentos a una carpeta."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area'), pk=pk
    )
    area = carpeta.area

    if not _puede_cargar_en(request.user, carpeta):
        messages.error(request, "No tienes permiso para subir archivos en esta carpeta.")
        if request.user.es_usuario_calidad and permisos_sgc.permisos_en_carpeta(request.user, carpeta) is None:
            return redirect('explorador_calidad')
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

    if not _puede_cargar_en(request.user, carpeta_padre):
        messages.error(request, "No tienes permiso para crear carpetas aquí.")
        if request.user.es_usuario_calidad and permisos_sgc.permisos_en_carpeta(request.user, carpeta_padre) is None:
            return redirect('explorador_calidad')
        return redirect('contenido_carpeta', pk=carpeta_padre.pk)

    if request.method == 'POST':
        form = CrearCarpetaForm(request.POST)
        if form.is_valid():
            nueva = form.save(commit=False)
            nueva.area = area
            nueva.padre = carpeta_padre
            nueva.creado_por = request.user
            nueva.save()

            # El Usuario de Calidad hereda sobre la carpeta que el mismo creo
            # los permisos que tenia sobre la carpeta padre; si no, no podria
            # ni verla.
            if request.user.es_usuario_calidad:
                permisos = permisos_sgc.permisos_en_carpeta(request.user, carpeta_padre)
                AccesoCarpetaUsuario.objects.create(
                    usuario=request.user,
                    carpeta=nueva,
                    puede_ver=True,
                    puede_cargar=permisos['cargar'],
                    puede_eliminar=permisos['eliminar'],
                    asignado_por=request.user,
                )

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
    """Crea una carpeta en la raíz de un área (sin padre). Solo staff."""
    area = get_object_or_404(AreaCalidad, pk=pk)

    if request.user.es_usuario_calidad or not _usuario_tiene_acceso(
        request.user, area, requiere_edicion=True
    ):
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
    """Descarga un documento verificando acceso a la carpeta o al área."""
    documento = get_object_or_404(
        Documento.objects.select_related('carpeta__area'), pk=pk
    )

    if request.user.es_usuario_calidad:
        permisos = permisos_sgc.permisos_en_carpeta(request.user, documento.carpeta)
        tiene_acceso = bool(permisos and permisos['ver'])
    else:
        tiene_acceso = _usuario_tiene_acceso(request.user, documento.carpeta.area)

    if not tiene_acceso:
        messages.error(request, "No tienes acceso a este documento.")
        return redirect('explorador_calidad')

    if not documento.archivo:
        raise Http404("Archivo no encontrado.")

    # Redirigir a la URL del archivo (S3 en prod, media local en dev)
    return redirect(documento.archivo.url)


@login_required
def eliminar_documento(request, pk):
    """
    Elimina un documento. Lo pueden hacer los admins del SGC y los Usuarios
    de Calidad con permiso de eliminar sobre la carpeta del documento.
    """
    documento = get_object_or_404(
        Documento.objects.select_related('carpeta__area'), pk=pk
    )

    if request.user.es_usuario_calidad:
        permisos = permisos_sgc.permisos_en_carpeta(request.user, documento.carpeta)
        autorizado = bool(permisos and permisos['eliminar'])
        if not autorizado and (permisos is None or not permisos['ver']):
            messages.error(request, "No tienes acceso a este documento.")
            return redirect('explorador_calidad')
    else:
        autorizado = request.user.es_admin_sgc

    if not autorizado:
        messages.error(request, "No tienes permiso para eliminar documentos en esta carpeta.")
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
    """Elimina una carpeta vacía (solo admins del SGC)."""
    carpeta = get_object_or_404(
        Carpeta.objects.select_related('area', 'padre'), pk=pk
    )

    if not request.user.es_admin_sgc:
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


# ══════════════════════════════════════════════════════════════════════════
# GESTION DE ACCESOS POR AREA (staff Geolab)
# ══════════════════════════════════════════════════════════════════════════

@login_required
def gestionar_accesos(request):
    """Gestión de accesos por área (solo admins del SGC)."""
    if not request.user.es_admin_sgc:
        messages.error(request, "Solo administradores pueden gestionar accesos.")
        return redirect('explorador_calidad')

    areas = AreaCalidad.objects.all()
    usuarios_geolab = UsuarioBase.objects.filter(
        es_geolab=True
    ).select_related('perfil_geolab').order_by('first_name', 'last_name')

    # Excluir a quienes ya mandan en el SGC (admins y coordinadores) y a los
    # Usuarios de Calidad, cuyos permisos son por carpeta (otra pantalla).
    usuarios_geolab = [
        u for u in usuarios_geolab
        if not u.es_admin_sgc and not u.es_usuario_calidad
    ]

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


# ══════════════════════════════════════════════════════════════════════════
# GESTION DE USUARIOS DE CALIDAD (los crea el coordinador)
# ══════════════════════════════════════════════════════════════════════════

def _solo_admin_sgc(request):
    """Guard comun de las vistas de gestion de usuarios del SGC."""
    if not request.user.es_admin_sgc:
        messages.error(request, "Solo el coordinador puede gestionar usuarios de calidad.")
        return redirect('explorador_calidad')
    return None


@login_required
def usuarios_calidad(request):
    """Lista de Usuarios de Calidad con su cantidad de carpetas asignadas."""
    denegado = _solo_admin_sgc(request)
    if denegado:
        return denegado

    usuarios = UsuarioBase.objects.filter(
        perfil_geolab__area='calidad_usuario'
    ).annotate(
        num_carpetas=Count('accesos_carpetas_calidad')
    ).order_by('first_name', 'last_name', 'username')

    return render(request, 'calidad/usuarios_calidad.html', {
        'usuarios': usuarios,
    })


@login_required
def crear_usuario_calidad(request):
    """
    Crea un Usuario de Calidad: confinado a /calidad/ y sin acceso a ninguna
    carpeta hasta que se le asignen. Usuario + perfil en una transaccion para
    que nunca exista es_geolab=True sin area (fallback de es_admin_geolab).
    """
    denegado = _solo_admin_sgc(request)
    if denegado:
        return denegado

    if request.method == 'POST':
        form = CrearUsuarioCalidadForm(request.POST)
        if form.is_valid():
            datos = form.cleaned_data
            with transaction.atomic():
                usuario = UsuarioBase(
                    username=datos['username'],
                    first_name=datos['nombre'],
                    last_name=datos['apellido'],
                    email=datos['email'],
                    es_geolab=True,
                    es_cliente=False,
                    is_staff=False,
                    is_superuser=False,
                    is_active=True,
                )
                usuario.set_password(datos['password1'])
                usuario.save()
                FuncionarioGeolab.objects.create(
                    user=usuario, area='calidad_usuario'
                )
            logger.info(
                f"Usuario de calidad '{usuario.username}' creado por "
                f"'{request.user.username}'"
            )
            messages.success(
                request,
                f'Usuario "{usuario.username}" creado. Ahora asígnale sus carpetas: '
                f'sin carpetas asignadas no verá ningún contenido.'
            )
            return redirect('permisos_usuario_calidad', pk=usuario.pk)
    else:
        form = CrearUsuarioCalidadForm()

    return render(request, 'calidad/usuario_calidad_form.html', {
        'form': form,
    })


@login_required
def permisos_usuario_calidad(request, pk):
    """
    Matriz de permisos por carpeta de un Usuario de Calidad: por cada carpeta,
    checkboxes de Ver / Cargar / Eliminar. Lo no marcado queda bloqueado.
    """
    denegado = _solo_admin_sgc(request)
    if denegado:
        return denegado

    # El filtro por area garantiza que desde aqui NO se puede tocar a un
    # admin, tecnico o coordinador: solo Usuarios de Calidad.
    usuario = get_object_or_404(
        UsuarioBase, pk=pk, perfil_geolab__area='calidad_usuario'
    )

    if request.method == 'POST':
        with transaction.atomic():
            AccesoCarpetaUsuario.objects.filter(usuario=usuario).delete()
            nuevos = []
            for carpeta in Carpeta.objects.all():
                cargar = f'cargar_{carpeta.pk}' in request.POST
                eliminar = f'eliminar_{carpeta.pk}' in request.POST
                ver = f'ver_{carpeta.pk}' in request.POST or cargar or eliminar
                if ver:
                    nuevos.append(AccesoCarpetaUsuario(
                        usuario=usuario,
                        carpeta=carpeta,
                        puede_ver=True,
                        puede_cargar=cargar,
                        puede_eliminar=eliminar,
                        asignado_por=request.user,
                    ))
            AccesoCarpetaUsuario.objects.bulk_create(nuevos)

        messages.success(
            request,
            f'Permisos de "{usuario.username}" guardados: '
            f'{len(nuevos)} carpeta(s) con acceso.'
        )
        return redirect('usuarios_calidad')

    # Arbol de carpetas por area, aplanado con nivel de indentacion
    grants = {
        g.carpeta_id: g
        for g in AccesoCarpetaUsuario.objects.filter(usuario=usuario)
    }
    secciones = []
    for area in AreaCalidad.objects.all():
        filas = []
        hijos = defaultdict(list)
        for carpeta in Carpeta.objects.filter(area=area):
            hijos[carpeta.padre_id].append(carpeta)

        def aplanar(padre_id, nivel):
            for carpeta in hijos.get(padre_id, []):
                filas.append({
                    'carpeta': carpeta,
                    'nivel': nivel,
                    'grant': grants.get(carpeta.pk),
                })
                aplanar(carpeta.pk, nivel + 1)

        aplanar(None, 0)
        if filas:
            secciones.append({'area': area, 'filas': filas})

    return render(request, 'calidad/usuario_calidad_permisos.html', {
        'usuario': usuario,
        'secciones': secciones,
    })


@login_required
@require_POST
def toggle_usuario_calidad(request, pk):
    """Activa/desactiva el acceso de un Usuario de Calidad."""
    denegado = _solo_admin_sgc(request)
    if denegado:
        return denegado

    usuario = get_object_or_404(
        UsuarioBase, pk=pk, perfil_geolab__area='calidad_usuario'
    )
    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=['is_active'])
    estado = 'activado' if usuario.is_active else 'desactivado'
    messages.success(request, f'Usuario "{usuario.username}" {estado}.')
    return redirect('usuarios_calidad')
