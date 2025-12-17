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