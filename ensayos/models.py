from django.db import models, transaction
from datetime import timedelta


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

    # ══════════════════════════════════════════════════════════════════════════
    # CAMPOS ESPECÍFICOS PARA VIGAS (Flexión NTC 2871)
    # Solo aplican cuando la muestra es geometría 'prisma'
    # ══════════════════════════════════════════════════════════════════════════

    luz_entre_apoyos = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        verbose_name='Luz entre apoyos L (mm)',
        help_text='Distancia entre apoyos inferiores en mm'
    )

    distancia_falla_apoyo = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        verbose_name='Distancia falla-apoyo a (mm)',
        help_text='Distancia de la línea de falla al apoyo más próximo en mm'
    )

    FORMULA_FLEXION_CHOICES = [
        ('', '-- Seleccionar --'),
        ('A', 'A - Falla en tercio medio'),
        ('B', 'B - Falla fuera del tercio medio'),
    ]
    formula_flexion = models.CharField(
        max_length=1,
        choices=FORMULA_FLEXION_CHOICES,
        blank=True,
        default='',
        verbose_name='Fórmula usada',
        help_text='A: falla en tercio medio, B: falla fuera del tercio medio'
    )

    TIPO_ESPECIMEN_VIGA_CHOICES = [
        ('', '-- Seleccionar --'),
        ('F', 'Fundido'),
        ('C', 'Cortado'),
    ]
    tipo_especimen_viga = models.CharField(
        max_length=1,
        choices=TIPO_ESPECIMEN_VIGA_CHOICES,
        blank=True,
        default='',
        verbose_name='Tipo espécimen',
        help_text='F: Fundido, C: Cortado'
    )

    # Informe generado que incluye este resultado (marca de inclusión)
    informe_ensayo = models.ForeignKey(
        'ensayos.InformeEnsayo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resultados',
        verbose_name='Informe de ensayo'
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
    def _macro(self):
        """Obtiene la macro de cálculo según la geometría de la muestra."""
        from ensayos.macros import get_macro
        return get_macro(self.muestra.geometria)

    @property
    def _valores_cilindro(self):
        """
        Cadena de cálculo exacta estilo Excel para cilindros (con corrección
        de instrumento y polinomio de la prensa). None para otras geometrías.
        """
        from ensayos.macros import MacroCilindro
        macro = self._macro
        if not isinstance(macro, MacroCilindro):
            return None
        return macro.calcular_valores_exactos(
            self.diametro_d1, self.diametro_d2, self.diametro_d3,
            self.longitud_l1, self.longitud_l2, self.longitud_l3,
            self.carga_maxima_kn, self.muestra.fc_resistencia,
            dimension=self.muestra.dimension_especimen,
        )

    @property
    def diametro_real(self):
        """Promedio de las 3 mediciones de diámetro/lado A en mm.
        Cilindros: incluye corrección de instrumento según dimensión."""
        vals = self._valores_cilindro
        if vals is not None:
            from ensayos.macros import redondear_half_up
            return redondear_half_up(vals['diametro_real'], 2)
        return self._macro.calcular_dimension_real(
            self.diametro_d1, self.diametro_d2, self.diametro_d3
        )

    @property
    def longitud_real(self):
        """Promedio de las 3 mediciones de longitud/lado B en mm.
        Cilindros: incluye corrección de instrumento según dimensión."""
        vals = self._valores_cilindro
        if vals is not None:
            from ensayos.macros import redondear_half_up
            return redondear_half_up(vals['longitud_real'], 2)
        return self._macro.calcular_dimension_real(
            self.longitud_l1, self.longitud_l2, self.longitud_l3
        )

    @property
    def area_mm2(self):
        """Área de la sección transversal. Fórmula varía según geometría.
        Cilindros: calculada desde el diámetro corregido SIN redondeos intermedios."""
        vals = self._valores_cilindro
        if vals is not None:
            from ensayos.macros import redondear_half_up
            return redondear_half_up(vals['area'], 2)
        return self._macro.calcular_area(self.diametro_real, self.longitud_real)

    @property
    def esfuerzo_mpa(self):
        """Resistencia/módulo de rotura en MPa. Fórmula varía según geometría.
        Cilindros: carga corregida por el polinomio de la prensa, cadena exacta."""
        from ensayos.geometry import GEOMETRIA_PRISMA
        if self.muestra.geometria == GEOMETRIA_PRISMA:
            return self._macro.calcular_esfuerzo_viga(
                self.carga_maxima_kn,
                self.diametro_real,   # b (ancho)
                self.longitud_real,   # d (altura)
                self.luz_entre_apoyos,
                self.distancia_falla_apoyo,
                self.formula_flexion,
            )
        vals = self._valores_cilindro
        if vals is not None:
            from ensayos.macros import redondear_half_up
            return redondear_half_up(vals['esfuerzo'], 2)
        return self._macro.calcular_esfuerzo(self.carga_maxima_kn, self.area_mm2)

    @property
    def porcentaje_desarrollo(self):
        """Porcentaje de la resistencia alcanzada vs la esperada."""
        from ensayos.geometry import GEOMETRIA_PRISMA
        if self.muestra.geometria != GEOMETRIA_PRISMA:
            vals = self._valores_cilindro
            if vals is not None:
                from ensayos.macros import redondear_half_up
                return redondear_half_up(vals['porcentaje'], 1)
        return self._macro.calcular_porcentaje(
            self.esfuerzo_mpa, self.muestra.fc_resistencia
        )

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


class ConsecutivoInforme(models.Model):
    """
    Contador del consecutivo de informes, global por año.
    Formato del número: INF{n}-{año} (ej. INF1079-2026).
    """
    anio = models.PositiveIntegerField(unique=True, verbose_name='Año')
    ultimo = models.PositiveIntegerField(default=0, verbose_name='Último consecutivo')

    class Meta:
        verbose_name = 'Consecutivo de Informe'
        verbose_name_plural = 'Consecutivos de Informe'

    def __str__(self):
        return f"{self.anio}: {self.ultimo}"

    @classmethod
    def siguiente(cls, anio):
        """Asigna y devuelve el siguiente número de informe de forma atómica."""
        with transaction.atomic():
            contador, _ = cls.objects.select_for_update().get_or_create(anio=anio)
            contador.ultimo += 1
            contador.save(update_fields=['ultimo'])
            return f"INF{contador.ultimo}-{anio}"


class InformeEnsayo(models.Model):
    """
    Informe de resultados generado a partir de la plantilla Excel oficial.
    Un informe = (obra, tipo, fecha de falla). Reusa el mismo N° al re-generar.
    """
    TIPO_CHOICES = [
        ('compresion_cilindros', 'Compresión de cilindros de concreto'),
    ]

    obra = models.ForeignKey(
        'core.Obra', on_delete=models.CASCADE, related_name='informes_ensayo'
    )
    tipo = models.CharField(
        max_length=30, choices=TIPO_CHOICES, default='compresion_cilindros'
    )
    numero_informe = models.CharField(max_length=50, unique=True)
    fecha_falla = models.DateField(verbose_name='Fecha de falla')
    fecha_emision = models.DateField(auto_now_add=True)
    ciudad = models.CharField(max_length=100, blank=True)
    generado_por = models.ForeignKey(
        'users.UsuarioBase', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='informes_ensayo_generados'
    )
    archivo_xlsx = models.FileField(
        upload_to='informes_ensayo/%Y/%m/', null=True, blank=True
    )
    archivo_pdf = models.FileField(
        upload_to='informes_ensayo/%Y/%m/', null=True, blank=True
    )

    class Meta:
        verbose_name = 'Informe de Ensayo'
        verbose_name_plural = 'Informes de Ensayo'
        ordering = ['-fecha_emision', '-id']
        unique_together = ['obra', 'tipo', 'fecha_falla']

    def __str__(self):
        return f"{self.numero_informe} - {self.obra.nombre}"
