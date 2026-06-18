import uuid
from django.db import models
from django.utils import timezone
from ensayos.geometry import (
    GEOMETRIA_CHOICES, GEOMETRIA_CILINDRO,
    DIMENSION_ESPECIMEN_CHOICES, clasificar_geometria,
)


class RemisionMuestras(models.Model):
    """
    Modelo maestro para la Remisión de Muestras de Concreto y Materiales.
    Código de formato: F-GC-05
    """

    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('enviada', 'Enviada - Pendiente de respuesta'),
        ('completada', 'Completada'),
        ('vencida', 'Vencida'),
    ]

    # Metadatos del formato
    codigo_formato = models.CharField(max_length=20, default='F-GC-05', editable=False)
    version_formato = models.CharField(max_length=10, default='01', editable=False)

    # Relaciones principales
    obra = models.ForeignKey(
        'core.Obra',
        on_delete=models.CASCADE,
        related_name='remisiones'
    )
    solicitado_por = models.ForeignKey(
        'users.UsuarioBase',
        on_delete=models.SET_NULL,
        null=True,
        related_name='remisiones_creadas'
    )

    # Identificador único y acceso
    orden_trabajo = models.PositiveIntegerField(
        verbose_name='Remision No.',
        editable=False,
        help_text='Consecutivo automático por obra'
    )
    # Campo deprecado - ya no se usa (sistema de tokens eliminado)
    token_acceso = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='borrador')

    # Datos del proyecto (pre-llenados automáticamente)
    cc = models.CharField(max_length=100, blank=True, verbose_name='C.C.')

    # Fechas
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    # Campo deprecado - ya no se usa (sistema de tokens eliminado)
    email_destinatario = models.EmailField(blank=True, null=True, verbose_name='Email del destinatario')

    # ========== CADENA DE CUSTODIA - CLIENTE ==========
    cliente_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha (Cliente)')
    cliente_cantidad = models.PositiveIntegerField(null=True, blank=True, verbose_name='Cantidad')
    cliente_estado = models.CharField(max_length=100, blank=True, verbose_name='Estado de muestras')
    cliente_firma_nombre = models.CharField(max_length=200, blank=True, verbose_name='Firma (Nombre)')
    cliente_observaciones = models.TextField(blank=True, verbose_name='Observaciones')

    # ========== CADENA DE CUSTODIA - LABORATORIO (Geolab llena después) ==========
    lab_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha recepción Lab')
    lab_cantidad = models.PositiveIntegerField(null=True, blank=True, verbose_name='Cantidad recibida')
    lab_estado = models.CharField(max_length=100, blank=True, verbose_name='Estado recibido')
    lab_firma_nombre = models.CharField(max_length=200, blank=True, verbose_name='Recibido por')
    lab_observaciones = models.TextField(blank=True, verbose_name='Observaciones Lab')

    # ========== CONTROL INTERNO (Geolab) ==========
    revisado_por = models.CharField(max_length=200, blank=True)
    programado = models.BooleanField(default=False)
    fecha_revision = models.DateField(null=True, blank=True)
    firma_revision = models.CharField(max_length=200, blank=True)

    # ========== MANIFIESTO - DATOS DEL FIRMANTE (Legal) ==========
    firmante_nombre = models.CharField(max_length=200, blank=True, verbose_name='Nombre completo del firmante')
    firmante_cedula = models.CharField(max_length=20, blank=True, verbose_name='Cédula')
    firmante_cargo = models.CharField(max_length=100, blank=True, verbose_name='Cargo')
    firmante_email = models.EmailField(blank=True, verbose_name='Email del firmante')
    firmante_telefono = models.CharField(max_length=20, blank=True, verbose_name='Teléfono')

    # Auditoría de la firma
    firma_ip_address = models.GenericIPAddressField(null=True, blank=True)
    firma_user_agent = models.TextField(blank=True)
    firma_fecha = models.DateTimeField(null=True, blank=True)
    acepta_veracidad = models.BooleanField(default=False, verbose_name='Acepta declaración de veracidad')

    class Meta:
        verbose_name = 'Remisión de Muestras'
        verbose_name_plural = 'Remisiones de Muestras'
        ordering = ['-fecha_creacion']
        unique_together = ['obra', 'orden_trabajo']

    def __str__(self):
        return f"Remisión {self.orden_trabajo} - {self.obra.nombre}"

    def save(self, *args, **kwargs):
        # Auto-generar orden_trabajo si es nueva remisión
        if not self.orden_trabajo:
            ultimo = RemisionMuestras.objects.filter(obra=self.obra).order_by('-orden_trabajo').first()
            if ultimo:
                try:
                    self.orden_trabajo = int(ultimo.orden_trabajo) + 1
                except (ValueError, TypeError):
                    self.orden_trabajo = RemisionMuestras.objects.filter(obra=self.obra).count() + 1
            else:
                self.orden_trabajo = 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('detalle_remision', kwargs={'pk': self.pk})

    @property
    def total_muestras(self):
        """Cuenta de filas de muestras"""
        return self.muestras.count()

    @property
    def total_cantidad(self):
        """Suma de cantidades de todas las muestras (cilindros totales)"""
        from django.db.models import Sum
        resultado = self.muestras.aggregate(total=Sum('cantidad'))
        return resultado['total'] or 0

    @property
    def esta_completada(self):
        return self.estado == 'completada'


