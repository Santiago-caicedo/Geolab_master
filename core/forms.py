import unicodedata
from datetime import datetime, time

from django import forms
from django.utils import timezone
from users.models import Constructora
from .models import Obra


def _sin_acentos(texto):
    """Normaliza para comparar ciudades sin distinguir tildes ni mayúsculas."""
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto or '')
        if not unicodedata.combining(c)
    ).strip().lower()


MAX_INFORMES_POR_CARGA = 100   # = DATA_UPLOAD_MAX_NUMBER_FILES por defecto de Django
TIPOS_PDF = ('application/pdf', 'application/x-pdf', 'application/acrobat', '')


def titulo_desde_archivo(nombre):
    """'INF 0340-2026 VIGAS.pdf' -> 'INF 0340-2026 VIGAS' (el título del informe es el nombre del archivo)."""
    base = nombre.replace('\\', '/').rsplit('/', 1)[-1]
    if base.lower().endswith('.pdf'):
        base = base[:-4]
    return base.strip()[:255]


class VariosPdfInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class VariosPdfField(forms.FileField):
    """Campo de archivos múltiples: devuelve una lista de archivos subidos."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', VariosPdfInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,application/pdf',
            'multiple': True,
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            return [super(VariosPdfField, self).clean(d, initial) for d in data if d]
        return [super().clean(data, initial)] if data else super().clean(data, initial)


class InformeForm(forms.Form):
    """Carga de uno o varios informes técnicos (PDF) a una obra.
    Cada archivo es un Informe; su título es el nombre del archivo."""

    obra = forms.ModelChoiceField(
        queryset=Obra.objects.none(), label='Obra destino',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    # Fecha que se muestra en el portal (Informe.fecha_creacion). Por defecto hoy,
    # editable para cargar informes de fechas anteriores. Es la misma para todos.
    fecha = forms.DateField(
        label='Fecha del informe',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
    )
    archivos = VariosPdfField(label='Archivos PDF')

    def __init__(self, *args, **kwargs):
        # Permitir filtrar obras por constructora si se pasa
        constructora = kwargs.pop('constructora', None)
        super().__init__(*args, **kwargs)

        # Ordenar obras por constructora y nombre
        self.fields['obra'].queryset = Obra.objects.select_related('constructora').order_by(
            'constructora__nombre', 'nombre'
        )

        # Si se especifica constructora, filtrar solo esas obras
        if constructora:
            self.fields['obra'].queryset = self.fields['obra'].queryset.filter(
                constructora=constructora
            )

        # Mostrar nombre completo con constructora en el select
        self.fields['obra'].label_from_instance = lambda obj: f"{obj.constructora.nombre} → {obj.nombre}"

        hoy = timezone.localdate()
        self.fields['fecha'].initial = hoy
        self.fields['fecha'].widget.attrs['max'] = hoy.isoformat()

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha > timezone.localdate():
            raise forms.ValidationError('La fecha del informe no puede ser futura.')
        return fecha

    def fecha_creacion(self):
        """Fecha elegida como datetime: hoy = hora actual; otro día = mediodía de ese día."""
        fecha = self.cleaned_data['fecha']
        if fecha == timezone.localdate():
            return timezone.now()
        return timezone.make_aware(datetime.combine(fecha, time(12, 0)))

    def clean_archivos(self):
        """Todos deben ser PDF de verdad (extensión, tipo y contenido); si uno falla no se carga ninguno."""
        archivos = self.cleaned_data.get('archivos') or []
        if len(archivos) > MAX_INFORMES_POR_CARGA:
            raise forms.ValidationError(
                f'Máximo {MAX_INFORMES_POR_CARGA} informes por carga (elegiste {len(archivos)}).')
        errores, vistos = [], set()
        for archivo in archivos:
            nombre = archivo.name
            if not nombre.lower().endswith('.pdf'):
                errores.append(f'"{nombre}" no es un PDF.')
                continue
            if getattr(archivo, 'content_type', '') not in TIPOS_PDF:
                errores.append(f'"{nombre}" no es un PDF válido.')
                continue
            archivo.seek(0)
            inicio = archivo.read(1024)
            archivo.seek(0)
            if b'%PDF' not in inicio:
                errores.append(f'"{nombre}" no es un PDF válido (el contenido no es PDF).')
                continue
            titulo = titulo_desde_archivo(nombre)
            if not titulo:
                errores.append(f'"{nombre}" no tiene nombre.')
            elif titulo.lower() in vistos:
                errores.append(f'"{nombre}" está repetido en la selección.')
            vistos.add(titulo.lower())
        if errores:
            raise forms.ValidationError(errores)
        return archivos

    def informes_repetidos(self, obra):
        """Títulos que la obra ya tiene (se cargan igual, pero se avisa)."""
        titulos = [titulo_desde_archivo(a.name) for a in self.cleaned_data['archivos']]
        existentes = set(
            obra.informes.filter(titulo__in=titulos).values_list('titulo', flat=True))
        return [t for t in titulos if t in existentes]


class ConstructoraForm(forms.ModelForm):
    # Prefijo del código interno según la ciudad (fuente única: users/ciudades.py).
    # El código se arma como PREFIJO + número.
    CIUDAD_PREFIJOS = Constructora.CIUDADES
    CIUDAD_CHOICES = [('', '-- Seleccionar --')] + [(c, c) for c in CIUDAD_PREFIJOS]

    ciudad = forms.ChoiceField(
        choices=CIUDAD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_ciudad'}),
    )
    numero_codigo = forms.CharField(
        label='Número de código',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 23',
            'min': '1',
        }),
    )

    class Meta:
        model = Constructora
        fields = ['nombre', 'ciudad', 'nit']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Al editar, normalizar la ciudad legacy al valor del selector y
        # separar el número del prefijo para pre-llenar el campo.
        if self.instance and self.instance.pk:
            ciudad_actual = _sin_acentos(self.instance.ciudad)
            canonica = next(
                (c for c in self.CIUDAD_PREFIJOS if _sin_acentos(c) == ciudad_actual),
                '',
            )
            if canonica:
                self.initial['ciudad'] = canonica
            codigo = self.instance.codigo or ''
            prefijo = self.CIUDAD_PREFIJOS.get(canonica, '')
            if prefijo and codigo.upper().startswith(prefijo):
                self.fields['numero_codigo'].initial = codigo[len(prefijo):].strip()
            else:
                self.fields['numero_codigo'].initial = codigo

    def clean_numero_codigo(self):
        numero = (self.cleaned_data.get('numero_codigo') or '').strip()
        if not numero.isdigit():
            raise forms.ValidationError('Ingrese solo el número (ej: 23), sin el prefijo.')
        return numero

    def clean(self):
        cleaned = super().clean()
        ciudad = cleaned.get('ciudad')
        numero = cleaned.get('numero_codigo')
        if ciudad and numero:
            prefijo = self.CIUDAD_PREFIJOS.get(ciudad)
            if not prefijo:
                self.add_error('ciudad', 'No hay prefijo de código definido para esta ciudad.')
                return cleaned
            codigo = f"{prefijo}{numero}"
            duplicados = Constructora.objects.filter(codigo__iexact=codigo)
            if self.instance and self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error('numero_codigo', f'Ya existe una empresa con el código {codigo}.')
            else:
                self._codigo_generado = codigo
        return cleaned

    def save(self, commit=True):
        empresa = super().save(commit=False)
        empresa.codigo = self._codigo_generado
        if commit:
            empresa.save()
        return empresa

class ObraForm(forms.ModelForm):
    # El código de obra se arma como CODIGO_EMPRESA + '-' + número (ej: BUC52-1).
    numero_codigo = forms.CharField(
        label='Número de obra',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 1',
            'min': '1',
        }),
    )

    class Meta:
        model = Obra
        fields = ['nombre']  # codigo_obra se construye desde el prefijo; constructora no se edita
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.constructora = kwargs.pop('constructora', None)
        super().__init__(*args, **kwargs)
        # Al editar, la constructora viene de la instancia.
        if self.constructora is None and self.instance and self.instance.pk:
            self.constructora = self.instance.constructora
        # Pre-llenar el número separándolo del prefijo.
        if self.instance and self.instance.pk and self.instance.codigo_obra:
            codigo = self.instance.codigo_obra
            if self.prefijo_codigo and codigo.startswith(self.prefijo_codigo):
                self.fields['numero_codigo'].initial = codigo[len(self.prefijo_codigo):]
            else:
                self.fields['numero_codigo'].initial = codigo

    @property
    def prefijo_codigo(self):
        return f"{self.constructora.codigo}-" if self.constructora else ''

    def clean_numero_codigo(self):
        numero = (self.cleaned_data.get('numero_codigo') or '').strip()
        if not numero.isdigit():
            raise forms.ValidationError('Ingrese solo el número de obra (ej: 1), sin el prefijo.')
        return numero

    def clean(self):
        cleaned = super().clean()
        numero = cleaned.get('numero_codigo')
        if numero and self.constructora:
            codigo = f"{self.constructora.codigo}-{numero}"
            duplicados = Obra.objects.filter(
                constructora=self.constructora, codigo_obra__iexact=codigo
            )
            if self.instance and self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error(
                    'numero_codigo',
                    f'Ya existe una obra con el código {codigo} en esta empresa.',
                )
            else:
                self._codigo_generado = codigo
        return cleaned

    def save(self, commit=True):
        obra = super().save(commit=False)
        obra.codigo_obra = self._codigo_generado
        if commit:
            obra.save()
        return obra