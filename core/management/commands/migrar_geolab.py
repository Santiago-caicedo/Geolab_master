import os
import MySQLdb
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from django.db.utils import IntegrityError
from datetime import datetime

# Importamos los modelos (Sin usuarios, como acordamos)
from users.models import Constructora
from core.models import Obra, Informe

class Command(BaseCommand):
    help = 'Migración Limpia: Empresas, Obras e Informes (Títulos = Nombre de Archivo)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('Iniciando Migración Estructural...'))

        # ---------------------------------------------------------
        # 1. CONEXIÓN A BASE DE DATOS VIEJA
        # ---------------------------------------------------------
        try:
            db = MySQLdb.connect(
                host="localhost", 
                user="root", 
                passwd="", 
                db="wp_backup", 
                charset='utf8mb4'
            )
            cursor = db.cursor()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error conectando a MySQL: {e}"))
            return

        # =========================================================
        # FASE 1: OBRAS Y CONSTRUCTORAS
        # =========================================================
        self.stdout.write("--- Procesando Obras y Deduciendo Constructoras ---")
        
        query_proyectos = """
            SELECT 
                p.ID, 
                p.post_title, 
                p.post_date,
                MAX(CASE WHEN pm.meta_key = 'codigo-cliente_743' THEN pm.meta_value END) as codigo_agrupador,
                MAX(CASE WHEN pm.meta_key = 'razon-social' THEN pm.meta_value END) as nombre_empresa,
                MAX(CASE WHEN pm.meta_key = 'municipio' THEN pm.meta_value END) as ciudad
            FROM wpf3_posts p
            LEFT JOIN wpf3_postmeta pm ON p.ID = pm.post_id
            WHERE p.post_type = 'proyectos' AND p.post_status = 'publish'
            GROUP BY p.ID
        """
        cursor.execute(query_proyectos)
        rows = cursor.fetchall()
        
        count_emp = 0
        count_obras = 0

        for row in rows:
            id_wp, titulo_obra, fecha, codigo_raw, razon_social, ciudad = row
            
            # NORMALIZACIÓN
            if codigo_raw:
                codigo_limpio = str(codigo_raw).upper().replace(" ", "").replace("-", "").replace("_", "").strip()
            else:
                codigo_limpio = "SINCODIGO"

            nombre_final = razon_social if razon_social else f"CONSTRUCTORA {codigo_limpio}"
            ciudad_final = ciudad if ciudad else None

            # 1. GESTIONAR CONSTRUCTORA
            empresa, created_emp = Constructora.objects.update_or_create(
                codigo=codigo_limpio,
                defaults={
                    'nombre': nombre_final,
                    'ciudad': ciudad_final,
                }
            )
            if created_emp:
                count_emp += 1

            # 2. CREAR LA OBRA
            Obra.objects.update_or_create(
                id_wp_original=id_wp,
                defaults={
                    'nombre': titulo_obra,
                    'codigo_obra': f"{codigo_limpio}-{id_wp}", 
                    'constructora': empresa,
                    'fecha_creacion': make_aware(fecha) if fecha else None
                }
            )
            count_obras += 1

        self.stdout.write(self.style.SUCCESS(f" -> {count_obras} Obras procesadas."))
        self.stdout.write(self.style.SUCCESS(f" -> {count_emp} Constructoras creadas."))

        # =========================================================
        # FASE 3: INFORMES (TÍTULO = NOMBRE DE ARCHIVO)
        # =========================================================
        self.stdout.write("--- Migrando Informes (Usando nombre de archivo como título) ---")
        
        query_informes = """
            SELECT p.ID, p.post_title, p.post_date, rel.parent_object_id, pdf_post.guid
            FROM wpf3_posts p
            JOIN wpf3_jet_rel_default rel ON (p.ID = rel.child_object_id AND rel.rel_id = 10)
            LEFT JOIN wpf3_postmeta pm ON (p.ID = pm.post_id AND pm.meta_key = 'galeria-pdf')
            LEFT JOIN wpf3_posts pdf_post ON (pm.meta_value = pdf_post.ID)
            WHERE p.post_type = 'informes' AND p.post_status = 'publish'
        """
        cursor.execute(query_informes)
        
        count_informes = 0
        batch_size = 2000
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows: break
            
            for row in rows:
                id_wp, titulo_wp, fecha, id_obra_wp, url_pdf = row
                
                # --- LÓGICA DE TÍTULO ---
                # Si hay URL, extraemos el nombre del archivo (ej: INF-5268.pdf)
                # Si no, usamos el título viejo de WP como respaldo
                if url_pdf:
                    titulo_final = os.path.basename(url_pdf)
                else:
                    titulo_final = titulo_wp

                try:
                    obra = Obra.objects.get(id_wp_original=id_obra_wp)
                    
                    Informe.objects.update_or_create(
                        id_wp_original=id_wp,
                        defaults={
                            'titulo': titulo_final,  # <--- AQUÍ GUARDAMOS EL NOMBRE DEL ARCHIVO
                            'obra': obra,
                            'fecha_creacion': make_aware(fecha) if fecha else None,
                            'url_archivo_original': url_pdf
                        }
                    )
                    count_informes += 1
                except Obra.DoesNotExist:
                    pass

        self.stdout.write(self.style.SUCCESS(f"¡MIGRACIÓN FINALIZADA! Total informes: {count_informes}"))
        db.close()