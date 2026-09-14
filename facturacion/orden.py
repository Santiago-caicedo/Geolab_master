"""
Clave de ordenamiento natural para códigos de categorías y servicios.

Los códigos del catálogo son texto ("1", "10", "8A", "1-3-5-2", "11-10LV"),
así que ordenar por `codigo` da 1, 10, 11A, 12, ..., 2, 3. Esta clave
convierte cada segmento numérico a 4 dígitos con ceros a la izquierda y
conserva las letras, de modo que el orden alfabético de la clave coincide
con el orden numérico esperado:

    "1"      -> "0001"
    "8A"     -> "0008A"
    "10"     -> "0010"
    "1-3-5"  -> "0001~0003~0005"
    "11-10L" -> "0011~0010L"

El separador es "~" (mayor que letras y dígitos en ASCII) para que un código
corto vaya antes que sus derivados: "11-1L" < "11-1-1L" y "1-3" < "1-3-1".

Se guarda en `CategoriaServicio.clave_orden` y `TipoServicio.clave_orden`
(calculada en save()), y es lo que usa Meta.ordering.
"""

import re

_SEPARADORES = re.compile(r'[-.,\s]+')
_NUMERO_Y_LETRAS = re.compile(r'(\d*)(.*)')
ANCHO_NUMERO = 4
SEPARADOR = '~'


def clave_orden(codigo):
    """Devuelve la clave de ordenamiento natural de un código."""
    partes = []
    for segmento in _SEPARADORES.split(str(codigo or '').strip()):
        if not segmento:
            continue
        numero, letras = _NUMERO_Y_LETRAS.fullmatch(segmento).groups()
        partes.append((numero.zfill(ANCHO_NUMERO) if numero else '') + letras.upper())
    return SEPARADOR.join(partes)[:60]
