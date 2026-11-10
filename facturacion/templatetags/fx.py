from django import template

from facturacion.formato import texto_precio

register = template.Library()


@register.filter
def pesos(valor):
    """{{ factura.total|pesos }} -> '$ 2.815.000' (o '$ 6.750,50'); vacío -> '—'."""
    texto = texto_precio(valor)
    return f'$ {texto}' if texto else '—'


@register.filter
def cifra(valor):
    """Número sin signo de pesos: 13575 -> '13.575', 2,5 -> '2,5'; vacío -> '0'."""
    return texto_precio(valor) or '0'
