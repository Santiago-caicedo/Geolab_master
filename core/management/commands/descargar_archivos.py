import os
import time
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from core.models import Informe


def clave_url(url):
    """'.../wp-content/uploads/2023/08/INF-0425.pdf' -> '2023/08/INF-0425.pdf'.

    WordPress repite nombres de PDF entre carpetas (las sedes comparten la
    numeración INF-NNNN-AAAA), así que el nombre solo NO identifica el archivo.
    """
    ruta = unquote(urlparse(url.strip()).path)
    if '/uploads/' in ruta:
        return ruta.split('/uploads/', 1)[1]
    return '/'.join(ruta.rstrip('/').split('/')[-3:])


def clave_local(ruta_relativa):
    """'informes/2023/08/INF-0425.pdf' -> '2023/08/INF-0425.pdf' (año/mes/nombre)."""
    return '/'.join(ruta_relativa.replace(os.sep, '/').split('/')[-3:])


def informes_compartidos():
    """Informes que comparten `archivo` con otro informe de URL distinta: al menos
    uno de cada grupo tiene el PDF equivocado (enlazado solo por nombre)."""
    repetidos = (Informe.objects.exclude(archivo='').exclude(archivo__isnull=True)
                 .values('archivo').annotate(n=Count('id')).filter(n__gt=1)
                 .values_list('archivo', flat=True))
    grupos = defaultdict(list)
    for inf in Informe.objects.filter(archivo__in=list(repetidos)).select_related('obra'):
        grupos[inf.archivo.name].append(inf)
    return {k: v for k, v in grupos.items()
            if len({clave_url(i.url_archivo_original or '') for i in v}) > 1}


class Command(BaseCommand):
    help = 'Enlaza archivos locales o descarga los faltantes; --revisar/--reparar detectan PDF cruzados entre informes'

    def add_arguments(self, parser):
        parser.add_argument('--revisar', action='store_true',
                            help='Solo lectura: lista informes que comparten PDF con otro informe de URL distinta')
        parser.add_argument('--reparar', action='store_true',
                            help='Vacía el archivo de esos informes para que la siguiente corrida los baje bien')

    def handle(self, *args, **opts):
        if opts['revisar'] or opts['reparar']:
            return self.revisar(reparar=opts['reparar'])
        self.descargar()

    def revisar(self, reparar):
        grupos = informes_compartidos()
        total = sum(len(v) for v in grupos.values())
        self.stdout.write(f"PDF compartidos por informes de URL distinta: {len(grupos)} archivos, {total} informes")
        for archivo, infs in sorted(grupos.items()):
            self.stdout.write(f"\n  {archivo}")
            for i in infs:
                obra = i.obra.codigo_obra if i.obra_id else '-'
                self.stdout.write(f"    informe {i.pk:>6}  obra {obra:<14} {clave_url(i.url_archivo_original or '')}")
        if not grupos:
            self.stdout.write(self.style.SUCCESS("Nada que reparar."))
            return
        if not reparar:
            self.stdout.write(self.style.WARNING("\nSolo lectura. Con --reparar se vacía su archivo y luego hay que correr descargar_archivos."))
            return
        ids = [i.pk for infs in grupos.values() for i in infs if i.url_archivo_original]
        with transaction.atomic():
            n = Informe.objects.filter(pk__in=ids).update(archivo='')
        self.stdout.write(self.style.SUCCESS(f"\n{n} informes quedaron pendientes. Ahora corre: python manage.py descargar_archivos"))

    def descargar(self):
        # 1. MAPEO DE ARCHIVOS LOCALES por año/mes/nombre (el nombre solo se repite entre carpetas)
        self.stdout.write(self.style.WARNING("Escaneando archivos locales en 'media'..."))
        mapa_archivos = {}
        nombres_locales = Counter()
        ruta_base = str(settings.MEDIA_ROOT)
        for root, dirs, files in os.walk(ruta_base):
            for file in files:
                ruta_relativa = os.path.relpath(os.path.join(root, file), ruta_base).replace(os.sep, '/')
                mapa_archivos[clave_local(ruta_relativa)] = ruta_relativa
                nombres_locales[file] += 1
        por_nombre = {os.path.basename(k): v for k, v in mapa_archivos.items() if nombres_locales[os.path.basename(k)] == 1}

        self.stdout.write(self.style.SUCCESS(f"¡Mapa construido! Se encontraron {len(mapa_archivos)} archivos locales."))

        # 2. CONFIGURACIÓN DEL "DISFRAZ" (Para descargas necesarias)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://portal.geolabsas.co/'
        }
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.headers.update(headers)

        # 3. PROCESAR INFORMES
        # Buscamos informes que tengan URL pero no estén enlazados en DB
        informes = list(Informe.objects.filter(url_archivo_original__isnull=False).exclude(url_archivo_original='').filter(archivo=''))
        total = len(informes)
        # Un nombre que se repite entre los pendientes no se puede enlazar solo por nombre
        nombres_pendientes = Counter(os.path.basename(clave_url(i.url_archivo_original)) for i in informes)

        self.stdout.write(f"Procesando {total} informes pendientes de enlazar...")

        enlazados = 0
        descargados = 0
        errores = 0

        for i, informe in enumerate(informes):
            url = informe.url_archivo_original.strip()
            clave = clave_url(url)
            nombre_archivo_url = os.path.basename(clave)

            # A. BUSQUEDA LOCAL: misma carpeta año/mes, o nombre único en ambos lados
            ruta_existente = mapa_archivos.get(clave)
            if ruta_existente is None and nombres_pendientes[nombre_archivo_url] == 1:
                ruta_existente = por_nombre.get(nombre_archivo_url)
            if ruta_existente:
                informe.archivo.name = ruta_existente
                informe.save(update_fields=['archivo'])

                # Feedback visual simple cada 100 registros para no saturar consola
                if i % 100 == 0:
                    self.stdout.write(f"[{i}/{total}] Enlazado localmente: {clave}")
                enlazados += 1
                continue # Saltamos al siguiente, no hace falta descargar

            # B. DESCARGA (Solo si falló lo anterior)
            try:
                # Pausa de seguridad
                time.sleep(0.5)

                self.stdout.write(self.style.WARNING(f"[{i}/{total}] Descargando real: {clave}"))
                response = session.get(url, stream=True, timeout=15)

                if response.status_code == 200:
                    informe.archivo.save(nombre_archivo_url, ContentFile(response.content), save=True)
                    descargados += 1
                else:
                    self.stdout.write(self.style.ERROR(f"Error {response.status_code}: {url}"))
                    errores += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Falló conexión: {e}"))
                errores += 1

        self.stdout.write(self.style.SUCCESS(f"""
        RESUMEN FINAL:
        -------------------------
        Enlazados (Ya existían): {enlazados}
        Descargados (Nuevos):    {descargados}
        Fallidos:                {errores}
        """))
