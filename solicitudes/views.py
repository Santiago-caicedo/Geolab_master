from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from django.http import Http404, JsonResponse
from django.db import models

from .models import RemisionMuestras, Muestra
from .forms import (
    CrearRemisionForm,
    ResponderRemisionForm,
    MuestraFormSet,
    RecepcionLabForm,
)
from core.models import Obra


def get_client_ip(request):
    """Obtiene la IP real del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def crear_resultados_para_remision(remision):
    """
    Crea los ResultadoMuestra para cada muestra de una remisión completada.
    Se llama DESPUÉS de guardar las muestras del formset.
    """
    from ensayos.models import HojaTrabajo, ResultadoMuestra

    # Verificar que exista la hoja de trabajo (creada por el signal)
    try:
        hoja = remision.hoja_trabajo
    except HojaTrabajo.DoesNotExist:
        # Si no existe, crearla
        hoja = HojaTrabajo.objects.create(
            remision=remision,
            estado='pendiente'
        )

    # Crear ResultadoMuestra para cada muestra que no tenga uno
    muestras = remision.muestras.all()
    resultados_a_crear = []

    for muestra in muestras:
        if not ResultadoMuestra.objects.filter(muestra=muestra).exists():
            resultados_a_crear.append(
                ResultadoMuestra(
                    hoja_trabajo=hoja,
                    muestra=muestra,
                    estado='pendiente'
                )
            )

    if resultados_a_crear:
        ResultadoMuestra.objects.bulk_create(resultados_a_crear)
        print(f"[VIEW] Creados {len(resultados_a_crear)} ResultadoMuestra para Remision #{remision.orden_trabajo}")


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
    """Envía el email con el link de la remisión"""
    # Construir URL absoluta
    url_relativa = remision.get_public_url()
    url_completa = request.build_absolute_uri(url_relativa)

    asunto = f'Geolab - Remisión de Muestras - {remision.obra.nombre}'

    # Renderizar template de email
    mensaje_html = render_to_string('solicitudes/email_remision.html', {
        'remision': remision,
        'url_formulario': url_completa,
    })

    mensaje_texto = f"""
Estimado(a),

Se ha generado una solicitud de Remisión de Muestras para la obra {remision.obra.nombre}.

Por favor complete el formulario en el siguiente enlace:
{url_completa}

Orden de Trabajo: {remision.orden_trabajo}
Empresa: {remision.obra.constructora.nombre}

Este es un mensaje automático de Geolab S.A.S.
    """

    try:
        send_mail(
            subject=asunto,
            message=mensaje_texto,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@geolab.com',
            recipient_list=[remision.email_destinatario],
            html_message=mensaje_html,
            fail_silently=True,
        )
    except Exception as e:
        print(f"Error enviando email: {e}")


def responder_remision(request, token):
    """
    Vista pública para que el cliente responda la remisión.
    No requiere login - acceso mediante token único.
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
            # Guardar remisión con datos de auditoría
            remision = form.save(commit=False)
            remision.estado = 'completada'
            remision.fecha_respuesta = timezone.now()
            remision.firma_fecha = timezone.now()
            remision.firma_ip_address = get_client_ip(request)
            remision.firma_user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
            remision.save()

            # Guardar muestras
            formset.save()

            # Crear ResultadoMuestra para cada muestra (después de guardar el formset)
            crear_resultados_para_remision(remision)

            messages.success(request, 'Remisión enviada correctamente. Gracias.')
            return redirect('confirmacion_remision', token=token)
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
