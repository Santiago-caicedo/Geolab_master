from django.conf import settings
from django.db import models
# Importamos los modelos de la otra app
from users.models import Constructora, ClienteExterno

class Obra(models.Model):
    nombre = models.CharField(max_length=255) # "Torres de Mardel"
    codigo_obra = models.CharField(max_length=50, help_text="Ej: 52-1")
    
    # Relación: La obra pertenece a la Empresa (Marval)
    constructora = models.ForeignKey(Constructora, on_delete=models.CASCADE, related_name='obras')
    
    # PERMISOS ESPECÍFICOS (Solo para Residentes como Carlos)
    # Victor (Director) no necesita estar aquí porque él ve todo por ser de la Constructora
    residentes_asignados = models.ManyToManyField(
        ClienteExterno, 
        blank=True, 
        related_name='obras_asignadas'
    )
    
    fecha_creacion = models.DateTimeField(null=True, blank=True)
    id_wp_original = models.IntegerField(unique=True, null=True)

    # Datos de contacto de la obra (vienen del formulario de WordPress; opcionales)
    direccion = models.CharField(max_length=255, blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    contacto = models.CharField(max_length=150, blank=True, verbose_name='Persona de contacto')
    celular = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.nombre} ({self.codigo_obra})"

class Informe(models.Model):
    titulo = models.CharField(max_length=255)
    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name='informes')
    fecha_creacion = models.DateTimeField(null=True, blank=True)
    
    url_archivo_original = models.CharField(max_length=500, null=True, blank=True)
    archivo = models.FileField(upload_to='informes/%Y/%m/', null=True, blank=True)
    
    id_wp_original = models.IntegerField(unique=True, null=True)

    class Meta:
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{self.titulo} - {self.obra.codigo_obra}"


class InformeEliminado(models.Model):
    """
    Registro de cada informe borrado desde el portal (quién, cuándo, qué).
    Además evita que sincronizar_wordpress vuelva a traer un informe que se
    borró a propósito: se salta todo id_wp_original que esté aquí.
    """
    titulo = models.CharField(max_length=255)
    obra_codigo = models.CharField(max_length=50, blank=True)
    obra_nombre = models.CharField(max_length=255, blank=True)
    id_wp_original = models.IntegerField(null=True, blank=True, db_index=True)
    archivo = models.CharField(max_length=500, blank=True, help_text='Ruta del PDF que se borró del almacenamiento')
    fecha_informe = models.DateTimeField(null=True, blank=True)
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='informes_eliminados',
    )
    fecha_eliminacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_eliminacion']
        verbose_name = 'informe eliminado'
        verbose_name_plural = 'informes eliminados'

    def __str__(self):
        return f"{self.titulo} ({self.obra_codigo}) - eliminado {self.fecha_eliminacion:%Y-%m-%d}"
