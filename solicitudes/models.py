import uuid
from django.db import models
from django.utils import timezone


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
    token_acceso = models.CharField(max_length=64, unique=True, editable=False)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='borrador')

    # Datos del proyecto (pre-llenados automáticamente)
    cc = models.CharField(max_length=100, blank=True, verbose_name='C.C.')

    # Fechas
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    # Email del destinatario
    email_destinatario = models.EmailField(blank=True, verbose_name='Email del destinatario')

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
        if not self.token_acceso:
            self.token_acceso = uuid.uuid4().hex
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

    def get_public_url(self):
        from django.urls import reverse
        return reverse('responder_remision', kwargs={'token': self.token_acceso})

    @property
    def total_muestras(self):
        return self.muestras.count()

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

    # Dimensiones
    diametro_longitud = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Diámetro o Longitud (cm)'
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

    class Meta:
        verbose_name = 'Muestra'
        verbose_name_plural = 'Muestras'
        ordering = ['numero_muestra', 'edad_ensayo_dias']
        # Permite mismo numero_muestra con diferentes edades
        unique_together = ['remision', 'numero_muestra', 'edad_ensayo_dias']

    def __str__(self):
        return f"Muestra {self.numero_muestra} ({self.cantidad} uds) - {self.edad_ensayo_dias} dias"

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
