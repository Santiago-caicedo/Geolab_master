"""
Reglas para convertir un proyecto de WordPress en Constructora + Obra normalizadas.

Problemas del origen que se corrigen aquí (ver memoria/CLAUDE.md):
- codigo-cliente_743 suele ser el código de EMPRESA ("BUC 46") pero a veces
  trae el de OBRA ("IBA13-1"): la empresa es prefijo + primer número (IBA13).
- Los "0-N" son clientes varios: cada N es una empresa distinta, identificada
  por el código completo ("BUC0-12") y su razón social.
- post_title / codigo-proyecto es el código de obra ("BUC 46-9", "BUC 25--2",
  "BOG0-2"): se deja como PREFIJO+N-M sin espacios ("BUC46-9").
- nombre-proyecto es el nombre real de la obra; municipio va en minúscula.
"""

import re
from collections import Counter

from users.ciudades import CIUDADES, normalizar_ciudad

_PREFIJOS = tuple(CIUDADES.values())           # ('BUC', 'BOG', 'IBA')
_RE_CLIENTE = re.compile(r'^(?P<pref>[A-Z]{3})?-?(?P<num>\d+)(?:-(?P<sub>\d+))?$')
_RE_OBRA = re.compile(r'^(?P<pref>[A-Z]{3})?-?(?P<num>\d+)-(?P<sub>\d+)(?P<letra>[A-Z]?)$')


def _compacto(texto):
    return re.sub(r'\s+|_', '', (texto or '').upper()).replace('--', '-')


def prefijo_de(ciudad):
    """'Bucaramanga' -> 'BUC' (ciudad ya normalizada). '' si no es sede conocida."""
    return CIUDADES.get(ciudad, '')


def clave_constructora(proyecto):
    """
    Devuelve (codigo, es_cliente_varios) o (None, None) si el proyecto es basura.
      "BUC 46"  -> ("BUC46", False)      "IBA13-1" -> ("IBA13", False)
      "BUC 0-12"-> ("BUC0-12", True)     "0-22" + municipio bucaramanga -> ("BUC0-22", True)
    """
    raw = _compacto(proyecto.m('codigo-cliente_743'))
    m = _RE_CLIENTE.match(raw)
    if not m or (m.group('pref') and m.group('pref') not in _PREFIJOS):
        return None, None
    ciudad = normalizar_ciudad(proyecto.m('municipio'))
    pref = m.group('pref') or prefijo_de(ciudad)
    if m.group('num') == '0':
        return f"{pref}0-{m.group('sub') or '0'}", True
    return f"{pref}{int(m.group('num'))}", False


def codigo_obra(proyecto, codigo_constructora):
    """
    Código real de la obra: codigo-proyecto o, si falta, post_title, compactados.
    Si no tiene forma de código devuelve None (el llamador decide el respaldo).
    """
    for fuente in (proyecto.m('codigo-proyecto'), proyecto.titulo):
        c = _compacto(fuente)
        m = _RE_OBRA.match(c)
        if not m:
            continue
        pref = m.group('pref') or re.match(r'[A-Z]*', codigo_constructora).group()
        return f"{pref}{int(m.group('num'))}-{int(m.group('sub'))}{m.group('letra')}"
    return None


def nombre_obra(proyecto):
    nombre = proyecto.m('nombre-proyecto')
    return re.sub(r'\s+', ' ', nombre).strip(" '\"") or proyecto.titulo.strip()


def razon_social_canonica(razones):
    """
    Entre variantes de una misma empresa ("MARVAL S.A.S", "MARVAL SAS") elige la
    más frecuente; en empate, la más larga. Quita comillas y espacios sobrantes.
    """
    limpias = [re.sub(r'\s+', ' ', r).strip(" '\"") for r in razones if r and r.strip(" '\"")]
    if not limpias:
        return ''
    conteo = Counter(limpias)
    return max(conteo, key=lambda r: (conteo[r], len(r)))


def ciudad_obra(proyecto):
    return normalizar_ciudad(proyecto.m('municipio')) or ''
