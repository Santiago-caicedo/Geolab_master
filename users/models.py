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

    @property
    def es_tecnico_laboratorio(self):
        """Verifica si el usuario es técnico de laboratorio"""
        if self.es_geolab and hasattr(self, 'perfil_geolab'):
            return self.perfil_geolab.area == 'tecnico'
        return False

    @property
    def es_admin_geolab(self):
        """Verifica si el usuario es admin/staff completo de Geolab (no técnico)"""
        if self.es_geolab and hasattr(self, 'perfil_geolab'):
            return self.perfil_geolab.area in ['admin', 'lab', 'recepcion']
        return self.es_geolab

    @property
    def es_remitente(self):
        """Verifica si el usuario es remitente (solo crea remisiones)"""
        if self.es_cliente and hasattr(self, 'perfil_cliente'):
            return self.perfil_cliente.rol == 'remitente'
        return False

# 3. PERFIL INTERNO (Tu equipo)
class FuncionarioGeolab(models.Model):
    AREAS = [
        ('admin', 'Administrativo'),
        ('lab', 'Supervisor de Laboratorio'),
        ('recepcion', 'Recepción de Muestras'),
        ('tecnico', 'Técnico de Laboratorio'),
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
        ('remitente', 'Remitente (Solo crea remisiones)'),
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

    @property
    def obras_accesibles(self):
        """
        Retorna las obras a las que el cliente tiene acceso según su rol.
        - Director: todas las obras de su empresa
        - Residente/Remitente: solo las obras asignadas
        """
        from core.models import Obra
        if self.rol == 'director':
            return Obra.objects.filter(constructora=self.empresa).order_by('nombre')
        else:
            # Residente y Remitente usan obras asignadas
            return self.obras_asignadas.all().order_by('nombre')