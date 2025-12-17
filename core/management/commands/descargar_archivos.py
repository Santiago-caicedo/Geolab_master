import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.conf import settings
from core.models import Informe

class Command(BaseCommand):
    help = 'Enlaza archivos locales inteligentemente o descarga los faltantes con seguridad'

    def handle(self, *args, **kwargs):
        # 1. MAPEO DE ARCHIVOS LOCALES
        # Primero escaneamos qué diablos hay en la carpeta media para no descargar a ciegas
        self.stdout.write(self.style.WARNING("Escaneando archivos locales en 'media'..."))
        mapa_archivos = {}
        
        ruta_base = str(settings.MEDIA_ROOT)
        for root, dirs, files in os.walk(ruta_base):
            for file in files:
                # Guardamos: 'nombre_archivo.pdf' -> 'informes/2023/nombre_archivo.pdf'
                ruta_completa = os.path.join(root, file)
                ruta_relativa = os.path.relpath(ruta_completa, ruta_base)
                # Normalizamos para evitar problemas de mayúsculas/minúsculas
                mapa_archivos[file] = ruta_relativa

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
        informes = Informe.objects.filter(url_archivo_original__isnull=False).exclude(url_archivo_original='').filter(archivo='')
        total = informes.count()
        
        self.stdout.write(f"Procesando {total} informes pendientes de enlazar...")

        enlazados = 0
        descargados = 0
        errores = 0

        for i, informe in enumerate(informes):
            url = informe.url_archivo_original.strip()
            nombre_archivo_url = os.path.basename(url)
            
            # A. BUSQUEDA INTELIGENTE LOCAL
            # ¿Tenemos este archivo en el mapa que creamos al principio?
            if nombre_archivo_url in mapa_archivos:
                # ¡SI ESTÁ! Usamos la ruta que encontramos
                ruta_existente = mapa_archivos[nombre_archivo_url]
                informe.archivo.name = ruta_existente
                informe.save()
                
                # Feedback visual simple cada 100 registros para no saturar consola
                if i % 100 == 0:
                    self.stdout.write(f"[{i}/{total}] Enlazado localmente: {nombre_archivo_url}")
                enlazados += 1
                continue # Saltamos al siguiente, no hace falta descargar

            # B. DESCARGA (Solo si falló lo anterior)
            try:
                # Pausa de seguridad
                time.sleep(0.5) 
                
                self.stdout.write(self.style.WARNING(f"Descargando real: {nombre_archivo_url}"))
                response = session.get(url, stream=True, timeout=15)
                
                if response.status_code == 200:
                    informe.archivo.save(nombre_archivo_url, ContentFile(response.content), save=True)
                    # Actualizamos el mapa por si sale repetido más adelante
                    mapa_archivos[nombre_archivo_url] = informe.archivo.name
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