"""Formato de dinero a la colombiana, compartido por vistas y plantillas de Facturación."""

from decimal import Decimal, InvalidOperation


def texto_precio(valor):
    """Decimal -> '18.500' (miles con punto), '6.750,50' si tiene centavos; None -> ''."""
    if valor is None or valor == '':
        return ''
    try:
        valor = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return str(valor)
    signo = '-' if valor < 0 else ''
    entero, _, dec = f'{abs(valor):.2f}'.partition('.')
    miles = f'{int(entero):,}'.replace(',', '.')
    return signo + (miles if dec == '00' else f'{miles},{dec}')
