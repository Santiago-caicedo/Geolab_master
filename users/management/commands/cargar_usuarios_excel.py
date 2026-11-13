"""
Carga los usuarios cliente (residentes, remitentes, directores) desde el Excel del laboratorio
"USUARIOS Y CONTRASEÑAS": una hoja por sede (BOG, BUC, IBA).

    python manage.py cargar_usuarios_excel "USUARIOS Y CONTRASEÑAS (4).xlsx"            # ensayo: no guarda
    python manage.py cargar_usuarios_excel "USUARIOS Y CONTRASEÑAS (4).xlsx" --aplicar

Columnas: A usuario, C contraseña, E obra (residentes). En BUC además H/J/L = remitentes
("USUARIO REMISIONES") y O/P/Q = directores (usuario, contraseña, razón social).
La obra viene como "57-4", "2--2" o "13---1" (los guiones de más evitan que Excel lo vuelva
fecha): se lee como <sede><empresa>-<obra> = BUC57-4.

EXCEPCIÓN DELIBERADA (decisión del usuario, nov-2026): las contraseñas se cargan TAL CUAL
están en el Excel, sin los validadores de Django, porque son las que los clientes ya usan en
WordPress. No usar este comando como modelo para crear usuarios nuevos.

- No toca usuarios que ya existen (ni su contraseña): los lista.
- Nunca imprime contraseñas.
- Código de obra repetido en el portal: se desempata con DESEMPATE (usuario -> código de la
  constructora) o con --obra usuario=CODIGO_OBRA@CODIGO_EMPRESA.
- PENDIENTES: usuarios que no se cargan hasta que el laboratorio confirme; --obra los carga.
- Ignorado si falta el .xlsx en git: el archivo trae contraseñas y NUNCA se versiona.
"""

import re

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Obra
from users.models import ClienteExterno, Constructora, UsuarioBase

SEDES = {'BOG': 'BOG', 'BUC': 'BUC', 'IBA': 'IBA'}

# Código de obra que en el portal tiene varias obras (empresas que comparten código en WordPress).
# Decidido con el usuario el 2026-11-13 por el nombre del usuario.
DESEMPATE = {
    'interidu': 'BOG0-2B',          # INTERVENTORIA IDU 1523-2025
    'andes06': 'BOG3B',             # ANDES 06
    'espacio52': 'BOG4B',           # ESPACIO 52
    'meraki20': 'BOG5B',            # MERAKI 20
    'rprovenza': 'BUC11',           # CASA PROVENZA (CAG)
    'cprovenza': 'BUC11',
    'living43': 'BUC25B',           # LIVING 43
    'cconsultecnicos': 'BUC27B',    # DOBLE CALZADA (CONSORCIO CONSULTECNICOS)
}

# Directores: el Excel solo trae la razón social
DIRECTORES = {
    'marvalsas': 'BUC56',           # MARVAL SAS
    'urbmarval': 'BUC57',           # URBANIZADORA MARVAL SAS
}

# No se cargan hasta que el laboratorio confirme (informe enviado el 2026-11-13)
PENDIENTES = {
    'beltramonto': 'el código 7-14 es "PLANTA ITALCOL CUCUTA" en el portal: confirmar la obra con el laboratorio',
}


def _texto(valor):
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor)


def leer_excel(ruta):
    """Filas del Excel: dict(hoja, fila, rol, usuario, clave, obra, razon). La clave sin tocar."""
    try:
        wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    except FileNotFoundError:
        raise CommandError(f'No existe el archivo {ruta}')
    try:
        return _filas(wb)
    finally:
        wb.close()   # read_only deja el archivo abierto (en Windows no se puede borrar)


def _filas(wb):
    filas = []
    for ws in wb.worksheets:
        sede = ws.title.strip().upper()
        if sede not in SEDES:
            continue
        for n, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            r = list(r) + [None] * 20
            bloques = [('residente', 0, 2, 4)]
            if sede == 'BUC':
                bloques.append(('remitente', 7, 9, 11))
            for rol, cu, cc, co in bloques:
                usuario, clave, obra = _texto(r[cu]).strip(), _texto(r[cc]), _texto(r[co]).strip()
                if usuario.upper().startswith('USUARIO') or not (usuario or clave or obra):
                    continue
                filas.append(dict(hoja=sede, fila=n, rol=rol, usuario=usuario, clave=clave, obra=obra, razon=''))
            if sede == 'BUC':
                usuario = _texto(r[14]).strip()
                if usuario and not usuario.upper().startswith('USUARIO'):
                    filas.append(dict(hoja=sede, fila=n, rol='director', usuario=usuario, clave=_texto(r[15]),
                                      obra='', razon=_texto(r[16]).strip()))
    return filas