class Muestra(models.Model):
    """
    Modelo detalle para cada muestra de la remisión.
    Cada fila de la tabla del formato físico.
    """

    TIPO_MUESTRA_CHOICES = [
        ('concreto', 'Concreto'),
        ('grouting', 'Grouting'),
        ('mortero', 'Mortero'),
        ('muretes', 'Muretes'),
        ('bloques', 'Bloques'),
        ('vigas', 'Vigas'),
        ('varilla', 'Varilla'),
        ('malla_elec', 'Malla Eléctrica'),
    ]

    # Tipos que por ahora NO generan hoja de trabajo: solo se almacenan en la
    # remisión (acero: varilla y malla electrosoldada).
    TIPOS_SIN_HOJA = ('varilla', 'malla_elec')

    remision = models.ForeignKey(
        RemisionMuestras,
        on_delete=models.CASCADE,
        related_name='muestras'
    )

    # Identificador
    numero_muestra = models.PositiveIntegerField(verbose_name='Muestra No.')

    # Cantidad de especímenes (cilindros, cubos, etc.) para esta edad
    cantidad = models.PositiveIntegerField(
        default=1,
        verbose_name='Cantidad',
        help_text='Cantidad de cilindros/especímenes a fallar en esta edad'
    )

    # Tipo de muestra (selección única)
    tipo_muestra = models.CharField(
        max_length=20,
        choices=TIPO_MUESTRA_CHOICES,
        verbose_name='Tipo de Muestra'
    )

    # Dimensión del espécimen (nuevo: select predefinido)
    dimension_especimen = models.CharField(
        max_length=20,
        choices=DIMENSION_ESPECIMEN_CHOICES,
        blank=True,
        default='',
        verbose_name='Dimensión del espécimen',
        help_text='Seleccione la dimensión estándar'
    )

    # Campos legacy — se mantienen para datos existentes
    UNIDAD_DIAMETRO_CHOICES = [
        ('mm', 'mm'),
        ('cm', 'cm'),
        ('pulg', 'pulg'),
    ]

    diametro_longitud = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Diámetro o Longitud'
    )
    unidad_diametro = models.CharField(
        max_length=10,
        choices=UNIDAD_DIAMETRO_CHOICES,
        default='cm',
        verbose_name='Unidad'
    )

    # Ensayos a realizar (checkboxes - pueden ser múltiples)
    ensayo_flexion = models.BooleanField(default=False, verbose_name='Flexión')
    ensayo_compresion = models.BooleanField(default=False, verbose_name='Compresión')
    ensayo_absorcion = models.BooleanField(default=False, verbose_name='Absorción')
    ensayo_otros = models.CharField(max_length=100, blank=True, verbose_name='Otros ensayos')

    # Localización
    localizacion = models.TextField(verbose_name='Localización de Muestra')

    # Fecha de toma
    fecha_toma = models.DateField(verbose_name='Fecha de Toma')

    # Edad y resistencia
    edad_ensayo_dias = models.PositiveIntegerField(
        verbose_name='Edad Ensayo (días)',
        help_text='Ej: 7, 14, 28 días'
    )
    fc_resistencia = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="F'c (MPa/Psi)",
        help_text='Resistencia esperada'
    )

    # Geometría derivada automáticamente de diametro_longitud + unidad_diametro
    geometria = models.CharField(
        max_length=20,
        choices=GEOMETRIA_CHOICES,
        default=GEOMETRIA_CILINDRO,
        editable=False,
        verbose_name='Geometría del espécimen'
    )

    class Meta:
        verbose_name = 'Muestra'
        verbose_name_plural = 'Muestras'
        ordering = ['numero_muestra', 'edad_ensayo_dias']
        # Permite mismo numero_muestra con diferentes edades
        unique_together = ['remision', 'numero_muestra', 'edad_ensayo_dias']

    def __str__(self):
        return f"Muestra {self.numero_muestra} ({self.cantidad} uds) - {self.edad_ensayo_dias} dias"

    def save(self, *args, **kwargs):
        self.geometria = clasificar_geometria(
            self.dimension_especimen, self.diametro_longitud, self.unidad_diametro
        )
        super().save(*args, **kwargs)

    @property
    def dimension_display(self):
        """Muestra la dimensión en formato legible."""
        from ensayos.geometry import DIMENSION_DISPLAY
        if self.dimension_especimen:
            return DIMENSION_DISPLAY.get(self.dimension_especimen, self.dimension_especimen)
        # Fallback legacy
        if self.diametro_longitud:
            return f"{self.diametro_longitud} {self.unidad_diametro}"
        return '-'

    @property
    def ensayos_list(self):
        """Retorna lista de ensayos seleccionados"""
        ensayos = []
        if self.ensayo_flexion:
            ensayos.append('Flexión')
        if self.ensayo_compresion:
            ensayos.append('Compresión')
        if self.ensayo_absorcion:
            ensayos.append('Absorción')
        if self.ensayo_otros:
            ensayos.append(self.ensayo_otros)
        return ensayos


class Notificacion(models.Model):
    """
    Modelo para notificaciones del sistema.
    Permite notificar a usuarios sobre nuevas remisiones y otros eventos.
    """

    TIPOS = [
        ('nueva_remision', 'Nueva Remision Recibida'),
        ('sistema', 'Notificacion del Sistema'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPOS)
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField()

    # Destinatario específico (null = todos los staff)
    destinatario = models.ForeignKey(
        'users.UsuarioBase',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='notificaciones'
    )

    # Si es solo para staff de Geolab
    solo_staff = models.BooleanField(default=True)

    # Relación opcional con remisión
    remision = models.ForeignKey(
        'RemisionMuestras',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='notificaciones'
    )

    # Estado
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{self.titulo} - {'Leída' if self.leida else 'No leída'}"

    def marcar_leida(self):
        """Marca la notificación como leída"""
        if not self.leida:
            self.leida = True
            self.fecha_lectura = timezone.now()
            self.save()
