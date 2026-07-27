"""
Generación del informe F-AI-1-01 — Resistencia a la compresión de especímenes
cilíndricos de concreto (NTC 673) — rellenando la plantilla Excel oficial por ciudad.

Estrategia: INYECCIÓN QUIRÚRGICA DE XML. Se reescribe únicamente
`xl/worksheets/sheet1.xml` (valores de celda) y `xl/workbook.xml` (fullCalcOnLoad),
dejando intactos estilos, fórmulas, imágenes EMF/WMF y drawings de la plantilla.
openpyxl NO sirve aquí porque descarta las imágenes EMF/WMF al guardar.
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from datetime import date

from django.conf import settings

PLANTILLAS_DIR = os.path.join(settings.BASE_DIR, 'ensayos', 'plantillas_xlsx')

# Prefijo/ciudad de la constructora -> archivo de plantilla
_PLANTILLA_POR_CIUDAD = {
    'bucaramanga': 'bucaramanga.xlsx',
    'bogota': 'bogota.xlsx',
    'ibague': 'ibague.xlsx',
}

MAX_FILAS = 16        # filas de datos visibles en la plantilla (10..25)
DATA_ROW_0 = 10       # primera fila de la tabla de datos
INPUT_ROW_0 = 47      # primera fila de la zona de entrada de mediciones
EXCEL_EPOCH = date(1899, 12, 30)


class ConversionPDFNoDisponible(Exception):
    """Se lanza cuando LibreOffice (soffice) no está disponible para xlsx->pdf."""


# ── Utilidades ──────────────────────────────────────────────────────────────

def _sin_acentos(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto or '')
        if not unicodedata.combining(c)
    ).strip().lower()


def ciudad_a_plantilla(ciudad):
    """Ruta del .xlsx según la ciudad de la constructora. Fallback: bucaramanga."""
    nombre = _PLANTILLA_POR_CIUDAD.get(_sin_acentos(ciudad), 'bucaramanga.xlsx')
    return os.path.join(PLANTILLAS_DIR, nombre)


# parse_fc_mpa vive en macros.py (fuente única para web e informes).
from .macros import parse_fc_mpa  # noqa: E402  (re-export para compatibilidad)


def _serial_fecha(d):
    return (d - EXCEL_EPOCH).days


def _esc(texto):
    return str(texto).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _tipo_falla_num(forma_falla):
    """'tipo_3' -> 3 ; vacío/None -> None."""
    if forma_falla and str(forma_falla).startswith('tipo_'):
        try:
            return int(str(forma_falla).split('_')[1])
        except (ValueError, IndexError):
            return None
    return None


# ── Inyección de celdas ───────────────────────────────────────────────────────

def _celda_xml(coord, estilo, tipo, valor):
    s = f' s="{estilo}"' if estilo is not None else ''
    if tipo == 'str':
        t = _esc(valor)
        space = ' xml:space="preserve"' if t != t.strip() else ''
        return f'<c r="{coord}"{s} t="inlineStr"><is><t{space}>{t}</t></is></c>'
    return f'<c r="{coord}"{s}><v>{valor}</v></c>'  # num o date (serial)


def _col_a_num(letras):
    n = 0
    for ch in letras:
        n = n * 26 + (ord(ch.upper()) - ord('A') + 1)
    return n


def _partes_coord(coord):
    mm = re.match(r'([A-Z]+)(\d+)', coord)
    return mm.group(1), int(mm.group(2))


def _set_celdas(ws_xml, valores):
    """
    valores: {coord: (tipo, valor)}.
    Si la celda existe, reemplaza preservando 's'. Si NO existe, la inserta en su
    `<row>` en orden de columna (necesario porque la plantilla no declara todas
    las celdas explícitamente — ej. P47, Q47 estaban ausentes).
    """
    for coord, (tipo, valor) in valores.items():
        if valor is None or valor == '':
            continue
        col, row_num = _partes_coord(coord)
        cell_re = re.compile('<c r="%s"(?P<attrs>[^>]*?)(?:/>|>.*?</c>)' % re.escape(coord), re.S)
        m = cell_re.search(ws_xml)
        if m:
            sm = re.search(r's="(\d+)"', m.group('attrs'))
            estilo = sm.group(1) if sm else None
            ws_xml = ws_xml[:m.start()] + _celda_xml(coord, estilo, tipo, valor) + ws_xml[m.end():]
            continue
        # Celda inexistente: insertarla en su fila, en orden de columna.
        row_re = re.compile(r'(<row r="%d"[^>]*>)(.*?)(</row>)' % row_num, re.S)
        rm = row_re.search(ws_xml)
        if not rm:
            continue  # fila inexistente; en nuestros targets no debería ocurrir
        row_open, body, row_close = rm.group(1), rm.group(2), rm.group(3)
        target_n = _col_a_num(col)
        nuevo_cell = _celda_xml(coord, None, tipo, valor)
        nuevo_body, last, inserted = '', 0, False
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"[^>]*?(?:/>|>.*?</c>)', body, re.S):
            if not inserted and _col_a_num(cm.group(1)) > target_n:
                nuevo_body += body[last:cm.start()] + nuevo_cell
                last = cm.start()
                inserted = True
        nuevo_body += body[last:]
        if not inserted:
            nuevo_body += nuevo_cell
        ws_xml = ws_xml[:rm.start()] + row_open + nuevo_body + row_close + ws_xml[rm.end():]
    return ws_xml


def _num(d, coord, v):
    if v is not None and v != '':
        d[coord] = ('num', float(v))


def _calcular_dependientes(esp, drow):
    """
    Calcula en Python las celdas dependientes replicando EXACTAMENTE la macro
    Excel original (PLANTILLA MACRO.xlsx, F-GT-05):

      - Corrección de instrumento sumada al promedio de diámetro/longitud
        según la dimensión del espécimen (3"/4"/6").
      - Polinomio de calibración de la prensa aplicado a la carga para las
        columnas de resistencia (K kgf, N, O MPa, P psi). La columna L (kN)
        muestra la carga TAL CUAL la entrega la prensa.
      - SIN redondeos intermedios: se inyectan valores a precisión completa y
        el formato numérico de cada celda del template hace el redondeo de
        presentación, igual que en Excel.

    Necesario porque LibreOffice headless usa los <v> cacheados al convertir.
    Los valores se inyectan como <v> y reemplazan las fórmulas — el informe
    es un snapshot.
    """
    import math
    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP
    from .macros import (
        CORRECCION_DIAMETRO_MM, CORRECCION_LONGITUD_MM, corregir_carga_kn,
    )
    out = {}
    m = esp.muestra
    dim = getattr(m, 'dimension_especimen', '') or ''
    D1, D2, D3 = esp.diametro_d1, esp.diametro_d2, esp.diametro_d3
    L1, L2, L3 = esp.longitud_l1, esp.longitud_l2, esp.longitud_l3

    # D: fecha de falla = fecha_toma + edad
    if m.fecha_toma and m.edad_ensayo_dias is not None:
        ff = m.fecha_toma + timedelta(days=m.edad_ensayo_dias)
        out[f'D{drow}'] = ('date', _serial_fecha(ff))

    i_val = j_val = h_val = o_val = None

    # I: diámetro promedio (mm) + corrección de instrumento
    if D1 is not None and D2 is not None and D3 is not None:
        i_val = ((float(D1) + float(D2) + float(D3)) / 3
                 + CORRECCION_DIAMETRO_MM.get(dim, 0.0))
        out[f'I{drow}'] = ('num', i_val)
    # H: longitud promedio (mm) + corrección de instrumento
    if L1 is not None and L2 is not None and L3 is not None:
        h_val = ((float(L1) + float(L2) + float(L3)) / 3
                 + CORRECCION_LONGITUD_MM.get(dim, 0.0))
        out[f'H{drow}'] = ('num', h_val)
    # J: AREA cm² = π·d²/400 (desde el diámetro corregido, sin redondear)
    if i_val is not None:
        j_val = i_val * i_val * math.pi / 400
        out[f'J{drow}'] = ('num', j_val)
    # L: carga kN tal cual la entrega la prensa
    if esp.carga_maxima_kn is not None:
        l_val = float(esp.carga_maxima_kn)
        out[f'L{drow}'] = ('num', l_val)
        if l_val > 0:
            # Carga corregida por el polinomio de la prensa: base de todas
            # las columnas de resistencia (coherentes entre sí).
            carga_corr = corregir_carga_kn(l_val)
            # K: carga corregida en kgf = kN_corr / 0.009807
            k_val = carga_corr / 0.009807
            out[f'K{drow}'] = ('num', k_val)
            if j_val:
                # N: resistencia kgf/cm² = K/J
                n_val = k_val / j_val
                out[f'N{drow}'] = ('num', n_val)
                # O: esfuerzo MPa = (kN_corr·101.9716/J)/10
                o_val = (carga_corr * 101.9716 / j_val) / 10
                out[f'O{drow}'] = ('num', o_val)
                # P: psi = N/0.07
                out[f'P{drow}'] = ('num', n_val / 0.07)
    # Q: % desarrollo = O/M·100
    fc = parse_fc_mpa(m.fc_resistencia)
    if o_val is not None and fc:
        out[f'Q{drow}'] = ('num', o_val / fc * 100)
    # R: densidad (kg/m³) — MROUND(peso_g/(J·H/1e7)/1000, 10) como Excel:
    # múltiplo de 10 más cercano, mitades LEJOS de cero (round() de Python
    # usa banker's rounding y difiere en la frontera).
    if esp.peso_gramos and j_val and h_val:
        peso_g = float(esp.peso_gramos)
        densidad = peso_g / (j_val * h_val / 1e7) / 1000
        mround = int((Decimal(repr(densidad)) / 10)
                     .quantize(Decimal(1), rounding=ROUND_HALF_UP) * 10)
        out[f'R{drow}'] = ('num', mround)
    # S: L/D
    if h_val and i_val:
        out[f'S{drow}'] = ('num', h_val / i_val)
    return out


def _construir_valores(especimenes, cabecera, pagina, total_paginas):
    vals = {
        'B6': ('str', cabecera.get('cliente', '')),
        'B7': ('str', cabecera.get('obra', '')),
        'K7': ('date', _serial_fecha(cabecera['fecha_informe'])),
        'T7': ('str', cabecera['numero_informe']),
        'S26': ('str', f"PÁGINA {pagina} DE {total_paginas}"),
    }
    for i, esp in enumerate(especimenes):
        drow = DATA_ROW_0 + i
        irow = INPUT_ROW_0 + i
        m = esp.muestra
        vals[f'A{drow}'] = ('num', m.numero_muestra)
        if m.localizacion:
            vals[f'B{drow}'] = ('str', m.localizacion)
        if m.fecha_toma:
            vals[f'C{drow}'] = ('date', _serial_fecha(m.fecha_toma))
        if m.edad_ensayo_dias is not None:
            vals[f'G{drow}'] = ('num', m.edad_ensayo_dias)
        fc = parse_fc_mpa(m.fc_resistencia)
        if fc is not None:
            vals[f'M{drow}'] = ('num', fc)
        tf = _tipo_falla_num(esp.forma_falla)
        if tf is not None:
            vals[f'T{drow}'] = ('num', tf)
        # Zona de entrada de mediciones (filas 47..)
        _num(vals, f'J{irow}', esp.diametro_d1)
        _num(vals, f'K{irow}', esp.diametro_d2)
        _num(vals, f'L{irow}', esp.diametro_d3)
        _num(vals, f'O{irow}', esp.longitud_l1)
        _num(vals, f'P{irow}', esp.longitud_l2)
        _num(vals, f'Q{irow}', esp.longitud_l3)
        if esp.peso_gramos:
            # En gramos (la fórmula de densidad del template los espera en g).
            vals[f'S{irow}'] = ('num', float(esp.peso_gramos))
        _num(vals, f'T{irow}', esp.carga_maxima_kn)
        # Valores derivados (PDF/Excel los muestran sin necesidad de recálculo)
        vals.update(_calcular_dependientes(esp, drow))
    return vals


def llenar_plantilla_bytes(ruta_plantilla, especimenes, cabecera, pagina, total_paginas):
    """Rellena una página (≤16 especímenes) y devuelve los bytes del .xlsx."""
    with zipfile.ZipFile(ruta_plantilla) as z:
        nombres = z.namelist()
        contenidos = {n: z.read(n) for n in nombres}

    ws = contenidos['xl/worksheets/sheet1.xml'].decode('utf-8')
    ws = _set_celdas(ws, _construir_valores(especimenes, cabecera, pagina, total_paginas))
    contenidos['xl/worksheets/sheet1.xml'] = ws.encode('utf-8')

    wb = contenidos['xl/workbook.xml'].decode('utf-8')
    if 'fullCalcOnLoad' not in wb:
        wb = re.sub(r'<calcPr ', '<calcPr fullCalcOnLoad="1" ', wb, count=1)
    contenidos['xl/workbook.xml'] = wb.encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in nombres:
            zo.writestr(n, contenidos[n])
    return buf.getvalue()


# ── Conversión a PDF (LibreOffice headless) ───────────────────────────────────

def _soffice_bin():
    return (
        getattr(settings, 'LIBREOFFICE_PATH', None)
        or os.environ.get('LIBREOFFICE_PATH')
        or shutil.which('soffice')
        or shutil.which('libreoffice')
    )


def xlsx_a_pdf_bytes(xlsx_bytes):
    binario = _soffice_bin()
    if not binario:
        raise ConversionPDFNoDisponible('LibreOffice (soffice) no está disponible.')
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = os.path.join(tmp, 'informe.xlsx')
        with open(xlsx_path, 'wb') as f:
            f.write(xlsx_bytes)
        perfil = os.path.join(tmp, 'lo_profile').replace('\\', '/')
        subprocess.run(
            [
                binario, '--headless', '--nolockcheck', '--norestore',
                f'-env:UserInstallation=file:///{perfil}',
                '--convert-to', 'pdf', '--outdir', tmp, xlsx_path,
            ],
            check=True, capture_output=True, timeout=120,
        )
        pdf_path = os.path.join(tmp, 'informe.pdf')
        with open(pdf_path, 'rb') as f:
            return f.read()


def _concatenar_pdfs(lista_bytes):
    if len(lista_bytes) == 1:
        return lista_bytes[0]
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for b in lista_bytes:
        for page in PdfReader(io.BytesIO(b)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ── Orquestación ──────────────────────────────────────────────────────────────

def generar_archivos(ciudad, especimenes, cabecera):
    """
    Genera los entregables del informe.

    Returns: dict con
      - 'xlsx': bytes del .xlsx (o .zip si hay >1 página)
      - 'xlsx_es_zip': bool
      - 'pdf': bytes del PDF concatenado, o None si no hay conversor disponible
    """
    ruta = ciudad_a_plantilla(ciudad)
    especimenes = list(especimenes)
    chunks = [especimenes[i:i + MAX_FILAS] for i in range(0, len(especimenes), MAX_FILAS)] or [[]]
    total = len(chunks)

    xlsx_paginas = [
        llenar_plantilla_bytes(ruta, ch, cabecera, idx + 1, total)
        for idx, ch in enumerate(chunks)
    ]

    pdf_bytes = None
    try:
        pdf_bytes = _concatenar_pdfs([xlsx_a_pdf_bytes(x) for x in xlsx_paginas])
    except (ConversionPDFNoDisponible, subprocess.SubprocessError, OSError):
        pdf_bytes = None

    if total == 1:
        return {'xlsx': xlsx_paginas[0], 'xlsx_es_zip': False, 'pdf': pdf_bytes}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for idx, x in enumerate(xlsx_paginas):
            z.writestr(f"{cabecera['numero_informe']}_pag{idx + 1}.xlsx", x)
    return {'xlsx': buf.getvalue(), 'xlsx_es_zip': True, 'pdf': pdf_bytes}
