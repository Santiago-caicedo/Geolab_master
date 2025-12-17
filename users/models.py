from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. LA EMPRESA (La entidad Marval)
class Constructora(models.Model):
    nombre = models.CharField(max_length=200) # "Marval"
    codigo = models.CharField(max_length=50, unique=True, help_text="Ej: 52")
    nit = models.CharField(max_length=20, blank=True, null=True)

    ciudad = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Campo para migración
    id_wp_original = models.IntegerField(unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"

# 2. USUARIO BASE (Solo para Login)
class UsuarioBase(AbstractUser):
    # Flags para saber rápidamente qué tipo es sin hacer consultas complejas
    es_geolab = models.BooleanField(default=False)
    es_cliente = models.BooleanField(default=False)

    def __str__(self):
        return self.username

# 3. PERFIL INTERNO (Tu equipo)
class FuncionarioGeolab(models.Model):
    AREAS = [
        ('lab', 'Laboratorio'),
        ('admin', 'Administrativo'),
        ('recepcion', 'Recepción de Muestras'),
    ]
    user = models.OneToOneField(UsuarioBase, on_delete=models.CASCADE, related_name='perfil_geolab')
    area = models.CharField(max_length=50, choices=AREAS)
    codigo_empleado = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"[Geolab] {self.user.get_full_name()} - {self.area}"

# 4. PERFIL EXTERNO (Victor, Carlos)
class ClienteExterno(models.Model):
    ROLES = [
        ('director', 'Director (Ve toda la constructora)'),
        ('residente', 'Residente (Ve solo obras asignadas)'),
    ]
    user = models.OneToOneField(UsuarioBase, on_delete=models.CASCADE, related_name='perfil_cliente')
    
    # Vinculamos a la persona con la Empresa (Marval)
    empresa = models.ForeignKey(Constructora, on_delete=models.CASCADE, related_name='usuarios')
    rol = models.CharField(max_length=20, choices=ROLES, default='residente')
    
    cargo = models.CharField(max_length=100, blank=True) # Ej: Ing. Residente Torre 1
    telefono = models.CharField(max_length=20, blank=True)

    # Campo para migración
    id_wp_original = models.IntegerField(unique=True, null=True, blank=True)

    def __str__(self):
        return f"[{self.empresa.nombre}] {self.user.get_full_name()} ({self.rol})"