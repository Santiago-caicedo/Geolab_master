from django.db import models
from django.conf import settings


class AreaCalidad(models.Model):
    """Las 8 áreas del Sistema de Gestión de Calidad."""
    ICONOS_CHOICES = [
        ('bi-briefcase', 'Maletín'),
        ('bi-cart', 'Carrito'),
        ('bi-bag', 'Bolsa'),
        ('bi-people', 'Personas'),
        ('bi-wrench', 'Herramienta'),
        ('bi-clipboard2-check', 'Portapapeles'),
        ('bi-shield-check', 'Escudo'),
        ('bi-truck', 'Camión'),
    ]

    numero = models.PositiveSmallIntegerField(unique=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    icono = models.CharField(max_length=50, default='bi-folder')

    class Meta:
        ordering = ['numero']
        verbose_name = 'Área de Calidad'
        verbose_name_plural = 'Áreas de Calidad'

    def __str__(self):
        return f"{self.numero}. {self.nombre}"


class Carpeta(models.Model):
    """Carpetas recursivas dentro de un área de calidad."""
    nombre = models.CharField(max_length=255)
    area = models.ForeignKey(
        AreaCalidad, on_delete=models.CASCADE, related_name='carpetas'
    )
    padre = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='subcarpetas'
    )
    orden = models.PositiveSmallIntegerField(default=0)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='carpetas_creadas'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'Carpeta'
        verbose_name_plural = 'Carpetas'
        unique_together = [('nombre', 'area', 'padre')]

    def __str__(self):
        return self.nombre

    @property
    def ruta_breadcrumb(self):
        """Retorna la lista de ancestros desde la raíz hasta esta carpeta."""
        partes = []
        actual = self
        while actual is not None:
            partes.append(actual)
            actual = actual.padre
        partes.reverse()
        return partes

    @property
    def esta_vacia(self):
        """True si no tiene subcarpetas ni documentos."""
        return (
            not self.subcarpetas.exists()
            and not self.documentos.exists()
        )


class Documento(models.Model):
    """Archivos subidos a una carpeta del sistema de calidad."""
    nombre = models.CharField(max_length=255)
    carpeta = models.ForeignKey(
        Carpeta, on_delete=models.CASCADE, related_name='documentos'
    )
    archivo = models.FileField(upload_to='calidad/%Y/%m/')
    tipo_archivo = models.CharField(max_length=50, blank=True)
    tamano_bytes = models.PositiveBigIntegerField(default=0)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='documentos_calidad'
    )
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if self.archivo and not self.tipo_archivo:
            ext = self.archivo.name.rsplit('.', 1)[-1].lower() if '.' in self.archivo.name else ''
            self.tipo_archivo = ext
        if self.archivo and not self.tamano_bytes:
            try:
                self.tamano_bytes = self.archivo.size
            except Exception:
                pass
        super().save(*args, **kwargs)

    @property
    def icono_tipo(self):
        """Retorna clase de icono Bootstrap según extensión."""
        iconos = {
            'pdf': 'bi-file-earmark-pdf text-danger',
            'doc': 'bi-file-earmark-word text-primary',
            'docx': 'bi-file-earmark-word text-primary',
            'xls': 'bi-file-earmark-excel text-success',
            'xlsx': 'bi-file-earmark-excel text-success',
            'ppt': 'bi-file-earmark-ppt text-warning',
            'pptx': 'bi-file-earmark-ppt text-warning',
            'jpg': 'bi-file-earmark-image text-info',
            'jpeg': 'bi-file-earmark-image text-info',
            'png': 'bi-file-earmark-image text-info',
        }
        return iconos.get(self.tipo_archivo, 'bi-file-earmark text-secondary')

    @property
    def tamano_legible(self):
        """Retorna tamaño en formato legible (KB, MB)."""
        if self.tamano_bytes < 1024:
            return f"{self.tamano_bytes} B"
        elif self.tamano_bytes < 1024 * 1024:
            return f"{self.tamano_bytes / 1024:.1f} KB"
        else:
            return f"{self.tamano_bytes / (1024 * 1024):.1f} MB"


class AccesoCarpetaUsuario(models.Model):
    """
    Permisos POR CARPETA para los Usuarios de Calidad (rol creado por el
    Coordinador de Calidad). A diferencia de AccesoAreaUsuario (por area,
    para el staff), aqui el acceso es carpeta por carpeta y con tres niveles
    combinables. Una carpeta sin fila = sin acceso (bloqueo total).

    Regla: cargar o eliminar implican ver (se fuerza en save), porque no se
    puede operar sobre una carpeta que no se puede abrir.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='accesos_carpetas_calidad'
    )
    carpeta = models.ForeignKey(
        Carpeta, on_delete=models.CASCADE, related_name='accesos_usuarios'
    )
    puede_ver = models.BooleanField(
        default=True,
        help_text='Abrir la carpeta y ver/descargar sus documentos.'
    )
    puede_cargar = models.BooleanField(
        default=False,
        help_text='Subir documentos y crear subcarpetas dentro de la carpeta.'
    )
    puede_eliminar = models.BooleanField(
        default=False,
        help_text='Eliminar documentos de la carpeta.'
    )
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accesos_carpetas_asignados'
    )
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('usuario', 'carpeta')]
        verbose_name = 'Acceso a Carpeta'
        verbose_name_plural = 'Accesos a Carpetas'

    def __str__(self):
        letras = ''.join([
            'V' if self.puede_ver else '-',
            'C' if self.puede_cargar else '-',
            'E' if self.puede_eliminar else '-',
        ])
        return f"{self.usuario} → {self.carpeta} [{letras}]"

    def save(self, *args, **kwargs):
        # Cargar o eliminar sin ver no tiene sentido: se fuerza la coherencia.
        if self.puede_cargar or self.puede_eliminar:
            self.puede_ver = True
        super().save(*args, **kwargs)


class AccesoAreaUsuario(models.Model):
    """Permisos de acceso por área para cada usuario Geolab."""
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='accesos_calidad'
    )
    area = models.ForeignKey(
        AreaCalidad, on_delete=models.CASCADE, related_name='accesos'
    )
    puede_editar = models.BooleanField(
        default=False,
        help_text='Si es True, puede subir/crear. Si es False, solo lectura.'
    )
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='accesos_asignados'
    )
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('usuario', 'area')]
        verbose_name = 'Acceso a Área'
        verbose_name_plural = 'Accesos a Áreas'

    def __str__(self):
        modo = "Edición" if self.puede_editar else "Lectura"
        return f"{self.usuario} → {self.area} ({modo})"
