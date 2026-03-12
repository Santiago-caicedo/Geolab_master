from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from django.http import Http404, JsonResponse, HttpResponse
from django.db import models, transaction
import logging
import os

from .models import RemisionMuestras, Muestra
from .forms import (
    CrearRemisionForm,
    CrearRemisionClienteForm,
    ResponderRemisionForm,
    MuestraFormSet,
    RecepcionLabForm,
)
from core.models import Obra

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Obtiene la IP real del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def crear_hoja_trabajo_y_resultados(remision):
    """
    Crea la HojaTrabajo y los ResultadoMuestra para una remisión completada.

    IMPORTANTE: Esta función debe llamarse DESPUÉS de guardar las muestras del formset
    y DENTRO de una transacción atómica para garantizar consistencia.

    Args:
        remision: Instancia de RemisionMuestras con estado='completada'

    Returns:
        tuple: (hoja_trabajo, num_resultados_creados)

    Raises:
        ValueError: Si la remisión no tiene muestras
    """
    from ensayos.models import HojaTrabajo, ResultadoMuestra

    # Verificar que la remisión tenga muestras
    muestras = list(remision.muestras.all())
    if not muestras:
        raise ValueError(f"La remisión #{remision.orden_trabajo} no tiene muestras registradas")

    # Crear o obtener la hoja de trabajo
    hoja, created = HojaTrabajo.objects.get_or_create(
        remision=remision,
        defaults={'estado': 'pendiente'}
    )

    if created:
        logger.info(f"Creada HojaTrabajo para Remision #{remision.orden_trabajo}")

    # Crear ResultadoMuestra solo para muestras que no tengan uno
    resultados_existentes = set(
        ResultadoMuestra.objects.filter(
            muestra__in=muestras
        ).values_list('muestra_id', flat=True)
    )

    resultados_a_crear = [
        ResultadoMuestra(
            hoja_trabajo=hoja,
            muestra=muestra,
            estado='pendiente'
        )
        for muestra in muestras
        if muestra.pk not in resultados_existentes
    ]

    if resultados_a_crear:
        ResultadoMuestra.objects.bulk_create(resultados_a_crear)
        logger.info(
            f"Creados {len(resultados_a_crear)} ResultadoMuestra "
            f"para Remision #{remision.orden_trabajo}"
        )

    return hoja, len(resultados_a_crear)


@login_required
def crear_remision(request, obra_pk):
    """
    Vista para que Staff Geolab cree una nueva remisión desde una obra.
    """
    # Verificar que es staff Geolab
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para realizar esta acción.')
        return redirect('home')

    obra = get_object_or_404(Obra, pk=obra_pk)

    if request.method == 'POST':
        form = CrearRemisionForm(request.POST)
        if form.is_valid():
            remision = form.save(commit=False)
            remision.obra = obra
            remision.solicitado_por = request.user
            remision.estado = 'enviada'
            remision.fecha_envio = timezone.now()
            remision.save()

            # Enviar email
            enviar_email_remision(request, remision)

            messages.success(
                request,
                f'Remision #{remision.orden_trabajo} creada exitosamente. Se ha enviado un email a {remision.email_destinatario}'
            )
            return redirect('detalle_remision', pk=remision.pk)
    else:
        form = CrearRemisionForm()

    # Calcular siguiente número de remisión
    ultima = RemisionMuestras.objects.filter(obra=obra).order_by('-orden_trabajo').first()
    if ultima:
        # Manejar caso de datos legacy (string) o nuevo (int)
        try:
            siguiente_numero = int(ultima.orden_trabajo) + 1
        except (ValueError, TypeError):
            siguiente_numero = obra.remisiones.count() + 1
    else:
        siguiente_numero = 1

    context = {
        'form': form,
        'obra': obra,
        'siguiente_numero': siguiente_numero,
    }
    return render(request, 'solicitudes/crear_remision.html', context)


def enviar_email_remision(request, remision):
    """
    DEPRECADO: Esta funcion era usada por el sistema de tokens.
    Se mantiene temporalmente para compatibilidad pero no se usa.
    Ver: notificar_nueva_remision() para el nuevo sistema.
    """
    pass


