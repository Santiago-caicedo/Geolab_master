from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


class CategoriaServicio(models.Model):
    """
    Categorías de servicios de laboratorio.
    Ej: "CONCRETOS", "SUELOS", "TRANSPORTE"
    IMPORTANTE: La categoría con codigo='7' es TRANSPORTE (tratamiento especial de IVA).
    """
    codigo = models.CharField(max_length=20, unique=True, verbose_name='Código')
    nombre = models.CharField(max_length=255, verbose_name='Nombre')

    class Meta:
        ordering = ['codigo']
        verbose_name = 'Categoría de Servicio'
        verbose_name_plural = 'Categorías de Servicio'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def es_transporte(self):
        return self.codigo == '7'


class TipoServicio(models.Model):
    """
    Servicios específicos del laboratorio.
    Cada servicio pertenece a una categoría y tiene un código único.
    """
    categoria = models.ForeignKey(
        CategoriaServicio, on_delete=models.CASCADE,
        related_name='servicios', verbose_name='Categoría'
    )
    codigo = models.CharField(max_length=20, unique=True, verbose_name='Código')
    nombre = models.CharField(max_length=255, unique=True, verbose_name='Nombre')
    norma = models.CharField(
        max_length=100, blank=True,
        verbose_name='Norma técnica', help_text='Norma técnica aplicable'
    )

    class Meta:
        ordering = ['categoria__codigo', 'codigo']
        verbose_name = 'Tipo de Servicio'
        verbose_name_plural = 'Tipos de Servicio'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class PrecioServicio(models.Model):
    """
    Precio personalizado de un servicio para una obra específica.
    Cada obra tiene su propia lista de precios.
    Un precio null = no configurado.
    """
    obra = models.ForeignKey(
        'core.Obra', on_delete=models.CASCADE,
        related_name='lista_de_precios', verbose_name='Obra'
    )
    tipo_servicio = models.ForeignKey(
        TipoServicio, on_delete=models.CASCADE,
        verbose_name='Tipo de Servicio'
    )
    precio = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Precio unitario',
        help_text='Dejar vacío si no aplica para esta obra'
    )

    class Meta:
        unique_together = ('obra', 'tipo_servicio')
        verbose_name = 'Precio de Servicio'
        verbose_name_plural = 'Precios de Servicio'

    def __str__(self):
        precio_str = f"${self.precio:,.2f}" if self.precio else "Sin precio"
        return f"{self.tipo_servicio.nombre} → {self.obra.nombre}: {precio_str}"


class Impuesto(models.Model):
    """
    Configuración de impuestos. Se busca por nombre__iexact='IVA'.
    """
    nombre = models.CharField(max_length=50, unique=True, verbose_name='Nombre')
    porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2,
        verbose_name='Porcentaje', help_text='Ej: 19.00 para 19%'
    )
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name = 'Impuesto'
        verbose_name_plural = 'Impuestos'

    def __str__(self):
        return f"{self.nombre} ({self.porcentaje}%)"


class RegistroServicio(models.Model):
    """
    Registro de un servicio realizado.
    El precio se CONGELA al momento del registro (price freezing).
    """
    obra = models.ForeignKey(
        'core.Obra', on_delete=models.PROTECT,
        related_name='registros_servicio', verbose_name='Obra'
    )
    tipo_servicio = models.ForeignKey(
        TipoServicio, on_delete=models.PROTECT,
        related_name='registros', verbose_name='Tipo de Servicio'
    )
    fecha_realizacion = models.DateField(
        default=timezone.now, verbose_name='Fecha de realización'
    )
    cantidad = models.PositiveIntegerField(default=1, verbose_name='Cantidad')
    numero_informe = models.CharField(
        max_length=100, verbose_name='Número de informe',
        help_text='Número del informe de laboratorio'
    )
    precio_unitario_congelado = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name='Precio unitario',
        help_text='Precio congelado al momento del registro'
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name='Subtotal', editable=False
    )
    facturar_despues = models.BooleanField(
        default=False, verbose_name='Facturar después'
    )
    factura = models.ForeignKey(
        'Factura', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='registros', verbose_name='Factura'
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='registros_facturacion'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_realizacion', '-id']
        verbose_name = 'Registro de Servicio'
        verbose_name_plural = 'Registros de Servicio'

    def __str__(self):
        return f"{self.tipo_servicio.codigo} × {self.cantidad} - {self.obra.nombre}"

    def save(self, *args, **kwargs):
        self.subtotal = self.precio_unitario_congelado * self.cantidad
        super().save(*args, **kwargs)

    @property
    def esta_facturado(self):
        return self.factura is not None

    @property
    def es_transporte(self):
        return self.tipo_servicio.categoria.es_transporte


class Factura(models.Model):
    """
    Factura generada a partir de registros de servicio.
    """
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADA', 'Pagada'),
        ('ANULADA', 'Anulada'),
    ]

    constructora = models.ForeignKey(
        'users.Constructora', on_delete=models.PROTECT,
        related_name='facturas', verbose_name='Constructora'
    )
    obra = models.ForeignKey(
        'core.Obra', on_delete=models.PROTECT,
        related_name='facturas', verbose_name='Obra'
    )
    fecha_inicio_periodo = models.DateField(verbose_name='Inicio del periodo')
    fecha_fin_periodo = models.DateField(verbose_name='Fin del periodo')
    fecha_emision = models.DateField(default=timezone.now, verbose_name='Fecha de emisión')
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name='Subtotal'
    )
    monto_iva = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name='Monto IVA'
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name='Total'
    )
    iva_transporte_facturado = models.BooleanField(
        default=False, verbose_name='IVA transporte aplicado',
        help_text='Indica si se aplicó IVA a servicios de transporte'
    )
    estado = models.CharField(
        max_length=10, choices=ESTADOS, default='PENDIENTE',
        verbose_name='Estado'
    )
    pdf_archivo = models.FileField(
        upload_to='facturas/%Y/%m/', null=True, blank=True,
        verbose_name='PDF'
    )
    emitida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='facturas_emitidas'
    )

    class Meta:
        ordering = ['-fecha_emision']
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'

    def __str__(self):
        return f"Factura #{self.pk} - {self.obra.nombre} ({self.get_estado_display()})"

    @property
    def esta_anulada(self):
        return self.estado == 'ANULADA'

    @property
    def total_registros(self):
        return self.registros.count()
