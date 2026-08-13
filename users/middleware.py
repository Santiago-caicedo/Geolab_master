"""
Middleware de restriccion de acceso por rol.

El Coordinador de Calidad necesita 'es_geolab=True' para entrar al SGC (asi lo
exige calidad.views._usuario_tiene_acceso), pero ese mismo flag es la puerta de
entrada de ~43 vistas de core, users, solicitudes y ensayos. En vez de agregar
una excepcion en cada una de esas vistas (que es justo el tipo de chequeo que se
olvida al crear una vista nueva), este middleware lo encierra en /calidad/.

Funciona por lista blanca: todo lo que no este explicitamente permitido queda
bloqueado, de modo que cualquier modulo o URL que se agregue en el futuro nace
cerrado para este rol.
"""

from django.contrib import messages
from django.shortcuts import redirect


class RestriccionCalidadMiddleware:
    """Encierra al Coordinador de Calidad dentro del modulo de calidad."""

    # Unicos prefijos que puede visitar. '/' entra aparte (ver _ruta_permitida)
    # porque es el router que lo reenvia a su propio panel.
    PREFIJOS_PERMITIDOS = (
        '/calidad/',    # el SGC completo
        '/accounts/',   # login, logout y cambio de contrasena
        '/static/',     # en DEBUG los sirve Django; en produccion van a S3
        '/media/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._debe_restringir(request):
            messages.warning(
                request,
                'Tu usuario solo tiene acceso al Sistema de Calidad.'
            )
            return redirect('explorador_calidad')
        return self.get_response(request)

    def _debe_restringir(self, request):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        # Los superusuarios quedan fuera para no bloquearse a si mismos del admin
        if user.is_superuser:
            return False
        if not user.es_coordinador_calidad:
            return False
        return not self._ruta_permitida(request.path)

    def _ruta_permitida(self, ruta):
        if ruta == '/':
            return True
        return ruta.startswith(self.PREFIJOS_PERMITIDOS)