def notificar_nueva_remision(request, remision):
    """
    Notifica a Staff Geolab sobre una nueva remision recibida.
    Crea notificacion en sistema + envia email.
    """
    from .models import Notificacion

    # 1. Crear notificacion en el sistema
    Notificacion.objects.create(
        tipo='nueva_remision',
        titulo=f'Nueva Remision #{remision.orden_trabajo}',
        mensaje=f'Se ha recibido una nueva remision de muestras para la obra {remision.obra.nombre} ({remision.obra.constructora.nombre}). Total de muestras: {remision.total_muestras}.',
        solo_staff=True,
        remision=remision,
    )

    # 2. Enviar email a staff (obtener emails de staff)
    from users.models import UsuarioBase
    staff_emails = list(
        UsuarioBase.objects.filter(
            es_geolab=True,
            is_active=True,
            email__isnull=False
        ).exclude(email='').values_list('email', flat=True)
    )

    if staff_emails:
        asunto = f'[Geolab] Nueva Remision #{remision.orden_trabajo} - {remision.obra.nombre}'

        mensaje_texto = f"""
Nueva Remision de Muestras Recibida

Obra: {remision.obra.nombre}
Constructora: {remision.obra.constructora.nombre}
Remision No: {remision.orden_trabajo}
Total Muestras: {remision.total_muestras}
Enviado por: {remision.firmante_nombre}

Fecha: {remision.fecha_creacion.strftime('%d/%m/%Y %H:%M')}

Ingrese al sistema para ver los detalles.

---
Geolab S.A.S.
        """

        try:
            send_mail(
                subject=asunto,
                message=mensaje_texto,
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@geolab.com',
                recipient_list=staff_emails,
                fail_silently=True,
            )
        except Exception as e:
            logger.error(f"Error enviando email de notificacion: {e}")


def responder_remision(request, token):
    """
    Vista pública para que el cliente responda la remisión.
    No requiere login - acceso mediante token único.

    FLUJO ATÓMICO:
    1. Validar formularios
    2. Iniciar transacción
    3. Guardar remisión con estado='completada'
    4. Guardar muestras del formset
    5. Crear HojaTrabajo y ResultadoMuestra
    6. Commit o rollback automático
    """
    remision = get_object_or_404(RemisionMuestras, token_acceso=token)

    # Verificar que no esté ya completada
    if remision.estado == 'completada':
        return render(request, 'solicitudes/remision_completada.html', {
            'remision': remision,
        })

    if request.method == 'POST':
        form = ResponderRemisionForm(request.POST, instance=remision)
        formset = MuestraFormSet(request.POST, instance=remision)

        if form.is_valid() and formset.is_valid():
            # Validar que haya al menos una muestra
            muestras_validas = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]
            if not muestras_validas:
                messages.error(request, 'Debe agregar al menos una muestra.')
                return render(request, 'solicitudes/responder_remision.html', {
                    'remision': remision,
                    'form': form,
                    'formset': formset,
                    'obra': remision.obra,
                })

            try:
                # TRANSACCIÓN ATÓMICA: Todo se guarda o nada
                with transaction.atomic():
                    # 1. Guardar remisión con datos de auditoría
                    remision = form.save(commit=False)
                    remision.estado = 'completada'
                    remision.fecha_respuesta = timezone.now()
                    remision.firma_fecha = timezone.now()
                    remision.firma_ip_address = get_client_ip(request)
                    remision.firma_user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
                    remision.save()

                    # 2. Guardar muestras del formset
                    formset.save()

                    # 3. Crear HojaTrabajo y ResultadoMuestra
                    hoja, num_resultados = crear_hoja_trabajo_y_resultados(remision)

                    logger.info(
                        f"Remision #{remision.orden_trabajo} completada exitosamente. "
                        f"HojaTrabajo: {hoja.pk}, Resultados: {num_resultados}"
                    )

                # 4. Notificar a Staff (fuera de la transacción)
                notificar_nueva_remision(request, remision)

                messages.success(request, 'Remisión enviada correctamente. Gracias.')
                return redirect('confirmacion_remision', token=token)

            except ValueError as e:
                # Error de validación (ej: sin muestras)
                logger.error(f"Error de validación en remisión {token}: {e}")
                messages.error(request, str(e))

            except Exception as e:
                # Error inesperado - la transacción hace rollback automático
                logger.exception(f"Error crítico al procesar remisión {token}: {e}")
                messages.error(
                    request,
                    'Ocurrió un error al procesar la remisión. Por favor intente nuevamente.'
                )
    else:
        form = ResponderRemisionForm(instance=remision)
        formset = MuestraFormSet(instance=remision)

    context = {
        'remision': remision,
        'form': form,
        'formset': formset,
        'obra': remision.obra,
    }
    return render(request, 'solicitudes/responder_remision.html', context)


