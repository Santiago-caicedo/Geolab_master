from django.db import models
from datetime import timedelta
from math import pi
from decimal import Decimal, InvalidOperation


class HojaTrabajo(models.Model):
    """
    Representa el Excel F-GT-05 digitalizado.
    Se crea automáticamente cuando una remisión pasa a estado 'completada'.
    Contiene la relación de muestras ensayadas de cilindros, grouting, morteros y vigas.
    """

    # Relación con remisión (1:1)
    remision = models.OneToOneField(
        'solicitudes.RemisionMuestras',
        on_delete=models.CASCADE,
        related_name='hoja_trabajo',
        verbose_name='Remisión'
    )

    # Metadatos del formato
    codigo_formato = models.CharField(
        max_length=20,
        default='F-GT-05',
        editable=False,
        verbose_name='Código de Formato'
    )
    version_formato = models.CharField(
        max_length=10,
        default='02',
        editable=False,
        verbose_name='Versión'
    )

    # Estado del proceso
    ESTADOS = [
        ('pendiente', 'Pendiente de ensayos'),
        ('en_proceso', 'Ensayos en proceso'),
        ('completada', 'Ensayos completados'),
        ('informe_generado', 'Informe generado'),
    ]
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='pendiente',
        verbose_name='Estado'
    )

    # Control de fechas
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    # Número de informe generado
    numero_informe = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Número de Informe'
    )

    # Técnico responsable
    realizado_por = models.ForeignKey(
        'users.UsuarioBase',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hojas_trabajo',
        verbose_name='Realizado por'
    )

    # Observaciones generales
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')

    class Meta:
        verbose_name = 'Hoja de Trabajo'
        verbose_name_plural = 'Hojas de Trabajo'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"F-GT-05 - {self.remision.obra.nombre} - Remisión #{self.remision.orden_trabajo}"

    @property
    def obra(self):
        """Acceso directo a la obra"""
        return self.remision.obra

    @property
    def constructora(self):
        """Acceso directo a la constructora"""
        return self.remision.obra.constructora

    @property
    def total_muestras(self):
        """Total de muestras/resultados en esta hoja"""
        return self.resultados.count()

    @property
    def muestras_completadas(self):
        """Cantidad de muestras con ensayo completado"""
        return self.resultados.filter(estado='completado').count()

    @property
    def muestras_pendientes(self):
        """Cantidad de muestras pendientes de ensayo"""
        return self.resultados.filter(estado='pendiente').count()

    @property
    def progreso(self):
        """Porcentaje de progreso (0-100)"""
        total = self.total_muestras
        if total == 0:
            return 0
        return int((self.muestras_completadas / total) * 100)

    @property
    def muestras_para_hoy(self):
        """Muestras que deben fallarse hoy"""
        from django.utils import timezone
        hoy = timezone.now().date()
        return self.resultados.filter(
            estado='pendiente'
        ).filter(
            muestra__fecha_toma__isnull=False,
            muestra__edad_ensayo_dias__isnull=False
        ).select_related('muestra')

    def actualizar_estado(self):
        """Actualiza el estado de la hoja según el progreso"""
        if self.muestras_completadas == 0:
            self.estado = 'pendiente'
        elif self.muestras_completadas < self.total_muestras:
            self.estado = 'en_proceso'
        else:
            self.estado = 'completada'
        self.save(update_fields=['estado'])


