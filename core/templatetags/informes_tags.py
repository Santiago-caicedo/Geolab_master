"""
Presentación de informes técnicos: separa el número de informe del tipo de
ensayo a partir del título (que es el nombre del PDF).

    INF-0103-2024-COMPRESION-CILINDROS.xlsx_.pdf -> numero "INF 0103-2024", tipo "Compresión cilindros"
    INF 0340-2026 VIGAS FLEXION M 8V.pdf         -> numero "INF 0340-2026", tipo "Vigas flexión M 8V"
    Analisis_tecnico.pdf                         -> numero "", tipo "Analisis_tecnico"
"""

import re

from django import template

register = template.Library()

_NUMERO = re.compile(r'^\s*INF?[\s_\-.]*(?P<num>\d{1,6})(?:[\s_\-.]+(?P<anio>(?:19|20)\d{2}|\d{2}))?(?![\d])[\s_\-.]*', re.I)
_EXTENSIONES = re.compile(r'(\.(pdf|xlsx?|docx?)[_\-]?\d*)+$', re.I)
_TILDES = {
    'compresion': 'compresión', 'flexion': 'flexión', 'tension': 'tensión', 'traccion': 'tracción',
    'absorcion': 'absorción', 'densidad': 'densidad', 'granulometria': 'granulometría',
    'analisis': 'análisis', 'tecnico': 'técnico', 'informacion': 'información',
}


def _legible(texto):
    texto = _EXTENSIONES.sub('', texto or '')
    texto = re.sub(r'[_\-]+', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip(' .')
    if not texto:
        return ''
    palabras = []
    for p in texto.split(' '):
        # Lo que lleva números o es una sola letra (M 8V, 3000) se deja; el resto a minúsculas
        if any(ch.isdigit() for ch in p) or len(p) == 1:
            palabras.append(p)
        else:
            palabras.append(_TILDES.get(p.lower(), p.lower()))
    frase = ' '.join(palabras)
    return frase[0].upper() + frase[1:]


def _clase(tipo):
    """Familia de ensayo para darle color: cil (cilindros), cub (cubos), vig (vigas/flexión), otro."""
    t = tipo.lower()
    if 'cilindro' in t:
        return 'cil'
    if 'cubo' in t:
        return 'cub'
    if 'viga' in t or 'flexi' in t:
        return 'vig'
    return 'otro'


@register.filter
def partes_informe(titulo):
    """{'numero': 'INF 0103-2024', 'tipo': 'Compresión cilindros', 'clase': 'cil'}; numero vacío si no tiene ese formato."""
    titulo = titulo or ''
    m = _NUMERO.match(titulo)
    if not m:   # sin formato de informe: el nombre tal cual, sin extensión
        tipo = _EXTENSIONES.sub('', titulo).strip() or titulo
        return {'numero': '', 'tipo': tipo, 'clase': 'otro'}
    numero = f"INF {m.group('num')}" + (f"-{m.group('anio')}" if m.group('anio') else '')
    tipo = _legible(titulo[m.end():])
    return {'numero': numero, 'tipo': tipo, 'clase': _clase(tipo)}