class Command(BaseCommand):
    help = 'Carga residentes, remitentes y directores desde el Excel de usuarios del laboratorio (contraseñas tal cual).'

    def add_arguments(self, parser):
        parser.add_argument('excel')
        parser.add_argument('--aplicar', action='store_true', help='Guarda (sin esto es ensayo).')
        parser.add_argument('--obra', action='append', default=[], metavar='USUARIO=CODIGO_OBRA[@EMPRESA]',
                            help='Fija la obra de un usuario (también carga un PENDIENTE).')
        parser.add_argument('--omitir', action='append', default=[], metavar='USUARIO')

    def handle(self, *args, **opts):
        fijadas = {}
        for item in opts['obra']:
            if '=' not in item:
                raise CommandError(f'--obra {item}: use USUARIO=CODIGO_OBRA[@EMPRESA]')
            u, destino = item.split('=', 1)
            fijadas[u.strip().lower()] = destino.strip()
        omitir = {u.lower() for u in opts['omitir']}

        filas = leer_excel(opts['excel'])
        vistos = {}
        listos, saltados = [], []
        for f in filas:
            clave_u = f['usuario'].lower()
            donde = f'{f["hoja"]} fila {f["fila"]}'
            if not f['usuario']:
                saltados.append((donde, '(sin usuario)', f'obra {f["obra"] or "-"}: la fila no tiene usuario'))
                continue
            if clave_u in vistos:
                raise CommandError(f'El usuario {f["usuario"]} está dos veces en el Excel ({vistos[clave_u]} y {donde}).')
            vistos[clave_u] = donde
            if clave_u in omitir:
                saltados.append((donde, f['usuario'], 'omitido con --omitir'))
                continue
            if not f['clave']:
                saltados.append((donde, f['usuario'], 'no tiene contraseña en el Excel'))
                continue
            if clave_u in PENDIENTES and clave_u not in fijadas:
                saltados.append((donde, f['usuario'], 'PENDIENTE: ' + PENDIENTES[clave_u]))
                continue
            if UsuarioBase.objects.filter(username__iexact=f['usuario']).exists():
                saltados.append((donde, f['usuario'], 'ya existe en el portal (no se toca)'))
                continue

            if f['rol'] == 'director':
                codigo = (fijadas.get(clave_u) or DIRECTORES.get(clave_u) or "").split("@")[-1]
                empresa = Constructora.objects.filter(codigo__iexact=codigo).first() if codigo else None
                if not empresa:
                    saltados.append((donde, f['usuario'], f'director de "{f["razon"]}": no sé qué empresa es (use --obra {f["usuario"]}=@CODIGO)'))
                    continue
                f.update(empresa=empresa, obra_obj=None)
                listos.append(f)
                continue

            obra, error = self._obra(f, fijadas.get(clave_u))
            if error:
                saltados.append((donde, f['usuario'], error))
                continue
            f.update(empresa=obra.constructora, obra_obj=obra)
            listos.append(f)

        self.stdout.write(self.style.MIGRATE_HEADING(f'Se crean {len(listos)} usuarios'))
        for f in sorted(listos, key=lambda x: (x['hoja'], x['rol'], x['usuario'])):
            destino = (f'{f["obra_obj"].codigo_obra} "{f["obra_obj"].nombre}"' if f['obra_obj']
                       else 'toda la empresa')
            self.stdout.write(f'  + {f["hoja"]} {f["rol"]:9} {f["usuario"]:18} {f["empresa"].codigo} → {destino}')
        if saltados:
            self.stdout.write(self.style.WARNING(f'\nNo se cargan: {len(saltados)}'))
            for donde, usuario, motivo in saltados:
                self.stdout.write(f'  - {usuario:18} ({donde}): {motivo}')

        if not opts['aplicar']:
            self.stdout.write(self.style.WARNING('\nENSAYO: no se guardó nada. Para cargar: --aplicar'))
            return

        with transaction.atomic():
            for f in listos:
                u = UsuarioBase(username=f['usuario'], es_cliente=True, es_geolab=False, is_active=True)
                u.set_password(f['clave'])   # tal cual el Excel: sin validadores (excepción acordada)
                u.save()
                cliente = ClienteExterno.objects.create(user=u, empresa=f['empresa'], rol=f['rol'])
                if f['obra_obj']:
                    cliente.obras_asignadas.add(f['obra_obj'])
            # Verificación: cada usuario entra con la contraseña exacta del Excel
            malos = [f['usuario'] for f in listos
                     if not UsuarioBase.objects.get(username=f['usuario']).check_password(f['clave'])]
            if malos:
                raise CommandError('No se pudo verificar la contraseña de: ' + ', '.join(malos) + '. No se guardó nada.')
        self.stdout.write(self.style.SUCCESS(
            f'\nCreados {len(listos)} usuarios; cada uno verificado con su contraseña del Excel.'))

    def _obra(self, f, fijada):
        sede = SEDES[f['hoja']]
        if fijada:
            codigo, _, empresa = fijada.partition('@')
        else:
            codigo, empresa = sede + re.sub(r'-+', '-', f['obra'].replace(' ', '')), DESEMPATE.get(f['usuario'].lower(), '')
        if not codigo or codigo == sede:
            return None, 'la fila no tiene obra'
        obras = Obra.objects.filter(codigo_obra__iexact=codigo).select_related('constructora')
        if empresa:
            obras = obras.filter(constructora__codigo__iexact=empresa)
        obras = list(obras)
        if not obras:
            return None, f'no existe la obra {codigo}' + (f' en {empresa}' if empresa else '')
        if len(obras) > 1:
            return None, (f'el código {codigo} tiene {len(obras)} obras en el portal ('
                          + '; '.join(f'{o.constructora.codigo} "{o.nombre}"' for o in obras)
                          + f'): use --obra {f["usuario"]}={codigo}@EMPRESA')
        return obras[0], None
