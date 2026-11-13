"""
Informes repetidos: el mismo PDF subido a mano en el portal y traído también de WordPress.

El laboratorio sube los informes a los dos lados mientras WordPress siga vivo. La copia que
trae `sincronizar_wordpress` tiene `id_wp_original`; la que se subió en el portal no. Los
títulos no son idénticos (WordPress cambia espacios por guiones y el sync deja el `.pdf`):
'INF 4884-2026 COMPRESION CILINDROS.xlsx' = 'INF-4884-2026-COMPRESION-CILINDROS.xlsx.pdf'.
Por eso se comparan con `clave_titulo`.
"""

import re
import unicodedata
from dataclasses import dataclass

from .models import Informe

_EXTENSION = re.compile(r'\.(pdf|xlsx|xlsm|xls|docx|doc)$')


def clave_titulo(titulo):
    """Título -> clave de comparación: sin tildes, sin extensiones, solo letras y números."""
    t = unicodedata.normalize('NFKD', titulo or '').encode('ascii', 'ignore').decode().lower().strip()
    while _EXTENSION.search(t):
        t = _EXTENSION.sub('', t).strip()
    return re.sub(r'[^a-z0-9]', '', t)


def claves_manuales():
    """Claves de los informes subidos en el portal: {(obra_pk, clave)} y {(constructora_pk, codigo_obra, clave)}."""
    por_obra, por_codigo = set(), set()
    for obra_id, constructora_id, codigo, titulo in Informe.objects.filter(id_wp_original__isnull=True).values_list(
            'obra_id', 'obra__constructora_id', 'obra__codigo_obra', 'titulo'):
        clave = clave_titulo(titulo)
        if clave:
            por_obra.add((obra_id, clave))
            if codigo:
                por_codigo.add((constructora_id, codigo, clave))
    return por_obra, por_codigo


@dataclass
class Par:
    copia: Informe      # la traída de WordPress (la que sobra)
    manual: Informe     # la que subió el laboratorio en el portal (se conserva)
    tipo: str           # 'misma_obra' | 'obra_gemela' (mismo código de obra) | 'otra_obra' (solo se avisa)


def buscar_duplicados():
    """Copias de WordPress cuyo informe ya estaba subido a mano. Una lista de `Par`."""
    manuales = list(Informe.objects.filter(id_wp_original__isnull=True).select_related('obra'))
    por_obra, por_codigo, por_empresa = {}, {}, {}
    for m in manuales:
        clave = clave_titulo(m.titulo)
        if not clave:
            continue
        por_obra.setdefault((m.obra_id, clave), m)
        if m.obra.codigo_obra:
            por_codigo.setdefault((m.obra.constructora_id, m.obra.codigo_obra, clave), m)
        por_empresa.setdefault((m.obra.constructora_id, clave), m)

    empresas = {m.obra.constructora_id for m in manuales}
    pares = []
    copias = (Informe.objects.filter(id_wp_original__isnull=False, obra__constructora_id__in=empresas)
              .select_related('obra', 'obra__constructora').order_by('obra__codigo_obra', 'titulo'))
    for c in copias:
        clave = clave_titulo(c.titulo)
        if not clave:
            continue
        if (c.obra_id, clave) in por_obra:
            pares.append(Par(c, por_obra[(c.obra_id, clave)], 'misma_obra'))
        elif (c.obra.constructora_id, c.obra.codigo_obra, clave) in por_codigo:
            pares.append(Par(c, por_codigo[(c.obra.constructora_id, c.obra.codigo_obra, clave)], 'obra_gemela'))
        elif (c.obra.constructora_id, clave) in por_empresa:
            pares.append(Par(c, por_empresa[(c.obra.constructora_id, clave)], 'otra_obra'))
    return pares
