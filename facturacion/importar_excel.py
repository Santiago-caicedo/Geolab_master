"""
Lectura de la hoja "LISTA DE PRECIO" de los libros BASE DATOS <CIUDAD>.xlsm.

La hoja tiene una fila por servicio (ÍTEM, DESCRIPCIÓN, NORMA, PRECIO LISTA y,
en Bucaramanga e Ibagué, DESCUENTO) y después una columna por obra cuyo
encabezado es el código de obra del Excel ("8-1" = empresa 8, obra 1) con el
precio pactado para esa obra. Las columnas de obra se detectan por su
encabezado (Bogotá no tiene DESCUENTO y empiezan una columna antes).
Los códigos "0-N" son clientes varios: cada N es una empresa distinta, que
en el portal se llama BOG0-N (constructora y obra), con nombre en la hoja
LISTA EMPRESAS VARIOS OBRAS. Las filas cuyo ÍTEM no tiene guion y cuya DESCRIPCIÓN
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
from core.wp_normalizar import _tokens_empresa, misma_empresa
from users.ciudades import CIUDADES, normalizar_ciudad
from users.models import Constructora

HOJA_PRECIOS = 'LISTA DE PRECIO'
HOJA_NOMBRES_OBRAS = 'LISTA EMPRESAS REGULARES'
HOJA_NOMBRES_VARIOS = 'LISTA EMPRESAS VARIOS OBRAS'
HOJA_CLIENTES = 'CLIENTES'          # F-GC-01: C.C | RAZÓN SOCIAL | ...
HOJA_OBRAS = 'OBRAS'                # F-GC-01: RAZÓN SOCIAL | COD EMP | COD OBRA | NOMBRE PROYECTO
PRIMERA_COL_OBRA = 4          # columna E (DESCUENTO, si existe, no parece código y se salta)
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
    try:
        return _leer_libro(wb, hoja)
    finally:
        wb.close()   # en Windows un libro abierto deja el archivo bloqueado


def _leer_libro(wb, hoja):
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
        elif cod.upper().strip() not in ('DESCUENTO', 'PRECIO LISTA'):
            log.append(f'columna {j + 1}: el encabezado "{cod}" no es un código de obra (empresa-obra): se omite')
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
    # Clientes varios: una fila por (código, texto); la primera vez es la razón social y la segunda el proyecto
    if HOJA_NOMBRES_VARIOS in wb.sheetnames:
        for fila in wb[HOJA_NOMBRES_VARIOS].iter_rows(values_only=True):
            celdas = [c for c in fila if c not in (None, '')]
            if len(celdas) < 2:
                continue
            cod, texto = _codigo(celdas[0]), _norm(celdas[1])
            if not _CODIGO_OBRA.match(cod) or not texto or texto.startswith('Columna'):
                continue
            if cod not in empresas:
                empresas[cod] = texto
            elif cod not in obras and texto.lower() != empresas[cod].lower():
                obras[cod] = texto
    # Hojas del formato F-GC-01: traen razones sociales que las listas no tienen (SIKA, VALU...)
    if HOJA_CLIENTES in wb.sheetnames:
        for fila in wb[HOJA_CLIENTES].iter_rows(values_only=True):
            if not fila or fila[0] in (None, '') or len(fila) < 2 or fila[1] in (None, ''):
                continue
            cod, nombre = _codigo(fila[0]), _norm(fila[1])
            if cod.isdigit() and nombre and cod not in empresas:
                empresas[cod] = nombre
    if HOJA_OBRAS in wb.sheetnames:
        for fila in wb[HOJA_OBRAS].iter_rows(values_only=True):
            celdas = [c for c in fila if c not in (None, '')]
            if len(celdas) < 4:
                continue
            cod_obra, proyecto = _codigo(celdas[2]), _norm(celdas[3])
            if _CODIGO_OBRA.match(cod_obra) and proyecto and cod_obra not in obras and proyecto != cod_obra:
                obras[cod_obra] = proyecto
    return obras, empresas


# ═══════════════════════════════════════════════════════════════════════════
# Resolución de obras del Excel -> Obra del sistema
# ═══════════════════════════════════════════════════════════════════════════

class SinCrear(list):
    """Candidatas de una columna que el usuario debe confirmar con --obra: --crear-obras no debe inventar nada."""


def _afinidad(razon, nombre):
    """Palabras significativas compartidas entre dos razones sociales (0 = nada que ver)."""
    return len(set(_tokens_empresa(razon)) & set(_tokens_empresa(nombre)))


def _misma_fuerte(razon, nombre):
    """
    Coincidencia fuerte: dos palabras significativas en común, o una cuando alguno de los
    nombres solo tiene una ("ASFALTEMOS"). Una sola palabra compartida entre nombres largos
    ("ARENAS Y GRAVAS DE COLOMBIA" ~ "SIKA COLOMBIA") NO cuenta: sirve para detectar códigos
    reutilizados sin inventar parecidos.
    """
    a, b = set(_tokens_empresa(razon)), set(_tokens_empresa(nombre))
    comunes = len(a & b)
    return comunes >= 2 or (comunes == 1 and min(len(a), len(b)) == 1)


def _clave_obra(nombre):
    """
    "IBA 14-1", "IBA14-1", "iba 14 - 1" -> "14-1". Las obras migradas desde
    WordPress se llaman así (el código del Excel con el prefijo de la ciudad).
    """
    s = _norm(nombre).upper().replace(' ', '')
    for prefijo in CIUDADES.values():
        if s.startswith(prefijo):
            s = s[len(prefijo):]
            break
    return s.lstrip('-')


def resolver_obra(ciudad, codigo_excel, lectura, overrides=None, columnas_de_la_empresa=None):
    """
    Devuelve (obra, motivo, candidatas). obra es None si no se pudo resolver.

    Orden de búsqueda:
    1. --obra CODIGO_EXCEL=CODIGO_OBRA pasado por el usuario.
    2. Constructora de la ciudad con código IBA8 / 8 / IBA-8 (prefijo de la
       ciudad + número de empresa) o con la razón social del Excel; dentro de
       ella, la obra cuyo codigo_obra es IBA8-1 / 8-1, o cuyo NOMBRE es el
       código del Excel ("IBA 8-1"), o cuyo nombre es el proyecto del Excel.
    3. Si la constructora tiene una sola obra y el Excel también tiene una
       sola columna para esa empresa, se asume que es esa (motivo "supuesto").
    """
    overrides = overrides or {}
    if codigo_excel in overrides:
        obra = Obra.objects.filter(
            codigo_obra__iexact=overrides[codigo_excel], constructora__ciudad__iexact=ciudad,
        ).select_related('constructora').first()
        return obra, ('--obra' if obra else f'--obra: no existe "{overrides[codigo_excel]}" en {ciudad}'), []

    emp, _, num = codigo_excel.partition('-')
    prefijo = CIUDADES.get(ciudad, '')
    if emp == '0':
        return _resolver_varios(ciudad, codigo_excel, lectura, prefijo)
    codigos_emp = {f'{prefijo}{emp}', emp, f'{prefijo}-{emp}', f'{prefijo}{emp.zfill(2)}'}
    razon = lectura.nombres_empresas.get(emp)
    constructoras = _constructoras_de(ciudad, codigos_emp, razon)
    if not constructoras:
        return None, f'ninguna constructora en {ciudad} con código {", ".join(sorted(codigos_emp))}' + (f' ni razón social "{razon}"' if razon else ''), []

    # El código manda sobre la razón social (en WordPress hay razones mal capturadas), SALVO
    # que la razón social del Excel sea claramente la de OTRA empresa que sí existe en la sede:
    # entonces es un código reutilizado y no se asigna solo.
    if razon and not any(_es(razon, c) for c in constructoras):
        ajenas = Constructora.objects.filter(ciudad__iexact=ciudad).exclude(pk__in=[c.pk for c in constructoras])
        otra = max((c for c in ajenas if _misma_fuerte(razon, c.nombre)), key=lambda c: _afinidad(razon, c.nombre), default=None)
        if otra:
            cand = SinCrear(Obra.objects.filter(constructora__in=constructoras + [otra]).select_related('constructora').order_by('codigo_obra'))
            return None, (f'el Excel dice que la empresa {emp} es "{razon}", que en el portal es {otra.codigo} "{otra.nombre[:30]}", '
                          f'pero el código {constructoras[0].codigo} es de "{constructoras[0].nombre[:30]}": '
                          f'confirmar con --obra {codigo_excel}=CODIGO_OBRA'), cand

    proyecto = lectura.nombres_obras.get(codigo_excel)
    codigos_obra = {x.upper() for x in (codigo_excel, f'{prefijo}{codigo_excel}')} | {f'{c.codigo}-{num}'.upper() for c in constructoras}
    candidatas = list(Obra.objects.filter(constructora__in=constructoras).select_related('constructora').order_by('codigo_obra'))

    # 1) Obra con el código exacto, buscada en todas las empresas que comparten el código
    #    (BOG1-13 cuelga de BOG1B). Si hay dos con el mismo código (BUC25-2 en BUC25 y BUC25B),
    #    la razón social del Excel decide; si no decide, no se asigna.
    por_codigo = [o for o in candidatas if o.codigo_obra.upper() in codigos_obra]
    if len(por_codigo) > 1 and razon:
        por_codigo = [o for o in por_codigo if _es(razon, o.constructora)] or por_codigo
    if len(por_codigo) == 1:
        o = por_codigo[0]
        # La obra está bajo una empresa hermana (mismo código con sufijo) y el Excel nombra a la OTRA
        # hermana: puede ser una obra distinta con el mismo número. Se confirma.
        if razon and len(constructoras) > 1 and not _es(razon, o.constructora) and any(_es(razon, c) for c in constructoras):
            duena = next(c for c in constructoras if _es(razon, c))
            return None, (f'la obra {o.codigo_obra} está en {o.constructora.codigo} "{o.constructora.nombre[:26]}" pero el Excel dice que '
                          f'{codigo_excel} es de "{razon}" ({duena.codigo}): use --obra {codigo_excel}={o.codigo_obra} si es la misma, '
                          f'o --crear-obras tras confirmar'), SinCrear(candidatas)
        aviso = '' if not razon or _es(razon, o.constructora) else f' ⚠ el Excel llama "{razon}" a esta empresa'
        return o, f'código de obra {o.codigo_obra}' + (f' (en {o.constructora.codigo} {o.constructora.nombre[:30]})' if len(constructoras) > 1 else '') + aviso, candidatas
    if len(por_codigo) > 1:
        quienes = ' / '.join(f'{o.constructora.codigo} "{o.constructora.nombre[:26]}" ({o.nombre[:24]})' for o in por_codigo)
        return None, (f'hay {len(por_codigo)} obras con el código {codigo_excel}: {quienes}; el Excel '
                      + (f'dice "{razon}" y no decide' if razon else 'no trae la razón social')
                      + f'. Use --obra {codigo_excel}=CODIGO_OBRA'), SinCrear(por_codigo)

    # 2) Sin obra por código: si el código de empresa lo comparten varias, la razón social decide
    if len(constructoras) > 1:
        afines = [c for c in constructoras if razon and _es(razon, c)]
        if len(afines) == 1:
            constructoras = afines
            candidatas = [o for o in candidatas if o.constructora_id == afines[0].pk]
        else:
            quienes = ' / '.join(f'{c.codigo} "{c.nombre[:28]}"' for c in constructoras)
            return None, (f'el código {emp} lo comparten {quienes} y el Excel '
                          + (f'dice "{razon}", que no decide' if razon else 'no trae la razón social')
                          + f': use --obra {codigo_excel}=CODIGO_OBRA'), SinCrear(candidatas)

    for c in constructoras:
        obras = [o for o in candidatas if o.constructora_id == c.pk]
        aviso = '' if not razon or _es(razon, c) else f' ⚠ el Excel llama "{razon}" a esta empresa'
        for o in obras:
            if _clave_obra(o.nombre) == codigo_excel:
                return o, f'nombre de obra "{o.nombre}"{aviso}', candidatas
        if proyecto:
            for o in obras:
                if o.nombre.strip().lower() == proyecto.lower():
                    return o, f'nombre de proyecto "{proyecto}"{aviso}', candidatas
    if len(candidatas) == 1 and (columnas_de_la_empresa or 1) == 1:
        return candidatas[0], f'única obra de {candidatas[0].constructora.nombre} y única columna de la empresa en el Excel (supuesto)', candidatas
    n_cols = columnas_de_la_empresa or 1
    if len(candidatas) == 0:
        return None, f'{constructoras[0].nombre} no tiene obras en el sistema (use --crear-obras o --obra {codigo_excel}=CODIGO_OBRA)', candidatas
    return None, (
        f'{constructoras[0].nombre} tiene {len(candidatas)} obra(s) en el sistema y el Excel {n_cols} columna(s); '
        f'ninguna se llama "{prefijo} {codigo_excel}" (use --crear-obras o --obra {codigo_excel}=CODIGO_OBRA)'
    ), candidatas


def _resolver_varios(ciudad, codigo_excel, lectura, prefijo):
    """
    "0-10" es el cliente varios número 10: en el portal su constructora y su obra
    se llaman BOG0-10 (a veces la constructora lleva sufijo B, o la obra cuelga
    de otra constructora pero conserva el código). Si hay varias obras con el
    código (WordPress lo reutilizó), desempata la razón social del Excel.
    """
    cod = f'{prefijo}{codigo_excel}'
    razon = lectura.nombres_empresas.get(codigo_excel)
    obras = list(
        Obra.objects.filter(constructora__ciudad__iexact=ciudad).filter(
            Q(codigo_obra__iexact=cod)
            | Q(codigo_obra__iregex=rf'^{re.escape(cod)}-\d+$')
            | Q(constructora__codigo__iregex=rf'^{re.escape(cod)}[A-Z]?$')
        ).select_related('constructora').distinct().order_by('codigo_obra')
    )
    excel = f' (el Excel lo llama "{razon}")' if razon else ' (el Excel no trae su nombre)'
    if not obras:
        ajena = Constructora.objects.filter(codigo__iexact=cod).exclude(ciudad__iexact=ciudad).first()
        if ajena:
            return None, (f'el código {cod} ya lo tiene "{ajena.nombre}" en {ajena.ciudad or "sin ciudad"}{excel}: '
                          f'corrige la ciudad de esa empresa o use --obra {codigo_excel}=CODIGO_OBRA'), []
        if not razon:
            return None, f'ningún cliente varios {cod} en {ciudad}{excel}: sin nombre no se puede crear; use --obra {codigo_excel}=CODIGO_OBRA', []
        return None, f'ningún cliente varios {cod} en {ciudad}{excel}; use --crear-obras (crea empresa y obra) o --obra {codigo_excel}=CODIGO_OBRA', []
    if len(obras) == 1:
        o = obras[0]
        if razon and not (misma_empresa(razon, o.constructora.nombre) or misma_empresa(razon, o.nombre)):
            # Mismo número, otra empresa: cargar precios al cliente equivocado es un error de dinero.
            # No se asigna solo; el usuario confirma con --obra.
            return None, (f'el código {cod} es de "{o.constructora.nombre}" en el portal pero el Excel dice "{razon}" '
                          f'(¿número reutilizado?). Si es la misma empresa, use --obra {codigo_excel}={o.codigo_obra}'), obras
        return o, f'cliente varios {cod}', obras
    afines = obras
    if razon:
        afines = [o for o in obras if misma_empresa(razon, o.constructora.nombre) or misma_empresa(razon, o.nombre)]
        if len(afines) == 1:
            return afines[0], f'cliente varios {cod}, razón social "{razon}"', obras
    # Varias obras de la misma empresa (una vieja de WordPress "BOG012-602" y la vigente "BOG0-12"):
    # la que tiene exactamente el código del cliente varios es la buena.
    exactas = [o for o in afines if o.codigo_obra.upper() == cod.upper()]
    if razon and len(exactas) == 1:
        return exactas[0], f'cliente varios {cod}, razón social "{razon}" y código de obra exacto', obras
    # Con dudas no se crea otra obra (--crear-obras dejaría los precios en una obra vacía): se confirma con --obra
    return None, (
        f'{len(obras)} obras con el código {cod} en {ciudad}'
        + (f' y la razón social "{razon}" no desempata' if razon else excel)
        + f' (use --obra {codigo_excel}=CODIGO_OBRA)'
    ), SinCrear(obras)


def _es(razon, constructora):
    """¿La razón social del Excel es (una variante de) esta constructora?"""
    return misma_empresa(razon, constructora.nombre)


def _constructoras_de(ciudad, codigos_emp, razon):
    """
    El CÓDIGO manda: si hay constructora con ese código (IBA14), es esa aunque
    su razón social no coincida con el Excel (en WordPress hay razones sociales
    mal capturadas). La razón social solo se usa cuando ningún código coincide.
    Los sufijos B, C (códigos reutilizados) también cuentan como el mismo código.
    """
    base = Q(ciudad__iexact=ciudad)
    # IBA10 y sus sufijos IBA10B, IBA10C (código reutilizado en WordPress para otra
    # empresa) se consideran juntos: la obra "IBA10-1" puede estar en cualquiera.
    patron = r'^(' + '|'.join(sorted(codigos_emp)) + r')[A-Z]?$'
    por_codigo = list(Constructora.objects.filter(base, codigo__regex=patron).order_by('codigo'))
    if por_codigo:
        return por_codigo
    if razon:
        return list(Constructora.objects.filter(base, nombre__iexact=razon))
    return []


def constructora_de(ciudad, codigo_excel, lectura):
    """Constructora a la que pertenece una columna del Excel (o None). Misma regla que resolver_obra."""
    emp = codigo_excel.partition('-')[0]
    prefijo = CIUDADES.get(ciudad, '')
    if emp == '0':
        cod = f'{prefijo}{codigo_excel}'
        return Constructora.objects.filter(
            ciudad__iexact=ciudad, codigo__iregex=rf'^{re.escape(cod)}[A-Z]?$'
        ).order_by('codigo').first()
    codigos_emp = {f'{prefijo}{emp}', emp, f'{prefijo}-{emp}', f'{prefijo}{emp.zfill(2)}'}
    lista = _constructoras_de(ciudad, codigos_emp, lectura.nombres_empresas.get(emp))
    return lista[0] if lista else None


# ═══════════════════════════════════════════════════════════════════════════
# Lista de clientes activos (--activos)
# ═══════════════════════════════════════════════════════════════════════════
#
# El laboratorio confirma qué clientes están activos en cada sede; el resto de
# columnas del Excel son clientes viejos y NO se cargan. El archivo es un CSV
# con ";" (las líneas que empiezan por "#" son comentarios):
#
#   codigo;empresa;proyecto;empresa_portal;obra_portal;precios_de
#   27-1;CONSORCIO CONSULTECNICOS;DOBLE CALZADA;BUC27B;BUC27-1;
#   11-2;TINGUAS DE CANTOVAL SAS;PLAN PARCIAL 15;BOG11;BOG11-2;11-1
#
# - codigo: columna del Excel. Es la única columna obligatoria.
# - empresa / proyecto: lo que dice el laboratorio. El proyecto se usa como nombre
#   si la obra se crea; la empresa, como razón social si hay que crear la constructora.
# - empresa_portal + obra_portal: obra exacta del portal (van juntas, porque hay
#   códigos de obra repetidos entre empresas hermanas: BUC27-1 en BUC27 y BUC27B).
#   Si no existe y se pasa --crear-obras, se crea (y la constructora, si falta).
#   Vacías: la columna se resuelve como siempre (resolver_obra).
# - precios_de: otra columna del Excel cuyos precios se copian (misma lista de precios
#   para dos proyectos de la misma empresa). La columna `codigo` no debe existir en el Excel.

COLUMNAS_ACTIVOS = ('codigo', 'empresa', 'proyecto', 'empresa_portal', 'obra_portal', 'precios_de')


@dataclass
class ClienteActivo:
    codigo: str
    empresa: str = ''
    proyecto: str = ''
    empresa_portal: str = ''
    obra_portal: str = ''
    precios_de: str = ''


def leer_activos(ruta):
    """Lee el CSV de clientes activos -> {codigo_excel: ClienteActivo}. ValueError si está mal armado."""
    import csv
    with open(ruta, encoding='utf-8-sig', newline='') as f:
        lineas = [l for l in f if l.strip() and not l.lstrip().startswith('#')]
    lector = csv.DictReader(lineas, delimiter=';')
    encabezado = [(c or '').strip().lower() for c in (lector.fieldnames or [])]
    if 'codigo' not in encabezado or set(encabezado) - set(COLUMNAS_ACTIVOS):
        raise ValueError(f'{ruta}: el encabezado debe ser {";".join(COLUMNAS_ACTIVOS)} (recibí {";".join(encabezado)})')
    lector.fieldnames = encabezado
    activos = {}
    for n, fila in enumerate(lector, 2):
        datos = {k: _norm(v or '') for k, v in fila.items() if k in COLUMNAS_ACTIVOS}
        a = ClienteActivo(**datos)
        a.codigo, a.precios_de = _codigo(a.codigo), _codigo(a.precios_de)
        a.empresa_portal, a.obra_portal = a.empresa_portal.upper(), a.obra_portal.upper()
        if not _CODIGO_OBRA.match(a.codigo):
            raise ValueError(f'{ruta}, fila {n}: "{a.codigo}" no es un código de obra del Excel (empresa-obra)')
        if a.codigo in activos:
            raise ValueError(f'{ruta}, fila {n}: el código {a.codigo} está repetido')
        if bool(a.empresa_portal) != bool(a.obra_portal):
            raise ValueError(f'{ruta}, fila {n}: empresa_portal y obra_portal van juntas')
        if a.precios_de and not _CODIGO_OBRA.match(a.precios_de):
            raise ValueError(f'{ruta}, fila {n}: precios_de "{a.precios_de}" no es un código de obra del Excel')
        activos[a.codigo] = a
    return activos


def aplicar_activos(lectura, activos):
    """
    Deja en `lectura` solo las columnas de los clientes activos, copia los precios de
    `precios_de` y usa el proyecto del laboratorio como nombre de la obra.
    Devuelve (omitidas, faltantes): columnas del Excel que no están en la lista, y
    clientes de la lista que no tienen columna en el Excel (quedan sin precios).
    """
    for a in activos.values():
        if not a.precios_de:
            continue
        if a.codigo in lectura.obras:
            raise ValueError(f'{a.codigo} ya tiene columna en el Excel: no puede copiar los precios de {a.precios_de}')
        if a.precios_de not in lectura.obras:
            raise ValueError(f'{a.codigo} copia los precios de {a.precios_de}, que no es una columna del Excel')
        for s in lectura.servicios:
            if a.precios_de in s.precios:
                s.precios[a.codigo] = s.precios[a.precios_de]
        lectura.obras.insert(lectura.obras.index(a.precios_de) + 1, a.codigo)
    for a in activos.values():
        if a.proyecto:
            lectura.nombres_obras[a.codigo] = a.proyecto
    omitidas = [c for c in lectura.obras if c not in activos]
    faltantes = [c for c in activos if c not in lectura.obras]
    lectura.obras = [c for c in lectura.obras if c in activos]
    return omitidas, faltantes


def obra_de_activo(ciudad, activo, crear):
    """
    Obra fijada en la lista de activos (empresa_portal + obra_portal) -> (obra, motivo).
    Con `crear`, la crea si no existe; la constructora también, con la razón social del laboratorio.

    Los códigos de empresa cambian con WordPress (si un proyecto va a la papelera, BUC11B vuelve a
    ser BUC11), así que la razón social se verifica: la obra debe ser de esa empresa aunque el código
    de la lista haya quedado viejo, y nunca se crea un duplicado de una obra que ya existe.
    """
    mismo_codigo = list(Obra.objects.filter(
        constructora__ciudad__iexact=ciudad, codigo_obra__iexact=activo.obra_portal,
    ).select_related('constructora').order_by('pk'))
    propias = [o for o in mismo_codigo if not activo.empresa or _es(activo.empresa, o.constructora)]
    for o in propias:
        if o.constructora.codigo.upper() == activo.empresa_portal:
            return o, f'lista de activos ({activo.empresa_portal} / {activo.obra_portal})'
    if len(propias) == 1:
        o = propias[0]
        return o, f'lista de activos (la obra {o.codigo_obra} está en {o.constructora.codigo}, la lista decía {activo.empresa_portal})'
    if propias:
        return None, f'lista de activos: {len(propias)} obras {activo.obra_portal} de "{activo.empresa[:30]}"; corrija la lista'
    if mismo_codigo:
        quienes = ' / '.join(f'{o.constructora.codigo} "{o.constructora.nombre[:26]}"' for o in mismo_codigo)
        return None, f'lista de activos: la obra {activo.obra_portal} es de {quienes}, no de "{activo.empresa[:30]}"; corrija la lista'
    c = Constructora.objects.filter(codigo__iexact=activo.empresa_portal).first()
    if c is not None and normalizar_ciudad(c.ciudad or '') != normalizar_ciudad(ciudad):
        return None, f'lista de activos: la constructora {c.codigo} es de {c.ciudad or "ninguna ciudad"}, no de {ciudad}'
    if not crear:
        falta = 'la obra' if c else 'la constructora y la obra'
        return None, f'lista de activos: no existen {falta} {activo.empresa_portal} / {activo.obra_portal} (use --crear-obras)'
    nueva_empresa = c is None
    if nueva_empresa:
        if not activo.empresa:
            return None, f'lista de activos: no existe la constructora {activo.empresa_portal} y la lista no trae su razón social'
        c = Constructora.objects.create(codigo=activo.empresa_portal, nombre=activo.empresa, ciudad=ciudad)
    prefijo = CIUDADES.get(ciudad, '')
    nombre = activo.proyecto or f'{prefijo} {activo.codigo}'.strip()
    obra = Obra.objects.create(constructora=c, nombre=nombre[:255], codigo_obra=activo.obra_portal)
    return obra, ('empresa y obra CREADAS' if nueva_empresa else 'obra CREADA') + f' (lista de activos) bajo {c.codigo} {c.nombre[:30]}'


def crear_obra(ciudad, codigo_excel, lectura):
    """
    Crea la obra de una columna del Excel bajo su constructora, con la misma
    convención de las obras migradas: nombre "IBA 8-1" (o el proyecto del
    Excel si se conoce) y codigo_obra "IBA8-1". Devuelve None si no hay constructora.
    """
    c = constructora_de(ciudad, codigo_excel, lectura)
    prefijo = CIUDADES.get(ciudad, '')
    if codigo_excel.startswith('0-'):
        # Cliente varios nuevo: empresa + obra con el código del Excel, solo si el libro trae su nombre
        razon = lectura.nombres_empresas.get(codigo_excel)
        if c is not None and razon and not misma_empresa(razon, c.nombre):
            return None   # el número ya es de otra empresa: no se le cuelga una obra ajena (se confirma con --obra)
        if c is None:
            # Sin nombre no se inventa; y el código es único en todo el portal (otra ciudad lo bloquea)
            if not razon or Constructora.objects.filter(codigo__iexact=f'{prefijo}{codigo_excel}').exists():
                return None
            c = Constructora.objects.create(codigo=f'{prefijo}{codigo_excel}', nombre=razon, ciudad=ciudad)
        proyecto = lectura.nombres_obras.get(codigo_excel) or razon or c.nombre
        codigo_obra = f'{prefijo}{codigo_excel}'
        if Obra.objects.filter(codigo_obra__iexact=codigo_obra).exists():
            codigo_obra = f'{codigo_obra}-1'
        return Obra.objects.create(constructora=c, nombre=proyecto, codigo_obra=codigo_obra)
    if c is None:
        # Empresa que no está en WordPress: se crea solo si el libro trae su razón social
        # (hoja CLIENTES) y el código está libre en todo el portal
        emp = codigo_excel.partition('-')[0]
        razon = lectura.nombres_empresas.get(emp)
        codigo_emp = f'{prefijo}{emp}'
        if not razon or Constructora.objects.filter(codigo__iexact=codigo_emp).exists():
            return None
        c = Constructora.objects.create(codigo=codigo_emp, nombre=razon, ciudad=ciudad)
    num = codigo_excel.partition('-')[2]
    proyecto = lectura.nombres_obras.get(codigo_excel)
    nombre = f'{proyecto} ({prefijo} {codigo_excel})' if proyecto else f'{prefijo} {codigo_excel}'.strip()
    codigo_obra = f'{c.codigo}-{num}'
    if Obra.objects.filter(codigo_obra__iexact=codigo_obra).exists():
        return None   # ya hay una obra con ese código (bajo otra empresa): se confirma con --obra, no se inventa BUC11-11-1
    return Obra.objects.create(constructora=c, nombre=nombre, codigo_obra=codigo_obra)
