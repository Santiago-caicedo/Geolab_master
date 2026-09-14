"""
Ciudades (sedes) canónicas de Geolab y normalización de `Constructora.ciudad`.

El campo es texto libre (viene así de la migración desde WordPress), por lo
que aparecían variantes como "bucaramanga" y "Bucaramanga" que el resto del
sistema (filtro de Empresas, ciudad activa de Facturación, plantilla de
informe por ciudad) trataba como ciudades distintas.

`normalizar_ciudad()` se aplica en `Constructora.save()` y en la migración
users.0006, así que en la base de datos solo quedan valores canónicos.
"""

import re
import unicodedata

# Ciudad canónica -> prefijo del código interno de constructora.
CIUDADES = {
    'Bucaramanga': 'BUC',
    'Bogotá': 'BOG',
    'Ibagué': 'IBA',
}


def sin_acentos(texto):
    """'Bogotá' -> 'bogota' (minúsculas, sin tildes)."""
    nfkd = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


_CANONICA_POR_CLAVE = {sin_acentos(c): c for c in CIUDADES}


def normalizar_ciudad(valor):
    """
    Devuelve la forma canónica de una ciudad:
    - recorta y colapsa espacios;
    - si coincide (sin mayúsculas ni tildes) con una ciudad canónica, usa esa
      ("bucaramanga", "BUCARAMANGA ", "Bogota" -> "Bucaramanga", "Bogotá");
    - si no, la deja con mayúscula inicial en cada palabra ("san gil" -> "San Gil").
    None y cadena vacía se devuelven tal cual.
    """
    if valor is None:
        return None
    limpio = re.sub(r'\s+', ' ', str(valor)).strip()
    if not limpio:
        return ''
    return _CANONICA_POR_CLAVE.get(sin_acentos(limpio), limpio.title())
