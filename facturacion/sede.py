"""
Ciudad (sede) activa del módulo de Facturación.

Al entrar al módulo el usuario elige una ciudad; se guarda en la sesión y
todas las vistas filtran constructoras, obras, registros y facturas por
`Constructora.ciudad`. El catálogo de servicios y los impuestos son
globales (no tienen ciudad).

La lista de ciudades disponibles sale de los valores distintos de
`Constructora.ciudad` (igual que el filtro de /empresas/), así que no hay
un modelo Sede: para agregar una ciudad basta con asignársela a una
constructora.
"""

from core.models import Obra
from users.models import Constructora

from .models import Factura, RegistroServicio

SESSION_KEY = 'facturacion_ciudad'


def ciudades_disponibles():
    """Ciudades distintas de las constructoras, sin vacías, ordenadas."""
    return list(
        Constructora.objects.exclude(ciudad__isnull=True).exclude(ciudad='')
        .values_list('ciudad', flat=True).distinct().order_by('ciudad')
    )


def ciudad_actual(request):
    return request.session.get(SESSION_KEY)


def fijar_ciudad(request, ciudad):
    request.session[SESSION_KEY] = ciudad


def constructoras_de(ciudad):
    return Constructora.objects.filter(ciudad__iexact=ciudad)


def obras_de(ciudad):
    return Obra.objects.filter(constructora__ciudad__iexact=ciudad)


def registros_de(ciudad):
    return RegistroServicio.objects.filter(obra__constructora__ciudad__iexact=ciudad)


def facturas_de(ciudad):
    return Factura.objects.filter(obra__constructora__ciudad__iexact=ciudad)