def confirmacion_remision(request, token):
    """Vista de confirmación después de enviar la remisión"""
    remision = get_object_or_404(RemisionMuestras, token_acceso=token)
    return render(request, 'solicitudes/confirmacion.html', {
        'remision': remision,
    })


@login_required
def detalle_remision(request, pk):
    """
    Vista detalle de una remisión para Staff Geolab.
    Incluye formulario para completar recepción en laboratorio.
    """
    remision = get_object_or_404(RemisionMuestras, pk=pk)

    # Verificar permisos
    if not request.user.es_geolab:
        # Si es cliente, verificar que pertenece a esa obra
        if hasattr(request.user, 'perfil_cliente'):
            perfil = request.user.perfil_cliente
            if perfil.rol == 'director':
                if remision.obra.constructora != perfil.empresa:
                    raise Http404
            else:
                if remision.obra not in perfil.obras_asignadas.all():
                    raise Http404
        else:
            raise Http404

    # Formulario de recepción (solo staff)
    form_recepcion = None
    if request.user.es_geolab:
        if request.method == 'POST':
            form_recepcion = RecepcionLabForm(request.POST, instance=remision)
            if form_recepcion.is_valid():
                form_recepcion.save()
                messages.success(request, 'Datos de recepción actualizados.')
                return redirect('detalle_remision', pk=pk)
        else:
            form_recepcion = RecepcionLabForm(instance=remision)

    context = {
        'remision': remision,
        'muestras': remision.muestras.all(),
        'form_recepcion': form_recepcion,
    }
    return render(request, 'solicitudes/detalle_remision.html', context)


@login_required
def descargar_pdf_remision(request, pk):
    """
    Genera y descarga un PDF con la información completa de la remisión.
    """
    from weasyprint import HTML

    remision = get_object_or_404(RemisionMuestras, pk=pk)

    # Verificar permisos (misma lógica que detalle_remision)
    if not request.user.es_geolab:
        if hasattr(request.user, 'perfil_cliente'):
            perfil = request.user.perfil_cliente
            if perfil.rol == 'director':
                if remision.obra.constructora != perfil.empresa:
                    raise Http404
            else:
                if remision.obra not in perfil.obras_asignadas.all():
                    raise Http404
        else:
            raise Http404

    muestras = remision.muestras.all()
    logo_file = os.path.join(settings.BASE_DIR, 'static', 'img', 'geolab-logo.png')
    logo_path = 'file:///' + logo_file.replace('\\', '/')

    context = {
        'remision': remision,
        'muestras': muestras,
        'logo_path': logo_path,
        'fecha_generacion': timezone.now(),
    }

    html_string = render_to_string('solicitudes/pdf_remision.html', context)
    base_url = 'file:///' + str(settings.BASE_DIR).replace('\\', '/') + '/'
    pdf = HTML(string=html_string, base_url=base_url).write_pdf()

    response = HttpResponse(pdf, content_type='application/pdf')
    filename = f"Remision_{remision.orden_trabajo}_{remision.obra.codigo_obra or remision.obra.pk}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'

    return response


@login_required
def lista_remisiones(request):
    """
    Lista de todas las remisiones para Staff Geolab.
    """
    if not request.user.es_geolab:
        messages.error(request, 'No tiene permisos para ver esta página.')
        return redirect('home')

    remisiones = RemisionMuestras.objects.select_related(
        'obra', 'obra__constructora', 'solicitado_por'
    ).all()

    # Filtros
    estado = request.GET.get('estado')
    if estado:
        remisiones = remisiones.filter(estado=estado)

    busqueda = request.GET.get('q')
    if busqueda:
        remisiones = remisiones.filter(
            models.Q(orden_trabajo__icontains=busqueda) |
            models.Q(obra__nombre__icontains=busqueda) |
            models.Q(obra__constructora__nombre__icontains=busqueda)
        )

    context = {
        'remisiones': remisiones,
        'estado_actual': estado,
        'busqueda': busqueda,
    }
    return render(request, 'solicitudes/lista_remisiones.html', context)


