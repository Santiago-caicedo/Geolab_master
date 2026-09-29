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
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

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


_PALABRAS_VACIAS = {
    'SA', 'SAS', 'LTDA', 'LTA', 'CIA', 'COMPANIA', 'CONSTRUCTORA', 'CONSTRUCCIONES',
    'CONSORCIO', 'UNION', 'TEMPORAL', 'INGENIEROS', 'INGENIERIA', 'DE', 'LA', 'EL', 'Y',
    'DEL', 'LOS', 'LAS', 'GRUPO', 'PROYECTOS', 'URBANIZADORA', 'DESARROLLOS', 'OBRAS',
    'SOLUCIONES', 'SERVICIOS',
}


def _tokens_empresa(razon):
    s = unicodedata.normalize('NFKD', (razon or '').upper()).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return [w for w in s.split() if len(w) >= 3 and w not in _PALABRAS_VACIAS and not w.isdigit()]


def misma_empresa(razon_a, razon_b):
    """
    ¿Dos razones sociales son variantes de la misma empresa?
      "MARVAL SAS" ~ "MARVAL S.A.S"            -> True (mismo nombre significativo)
      "PRABYC INGENIEROS SAS" ~ "PRAVYC ..."   -> True (parecido > 0.8)
      "ASFALTEMOS" ~ "UNION TEMPORAL AP COELLO"-> False
    Regla: comparten alguna palabra significativa, o el texto significativo
    se parece más de 0.8. Sirve para detectar códigos de cliente reutilizados
    en WordPress para empresas distintas.
    """
    ta, tb = _tokens_empresa(razon_a), _tokens_empresa(razon_b)
    if not ta or not tb:
        return _tokens_empresa(razon_a) == _tokens_empresa(razon_b)
    if set(ta) & set(tb):
        return True
    return SequenceMatcher(None, ' '.join(ta), ' '.join(tb)).ratio() > 0.8


def agrupar_por_empresa(proyectos):
    """
    Divide los proyectos de un mismo código de cliente en grupos de empresa
    real (lista de listas), en orden de aparición (fecha del primer proyecto).
    Un proyecto entra en el primer grupo cuya razón social sea la misma empresa.
    """
    grupos = []
    for p in proyectos:
        razon = p.m('razon-social')
        for g in grupos:
            if any(misma_empresa(razon, q.m('razon-social')) for q in g):
                g.append(p)
                break
        else:
            grupos.append([p])
    return grupos