class ResultadoMuestra(models.Model):
    """
    Resultados del ensayo para cada muestra.
    Contiene los datos que el técnico llena en laboratorio + cálculos automáticos.
    Equivale a una fila del Excel F-GT-05.
    """

    # Relación con hoja de trabajo
    hoja_trabajo = models.ForeignKey(
        HojaTrabajo,
        on_delete=models.CASCADE,
        related_name='resultados',
        verbose_name='Hoja de Trabajo'
    )

    # Referencia a la muestra original (datos de la remisión)
    muestra = models.OneToOneField(
        'solicitudes.Muestra',
        on_delete=models.CASCADE,
        related_name='resultado_ensayo',
        verbose_name='Muestra'
    )

    # Estado del ensayo individual
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('completado', 'Completado'),
        ('fallido', 'Muestra descartada'),
    ]
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='pendiente',
        verbose_name='Estado'
    )

    # ══════════════════════════════════════════════════════════════════════════
    # DATOS QUE LLENA EL TÉCNICO (Columnas H-W del Excel)
    # ══════════════════════════════════════════════════════════════════════════

    # Mediciones de diámetro (mm) - 3 mediciones con vernier
    diametro_d1 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Diámetro D1 (mm)'
    )
    diametro_d2 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Diámetro D2 (mm)'
    )
    diametro_d3 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Diámetro D3 (mm)'
    )

    # Mediciones de longitud (mm) - 3 mediciones con vernier
    longitud_l1 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Longitud L1 (mm)'
    )
    longitud_l2 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Longitud L2 (mm)'
    )
    longitud_l3 = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='Longitud L3 (mm)'
    )

    # Peso del cilindro
    peso_gramos = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name='Peso (g)'
    )

    # Carga máxima de rotura (resultado de la prensa)
    carga_maxima_kn = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name='Carga Máxima (KN)'
    )

    # Tipo de falla observada
    TIPOS_FALLA = [
        ('', '-- Seleccionar --'),
        ('tipo_1', 'Tipo 1 - Conos razonablemente bien formados en ambos extremos'),
        ('tipo_2', 'Tipo 2 - Cono bien formado en un extremo, fisuras verticales'),
        ('tipo_3', 'Tipo 3 - Fisuras verticales columnares en ambos extremos'),
        ('tipo_4', 'Tipo 4 - Fractura diagonal sin fisuras en los extremos'),
        ('tipo_5', 'Tipo 5 - Fracturas en los lados en las partes superior o inferior'),
        ('tipo_6', 'Tipo 6 - Similar al tipo 5 pero el extremo del cilindro es puntiagudo'),
    ]
    forma_falla = models.CharField(
        max_length=20,
        choices=TIPOS_FALLA,
        blank=True,
        default='',
        verbose_name='Forma de Falla'
    )

    # Observaciones específicas de esta muestra
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')

    # Fecha real en que se realizó el ensayo
    fecha_ensayo = models.DateField(
        null=True,
        blank=True,
        verbose_name='Fecha de Ensayo'
    )

    # Campo para selección en la hoja global (checkbox)
    seleccionado = models.BooleanField(
        default=False,
        verbose_name='Seleccionado para informe'
    )

    class Meta:
        verbose_name = 'Resultado de Muestra'
        verbose_name_plural = 'Resultados de Muestras'
        ordering = ['muestra__numero_muestra', 'muestra__edad_ensayo_dias']

    def __str__(self):
        return f"Muestra #{self.muestra.numero_muestra} - {self.muestra.edad_ensayo_dias} días"

    # ══════════════════════════════════════════════════════════════════════════
    # PROPIEDADES CALCULADAS (Equivalentes a las fórmulas del Excel)
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def fecha_falla_programada(self):
        """
        FECHA_FALLA = FECHA_TOMA + EDAD_DIAS
        Calcula la fecha en que debe realizarse el ensayo.
        """
        if self.muestra.fecha_toma and self.muestra.edad_ensayo_dias:
            return self.muestra.fecha_toma + timedelta(days=self.muestra.edad_ensayo_dias)
        return None

    @property
    def debe_fallarse_hoy(self):
        """Indica si esta muestra debe fallarse hoy"""
        from django.utils import timezone
        if self.fecha_falla_programada:
            return self.fecha_falla_programada == timezone.now().date()
        return False

    @property
    def dias_para_falla(self):
        """Días restantes hasta la fecha de falla (negativo si ya pasó)"""
        from django.utils import timezone
        if self.fecha_falla_programada:
            return (self.fecha_falla_programada - timezone.now().date()).days
        return None

    @property
    def diametro_real(self):
        """
        DIÁMETRO REAL = PROMEDIO(D1, D2, D3)
        Promedio de las 3 mediciones de diámetro en mm.
        """
        if all([self.diametro_d1, self.diametro_d2, self.diametro_d3]):
            promedio = (self.diametro_d1 + self.diametro_d2 + self.diametro_d3) / 3
            return round(promedio, 2)
        return None

    @property
    def longitud_real(self):
        """
        LONGITUD REAL = PROMEDIO(L1, L2, L3)
        Promedio de las 3 mediciones de longitud en mm.
        """
        if all([self.longitud_l1, self.longitud_l2, self.longitud_l3]):
            promedio = (self.longitud_l1 + self.longitud_l2 + self.longitud_l3) / 3
            return round(promedio, 2)
        return None

    @property
    def area_mm2(self):
        """
        ÁREA = PI * DIÁMETRO² / 4 / 100
        Área de la sección transversal en mm².
        """
        if self.diametro_real:
            area = (Decimal(str(pi)) * (self.diametro_real ** 2) / 4) / 100
            return round(area, 2)
        return None

    @property
    def esfuerzo_mpa(self):
        """
        ESFUERZO = (CARGA_KN * 101.9716 / ÁREA) / 10
        Resistencia real a la compresión en MPa.
        """
        if self.carga_maxima_kn and self.area_mm2:
            esfuerzo = (self.carga_maxima_kn * Decimal('101.9716') / self.area_mm2) / 10
            return round(esfuerzo, 2)
        return None

    @property
    def porcentaje_desarrollo(self):
        """
        % DESARROLLO = (ESFUERZO / F'c) * 100
        Porcentaje de la resistencia alcanzada vs la esperada.
        """
        if self.esfuerzo_mpa and self.muestra.fc_resistencia:
            try:
                fc = Decimal(str(self.muestra.fc_resistencia))
                if fc > 0:
                    porcentaje = (self.esfuerzo_mpa / fc) * 100
                    return round(porcentaje, 1)
            except (ValueError, TypeError, InvalidOperation):
                pass
        return None

    @property
    def cumple_resistencia(self):
        """
        Indica si la muestra alcanzó >= 100% de la resistencia esperada.
        """
        if self.porcentaje_desarrollo is not None:
            return self.porcentaje_desarrollo >= 100
        return None

    @property
    def tiene_mediciones_completas(self):
        """Indica si se han llenado todas las mediciones requeridas"""
        return all([
            self.diametro_d1, self.diametro_d2, self.diametro_d3,
            self.longitud_l1, self.longitud_l2, self.longitud_l3,
            self.peso_gramos, self.carga_maxima_kn
        ])

    def marcar_completado(self):
        """Marca el resultado como completado si tiene todos los datos"""
        if self.tiene_mediciones_completas:
            self.estado = 'completado'
            if not self.fecha_ensayo:
                from django.utils import timezone
                self.fecha_ensayo = timezone.now().date()
            self.save()
            # Actualizar estado de la hoja de trabajo
            self.hoja_trabajo.actualizar_estado()
            return True
        return False