@login_required
def copiar_link_remision(request, pk):
    """API para obtener el link de una remisión (AJAX)"""
    remision = get_object_or_404(RemisionMuestras, pk=pk)
    if not request.user.es_geolab:
        raise Http404

    url = request.build_absolute_uri(remision.get_public_url())
    return JsonResponse({'url': url})


@login_required
def lista_remisiones_obra(request, obra_pk):
    """
    Lista de remisiones de una obra específica.
    Accesible desde el expediente de la obra.
    """
    obra = get_object_or_404(Obra, pk=obra_pk)

    # Verificar permisos
    if not request.user.es_geolab:
        if hasattr(request.user, 'perfil_cliente'):
            perfil = request.user.perfil_cliente
            if perfil.rol == 'director':
                if obra.constructora != perfil.empresa:
                    raise Http404
            else:
                if obra not in perfil.obras_asignadas.all():
                    raise Http404
        else:
            raise Http404

    remisiones = RemisionMuestras.objects.filter(obra=obra).select_related(
        'solicitado_por'
    ).order_by('-fecha_creacion')

    # Filtros
    estado = request.GET.get('estado')
    if estado:
        remisiones = remisiones.filter(estado=estado)

    busqueda = request.GET.get('q')
    if busqueda:
        remisiones = remisiones.filter(
            models.Q(orden_trabajo__icontains=busqueda) |
            models.Q(firmante_nombre__icontains=busqueda)
        )

    context = {
        'obra': obra,
        'remisiones': remisiones,
        'estado_actual': estado,
        'busqueda': busqueda,
    }
    return render(request, 'solicitudes/lista_remisiones_obra.html', context)


# =============================================================================
# VISTAS PARA REMITENTE (Nuevo sistema sin tokens)
# =============================================================================

@login_required
def dashboard_remitente(request):
    """
    Dashboard para usuarios con rol 'remitente'.
    Muestra sus obras asignadas y estadisticas de remisiones.
    """
    if not request.user.es_cliente:
        return redirect('home')

    perfil = request.user.perfil_cliente

    # Obras asignadas (usa la propiedad obras_accesibles)
    mis_obras = perfil.obras_accesibles

    # Estadisticas de remisiones creadas por este usuario
    remisiones_usuario = RemisionMuestras.objects.filter(
        solicitado_por=request.user
    )
    total_remisiones = remisiones_usuario.count()
    remisiones_pendientes = remisiones_usuario.filter(estado='enviada').count()
    remisiones_completadas = remisiones_usuario.filter(estado='completada').count()

    # Ultimas 5 remisiones
    ultimas_remisiones = remisiones_usuario.select_related('obra').order_by('-fecha_creacion')[:5]

    context = {
        'mis_obras': mis_obras,
        'total_remisiones': total_remisiones,
        'remisiones_pendientes': remisiones_pendientes,
        'remisiones_completadas': remisiones_completadas,
        'ultimas_remisiones': ultimas_remisiones,
    }
    return render(request, 'solicitudes/dashboard_remitente.html', context)


