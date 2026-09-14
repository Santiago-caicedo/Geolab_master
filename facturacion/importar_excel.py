"""
Lectura de la hoja "LISTA DE PRECIO" de los libros BASE DATOS <CIUDAD>.xlsm.

La hoja tiene una fila por servicio (ÍTEM, DESCRIPCIÓN, NORMA, PRECIO LISTA,
DESCUENTO) y, a partir de la columna F, una columna por obra cuyo encabezado
es el código de obra del Excel ("8-1" = empresa 8, obra 1) con el precio
pactado para esa obra. Las filas cuyo ÍTEM no tiene guion y cuya DESCRIPCIÓN
va en mayúsculas son encabezados de categoría.

Limpieza aplicada (la misma que se usó para generar catalogo_bucaramanga.py):
- Separadores de código normalizados a guion ("2.11" -> "2-11", "11,1,1L" -> "11-1-1L").
- Código cuyo primer segmento no es el número de la categoría pero empieza por
  él ("13-8" dentro de CONCRETOS) se corrige reinsertando el guion ("1-3-8").
- Filas con el mismo nombre dentro de una categoría se fusionan (normas unidas
  con " / "; los precios de la fila descartada rellenan los huecos de la conservada).
- Nombres repetidos entre categorías reciben sufijo: "(Laboratorista)",
  "(Auxiliar)", "(Laboratorista mes)" o "(cód. X)".
- Códigos repetidos con distinto nombre reciben sufijo "-2", "-3", ...
- Norma "N/A" o vacía se guarda como cadena vacía. Precios <= 0 se ignoran.

Se usa desde `python manage.py importar_catalogo_excel`.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from core.models import Obra
from users.ciudades import CIUDADES
from users.models import Constructora

HOJA_PRECIOS = 'LISTA DE PRECIO'
HOJA_NOMBRES_OBRAS = 'LISTA EMPRESAS REGULARES'
PRIMERA_COL_OBRA = 5          # columna F
FILA_ENCABEZADO = 3           # índice 0 -> fila 4 de Excel (la fila 3 es igual pero con celdas "0")
SUFIJO_CATEGORIA = {'11L': 'Laboratorista', '11A': 'Auxiliar', '11B': 'Laboratorista mes'}
_CODIGO_OBRA = re.compile(r'^\d+-\d+$')


@dataclass
class ServicioExcel:
    fila: int
    categoria: str
    codigo: str
    nombre: str
    norma: str
    precio_lista: Decimal | None
    precios: dict = field(default_factory=dict)   # codigo_obra_excel -> Decimal


@dataclass
class LecturaExcel:
    categorias: list            # [(codigo, nombre)]
    servicios: list             # [ServicioExcel]
    obras: list                 # códigos de obra del Excel, en orden de columna
    nombres_obras: dict         # codigo_obra -> nombre proyecto (si la hoja existe)
    nombres_empresas: dict      # codigo_empresa -> razón social
    log: list                   # decisiones de limpieza, en texto


def _norm(texto):
    return re.sub(r'\s+', ' ', str(texto).replace('\xa0', ' ')).strip()


def _codigo(texto):
    return re.sub(r'[,.]', '-', _norm(texto)).replace(' ', '')


def _corregir_prefijo(codigo, categoria):
    """
    Error de digitación frecuente: dentro de la categoría "1" aparece "13-8"
    (falta el guion: es "1-3-8"). Si el primer segmento del código no es el
    número de la categoría pero empieza por él, se reinserta el guion.
    """
    m = re.match(r'\d+', categoria)
    if not m:
        return codigo
    num_cat = m.group()
    primero, sep, resto = codigo.partition('-')
    if primero.isdigit() and primero != num_cat and primero.startswith(num_cat) and len(primero) > len(num_cat):
        return f'{num_cat}-{primero[len(num_cat):]}' + (sep + resto if sep else '')
    return codigo


def _unir_normas(a, b):
    """'NTC 176 / INV E 223' sin repetir partes: une por ' / ' y deduplica."""
    partes = []
    for trozo in f'{a} / {b}'.split('/'):
        trozo = trozo.strip()
        if trozo and trozo not in partes:
            partes.append(trozo)
    return ' / '.join(partes)


def _decimal(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return None
    d = Decimal(str(valor))
    return d if d > 0 else None


def leer_lista_precios(ruta, hoja=HOJA_PRECIOS):
    """Lee el libro y devuelve una LecturaExcel ya limpia."""
    import openpyxl  # import tardío: solo hace falta al importar

    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    if hoja not in wb.sheetnames:
        raise ValueError(f'El libro no tiene la hoja "{hoja}". Hojas: {wb.sheetnames}')
    filas = list(wb[hoja].iter_rows(values_only=True))
    log = []

    # ── columnas de obra ────────────────────────────────────────────────
    encabezado = filas[FILA_ENCABEZADO]
    respaldo = filas[FILA_ENCABEZADO - 1] if FILA_ENCABEZADO else ()
    columnas = []                      # [(indice_columna, codigo_obra)]
    for j in range(PRIMERA_COL_OBRA, len(encabezado)):
        celda = encabezado[j] if encabezado[j] not in (None, '', 0) else (respaldo[j] if j < len(respaldo) else None)
        if celda in (None, '', 0):
            continue
        cod = _codigo(celda)
        if _CODIGO_OBRA.match(cod):
            columnas.append((j, cod))
    repetidas = [c for c, n in Counter(c for _, c in columnas).items() if n > 1]
    for c in repetidas:
        log.append(f'columna de obra "{c}" aparece más de una vez: se toma el primer precio no vacío')

    # ── categorías y servicios ──────────────────────────────────────────
    categorias, servicios, cat = [], [], None
    for i, fila in enumerate(filas[FILA_ENCABEZADO + 1:], FILA_ENCABEZADO + 2):
        item, desc = fila[0], fila[1] if len(fila) > 1 else None
        if item is None and desc is None:
            continue
        item = _norm(item) if item is not None else ''
        desc = _norm(desc) if desc else ''
        if not item or not desc:
            continue
        norma = fila[2] if len(fila) > 2 else None
        precio_lista = fila[3] if len(fila) > 3 else None
        if '-' not in item and desc.isupper() and norma is None and precio_lista is None:
            cat = _codigo(item)
            categorias.append((cat, desc))
            continue
        if cat is None:
            log.append(f'fila {i}: servicio "{item}" antes de la primera categoría, omitido')
            continue
        codigo = _corregir_prefijo(_codigo(item), cat)
        if codigo != item.replace(' ', ''):
            log.append(f'fila {i}: código "{item}" -> "{codigo}"')
        s = ServicioExcel(
            fila=i, categoria=cat, codigo=codigo, nombre=desc,
            norma='' if norma in (None, 'N/A') else _norm(norma),
            precio_lista=_decimal(precio_lista),
        )
        for j, cod_obra in columnas:
            valor = _decimal(fila[j]) if j < len(fila) else None
            if valor is not None and cod_obra not in s.precios:
                s.precios[cod_obra] = valor
        servicios.append(s)

    # ── 1) mismo nombre: fusionar dentro de la categoría, sufijo entre categorías
    por_nombre, finales = {}, []
    for s in servicios:
        clave = s.nombre.lower()
        previo = por_nombre.get(clave)
        if previo is not None:
            if previo.categoria == s.categoria:
                previo.norma = _unir_normas(previo.norma, s.norma)
                for cod_obra, valor in s.precios.items():
                    previo.precios.setdefault(cod_obra, valor)
                log.append(f'fila {s.fila}: "{s.codigo}" omitido, mismo nombre que "{previo.codigo}" (normas y precios fusionados)')
                continue
            sufijo = SUFIJO_CATEGORIA.get(s.categoria) or f'cód. {s.codigo}'
            log.append(f'fila {s.fila}: "{s.codigo}" renombrado con sufijo "({sufijo})" por chocar con "{previo.codigo}" de otra categoría')
            s.nombre = f'{s.nombre} ({sufijo})'
        por_nombre[s.nombre.lower()] = s
        finales.append(s)

    # ── 2) mismo código con distinto nombre: sufijo -2, -3, ...
    vistos = Counter()
    for s in finales:
        vistos[s.codigo] += 1
        if vistos[s.codigo] > 1:
            nuevo = f'{s.codigo}-{vistos[s.codigo]}'
            log.append(f'fila {s.fila}: código "{s.codigo}" repetido con otro nombre -> "{nuevo}"')
            s.codigo = nuevo

    for s in finales:
        s.norma = s.norma[:100]
        s.nombre = s.nombre[:255]

    nombres_obras, nombres_empresas = _leer_nombres(wb)
    obras = []
    for _, cod in columnas:
        if cod not in obras:
            obras.append(cod)
    return LecturaExcel(categorias, finales, obras, nombres_obras, nombres_empresas, log)


def _leer_nombres(wb):
    """Hoja LISTA EMPRESAS REGULARES: fila 1 = (cod_empresa, razón social)..., fila 2 = (cod_obra, proyecto)..."""
    if HOJA_NOMBRES_OBRAS not in wb.sheetnames:
        return {}, {}
    filas = list(wb[HOJA_NOMBRES_OBRAS].iter_rows(values_only=True, max_row=2))
    def pares(fila):
        celdas = [c for c in fila if c is not None]
        out = {}
        for k in range(0, len(celdas) - 1, 2):
            cod, nombre = _codigo(celdas[k]), _norm(celdas[k + 1])
            if nombre and not nombre.startswith('Columna'):
                out[cod] = nombre
        return out
    empresas = pares(filas[0]) if filas else {}
    obras = pares(filas[1]) if len(filas) > 1 else {}
    return obras, empresas


# ═══════════════════════════════════════════════════════════════════════════
# Resolución de obras del Excel -> Obra del sistema
# ═══════════════════════════════════════════════════════════════════════════

def resolver_obra(ciudad, codigo_excel, lectura, overrides=None):
    """
    Devuelve (obra, motivo, candidatas). obra es None si no se pudo resolver.

    Orden de búsqueda:
    1. --obra CODIGO_EXCEL=CODIGO_OBRA pasado por el usuario.
    2. Constructora de la ciudad con código IBA8 / 8 / IBA-8 (prefijo de la
       ciudad + número de empresa) o con la razón social del Excel; dentro de
       ella, obra con codigo_obra IBA8-1 / 8-1, o con el nombre del proyecto
       del Excel, o la única obra que tenga.
    """
    overrides = overrides or {}
    if codigo_excel in overrides:
        obra = Obra.objects.filter(
            codigo_obra__iexact=overrides[codigo_excel], constructora__ciudad__iexact=ciudad,
        ).select_related('constructora').first()
        return obra, ('--obra' if obra else f'--obra: no existe "{overrides[codigo_excel]}" en {ciudad}'), []

    emp, _, num = codigo_excel.partition('-')
    prefijo = CIUDADES.get(ciudad, '')
    codigos_emp = {f'{prefijo}{emp}', emp, f'{prefijo}-{emp}', f'{prefijo}{emp.zfill(2)}'}
    filtro = Q(codigo__in=codigos_emp)
    razon = lectura.nombres_empresas.get(emp)
    if razon:
        filtro |= Q(nombre__iexact=razon)
    constructoras = list(Constructora.objects.filter(filtro, ciudad__iexact=ciudad))
    if not constructoras:
        return None, f'ninguna constructora en {ciudad} con código {", ".join(sorted(codigos_emp))}' + (f' ni razón social "{razon}"' if razon else ''), []

    proyecto = lectura.nombres_obras.get(codigo_excel)
    candidatas = []
    for c in constructoras:
        obras = list(Obra.objects.filter(constructora=c))
        candidatas.extend(obras)
        codigos_obra = {f'{c.codigo}-{num}', codigo_excel, f'{prefijo}{codigo_excel}'}
        for o in obras:
            if o.codigo_obra.upper() in {x.upper() for x in codigos_obra}:
                return o, f'código de obra {o.codigo_obra}', candidatas
        if proyecto:
            for o in obras:
                if o.nombre.strip().lower() == proyecto.lower():
                    return o, f'nombre de proyecto "{proyecto}"', candidatas
        if len(obras) == 1:
            return obras[0], f'única obra de {c.nombre}', candidatas
    return None, f'{constructoras[0].nombre} tiene {len(candidatas)} obras y ninguna coincide (use --obra {codigo_excel}=CODIGO_OBRA)', candidatas
