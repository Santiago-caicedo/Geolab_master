import unicodedata

from django import forms
from users.models import Constructora
from .models import Obra, Informe


def _sin_acentos(texto):
    """Normaliza para comparar ciudades sin distinguir tildes ni mayúsculas."""
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto or '')
        if not unicodedata.combining(c)
    ).strip().lower()


class InformeForm(forms.ModelForm):
    """Formulario para cargar nuevos informes técnicos"""

    class Meta:
        model = Informe
        fields = ['titulo', 'obra', 'archivo']
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Se completara automaticamente con el nombre del archivo...',
                'readonly': 'readonly'
            }),
            'obra': forms.Select(attrs={
                'class': 'form-select'
            }),
            'archivo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'application/pdf'
            }),
        }
        labels = {
            'titulo': 'Título del Informe',
            'obra': 'Obra destino',
            'archivo': 'Archivo PDF',
        }

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

    def clean_archivo(self):
        """Validar que el archivo sea un PDF"""
        archivo = self.cleaned_data.get('archivo')
        if archivo:
            # Verificar extensión
            if not archivo.name.lower().endswith('.pdf'):
                raise forms.ValidationError('Solo se permiten archivos PDF.')

            # Verificar content type
            content_type = getattr(archivo, 'content_type', '')
            if content_type and content_type != 'application/pdf':
                raise forms.ValidationError('El archivo debe ser un PDF válido.')

        return archivo


class ConstructoraForm(forms.ModelForm):
    # Prefijo del código interno según la ciudad. El código se arma como PREFIJO + número.
    CIUDAD_PREFIJOS = {
        'Bucaramanga': 'BUC',
        'Bogotá': 'BOG',
        'Ibagué': 'IBA',
    }
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