@login_required
def crear_remision_cliente(request, obra_pk):
    """
    Vista para que un Remitente cree una remision CON muestras.
    La firma se auto-completa con los datos del usuario logueado.
    """
    # Verificar que es cliente
    if not request.user.es_cliente:
        messages.error(request, 'No tiene permisos para esta accion.')
        return redirect('home')

    obra = get_object_or_404(Obra, pk=obra_pk)
    perfil = request.user.perfil_cliente

    # Verificar que el usuario tiene acceso a esta obra
    if obra not in perfil.obras_accesibles:
        messages.error(request, 'No tiene acceso a esta obra.')
        return redirect('home')

    # Calcular siguiente numero de remision
    ultima = RemisionMuestras.objects.filter(obra=obra).order_by('-orden_trabajo').first()
    if ultima:
        try:
            siguiente_numero = int(ultima.orden_trabajo) + 1
        except (ValueError, TypeError):
            siguiente_numero = obra.remisiones.count() + 1
    else:
        siguiente_numero = 1

    if request.method == 'POST':
        form = CrearRemisionClienteForm(request.POST)
        # Crear instancia temporal para el formset
        remision_temp = RemisionMuestras(obra=obra)
        formset = MuestraFormSet(request.POST, instance=remision_temp)

        if form.is_valid() and formset.is_valid():
            # Validar que haya al menos una muestra
            muestras_validas = [f for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]
            if not muestras_validas:
                messages.error(request, 'Debe agregar al menos una muestra.')
            else:
                try:
                    with transaction.atomic():
                        # 1. Crear la remision
                        remision = form.save(commit=False)
                        remision.obra = obra
                        remision.solicitado_por = request.user
                        remision.estado = 'completada'  # Ya viene completa con muestras y firma
                        remision.fecha_envio = timezone.now()
                        remision.fecha_respuesta = timezone.now()

                        # Auto-firma con datos del usuario
                        remision.firmante_nombre = request.user.get_full_name()
                        remision.firmante_email = request.user.email
                        remision.firmante_cargo = perfil.cargo or 'Remitente'
                        remision.firmante_telefono = perfil.telefono or ''
                        remision.firma_ip_address = get_client_ip(request)
                        remision.firma_user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
                        remision.firma_fecha = timezone.now()
                        remision.acepta_veracidad = True

                        # Calcular cantidad total
                        total_cantidad = sum(
                            f.cleaned_data.get('cantidad', 1)
                            for f in muestras_validas
                        )
                        remision.cliente_cantidad = total_cantidad

                        remision.save()

                        # 2. Guardar muestras
                        formset.instance = remision
                        formset.save()

                        # 3. Crear HojaTrabajo y ResultadoMuestra
                        hoja, num_resultados = crear_hoja_trabajo_y_resultados(remision)

                        # 4. Notificar a Staff
                        notificar_nueva_remision(request, remision)

                        logger.info(
                            f"Remitente {request.user.username} creo Remision #{remision.orden_trabajo} "
                            f"para obra {obra.nombre}. HojaTrabajo: {hoja.pk}"
                        )

                    messages.success(
                        request,
                        f'Remision #{remision.orden_trabajo} creada exitosamente. El laboratorio ha sido notificado.'
                    )
                    return redirect('detalle_remision_remitente', pk=remision.pk)

                except ValueError as e:
                    logger.error(f"Error de validacion: {e}")
                    messages.error(request, str(e))
                except Exception as e:
                    logger.exception(f"Error critico al crear remision: {e}")
                    messages.error(request, 'Ocurrio un error. Por favor intente nuevamente.')
    else:
        form = CrearRemisionClienteForm()
        formset = MuestraFormSet()

    context = {
        'form': form,
        'formset': formset,
        'obra': obra,
        'siguiente_numero': siguiente_numero,
    }
    return render(request, 'solicitudes/crear_remision_cliente.html', context)


@login_required
def mis_remisiones_remitente(request):
    """
    Lista de remisiones creadas por el remitente (solo lectura).
    """
    from django.core.paginator import Paginator

    if not request.user.es_cliente:
        return redirect('home')

    perfil = request.user.perfil_cliente

    # Obtener remisiones del usuario
    remisiones = RemisionMuestras.objects.filter(
        solicitado_por=request.user
    ).select_related('obra', 'obra__constructora').order_by('-fecha_creacion')

    # Filtros
    query = request.GET.get('q', '')
    if query:
        remisiones = remisiones.filter(
            models.Q(orden_trabajo__icontains=query)
        )

    obra_filtro = request.GET.get('obra', '')
    if obra_filtro:
        remisiones = remisiones.filter(obra_id=obra_filtro)

    estado_filtro = request.GET.get('estado', '')
    if estado_filtro:
        remisiones = remisiones.filter(estado=estado_filtro)

    # Paginacion
    paginator = Paginator(remisiones, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'total_remisiones': RemisionMuestras.objects.filter(solicitado_por=request.user).count(),
        'mis_obras': perfil.obras_accesibles,
        'query': query,
        'obra_filtro': obra_filtro,
        'estado_filtro': estado_filtro,
    }
    return render(request, 'solicitudes/mis_remisiones_remitente.html', context)


@login_required
def detalle_remision_remitente(request, pk):
    """
    Vista de solo lectura de una remision para el remitente.
    """
    remision = get_object_or_404(RemisionMuestras, pk=pk)

    # Verificar que es el creador
    if remision.solicitado_por != request.user:
        messages.error(request, 'No tiene acceso a esta remision.')
        return redirect('home')

    context = {
        'remision': remision,
        'muestras': remision.muestras.all().order_by('numero_muestra', 'edad_ensayo_dias'),
    }
    return render(request, 'solicitudes/detalle_remision_remitente.html', context)


# =============================================================================
# VISTAS DE NOTIFICACIONES
# =============================================================================

@login_required
def lista_notificaciones(request):
    """
    Lista de notificaciones del usuario.
    Staff ve notificaciones con solo_staff=True.
    """
    from django.core.paginator import Paginator
    from .models import Notificacion

    if request.user.es_geolab:
        # Staff ve notificaciones para staff + las dirigidas a el
        notificaciones = Notificacion.objects.filter(
            models.Q(solo_staff=True) | models.Q(destinatario=request.user)
        ).order_by('-fecha_creacion')
    else:
        # Clientes solo ven las dirigidas a ellos
        notificaciones = Notificacion.objects.filter(
            destinatario=request.user
        ).order_by('-fecha_creacion')

    no_leidas = notificaciones.filter(leida=False).count()

    paginator = Paginator(notificaciones, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'no_leidas': no_leidas,
    }
    return render(request, 'solicitudes/lista_notificaciones.html', context)


@login_required
def marcar_notificacion_leida(request, pk):
    """Marca una notificacion como leida"""
    from .models import Notificacion

    notificacion = get_object_or_404(Notificacion, pk=pk)

    # Verificar acceso
    if notificacion.solo_staff and not request.user.es_geolab:
        raise Http404
    if notificacion.destinatario and notificacion.destinatario != request.user:
        raise Http404

    notificacion.marcar_leida()
    messages.success(request, 'Notificacion marcada como leida.')

    # Si viene de AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('lista_notificaciones')


@login_required
def marcar_todas_leidas(request):
    """Marca todas las notificaciones como leidas"""
    from .models import Notificacion

    if request.method == 'POST':
        if request.user.es_geolab:
            notificaciones = Notificacion.objects.filter(
                models.Q(solo_staff=True) | models.Q(destinatario=request.user),
                leida=False
            )
        else:
            notificaciones = Notificacion.objects.filter(
                destinatario=request.user,
                leida=False
            )

        count = notificaciones.update(leida=True, fecha_lectura=timezone.now())
        messages.success(request, f'{count} notificaciones marcadas como leidas.')

    return redirect('lista_notificaciones')


@login_required
def contar_notificaciones_no_leidas(request):
    """API para obtener el conteo de notificaciones no leidas (polling)"""
    from .models import Notificacion

    if request.user.es_geolab:
        count = Notificacion.objects.filter(
            models.Q(solo_staff=True) | models.Q(destinatario=request.user),
            leida=False
        ).count()
    else:
        count = Notificacion.objects.filter(
            destinatario=request.user,
            leida=False
        ).count()

    return JsonResponse({'count': count})


@login_required
def obtener_notificaciones_recientes(request):
    """API para obtener las últimas notificaciones (para el dropdown)"""
    from .models import Notificacion

    if request.user.es_geolab:
        notificaciones = Notificacion.objects.filter(
            models.Q(solo_staff=True) | models.Q(destinatario=request.user)
        ).order_by('-fecha_creacion')[:5]
    else:
        notificaciones = Notificacion.objects.filter(
            destinatario=request.user
        ).order_by('-fecha_creacion')[:5]

    data = []
    for n in notificaciones:
        data.append({
            'id': n.pk,
            'titulo': n.titulo,
            'mensaje': n.mensaje[:100] + '...' if len(n.mensaje) > 100 else n.mensaje,
            'tipo': n.tipo,
            'leida': n.leida,
            'fecha': n.fecha_creacion.strftime('%d/%m/%Y %H:%M'),
            'remision_id': n.remision.pk if n.remision else None,
        })

    return JsonResponse({'notificaciones': data})
