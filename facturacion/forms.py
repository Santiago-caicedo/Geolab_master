from django import forms
from django.forms import modelformset_factory

from .models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio,
)
from users.models import Constructora
from core.models import Obra


class CategoriaServicioForm(forms.ModelForm):
    """La ciudad no se edita: viene de la ciudad activa del módulo."""
    class Meta:
        model = CategoriaServicio
        fields = ['codigo', 'nombre']
        widgets = {
            'codigo': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: 1'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: CONCRETOS'
            }),
        }

    def __init__(self, *args, ciudad=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciudad = ciudad or self.instance.ciudad
        self.instance.ciudad = self.ciudad

    def clean_codigo(self):
        codigo = (self.cleaned_data.get('codigo') or '').strip()
        repetida = CategoriaServicio.objects.filter(
            ciudad__iexact=self.ciudad, codigo=codigo
        ).exclude(pk=self.instance.pk).exists()
        if repetida:
            raise forms.ValidationError(f'Ya existe la categoría {codigo} en {self.ciudad}.')
        return codigo


class TipoServicioForm(forms.ModelForm):
    """La ciudad no se edita: viene de la ciudad activa (y de la categoría)."""
    class Meta:
        model = TipoServicio
        fields = ['categoria', 'codigo', 'nombre', 'norma']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'codigo': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: I-1'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Descripción del servicio'
            }),
            'norma': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Norma técnica (opcional)'
            }),
        }

    def __init__(self, *args, ciudad=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciudad = ciudad or self.instance.ciudad
        self.fields['categoria'].queryset = CategoriaServicio.objects.filter(
            ciudad__iexact=self.ciudad
        )

    def _repetido(self, campo, valor):
        return TipoServicio.objects.filter(
            ciudad__iexact=self.ciudad, **{campo: valor}
        ).exclude(pk=self.instance.pk).exists()

    def clean_codigo(self):
        codigo = (self.cleaned_data.get('codigo') or '').strip()
        if self._repetido('codigo', codigo):
            raise forms.ValidationError(f'Ya existe el servicio {codigo} en {self.ciudad}.')
        return codigo

    def clean_nombre(self):
        nombre = (self.cleaned_data.get('nombre') or '').strip()
        if self._repetido('nombre__iexact', nombre):
            raise forms.ValidationError(f'Ya existe un servicio con ese nombre en {self.ciudad}.')
        return nombre


class PrecioServicioForm(forms.ModelForm):
    class Meta:
        model = PrecioServicio
        fields = ['precio']
        widgets = {
            'precio': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-end',
                'step': '0.01', 'placeholder': '0.00',
                'style': 'width: 130px;',
            }),
        }


PrecioServicioFormSet = modelformset_factory(
    PrecioServicio,
    form=PrecioServicioForm,
    extra=0,
)


class ImpuestoForm(forms.ModelForm):
    class Meta:
        model = Impuesto
        fields = ['nombre', 'porcentaje', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'porcentaje': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01'
            }),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RegistroServicioForm(forms.ModelForm):
    """Formulario para editar un registro de servicio existente (no facturado)."""
    class Meta:
        model = RegistroServicio
        fields = [
            'obra', 'tipo_servicio', 'fecha_realizacion',
            'numero_informe', 'cantidad',
        ]
        widgets = {
            'obra': forms.Select(attrs={'class': 'form-select'}),
            'tipo_servicio': forms.Select(attrs={'class': 'form-select'}),
            'fecha_realizacion': forms.DateInput(attrs={
                'class': 'form-control', 'type': 'date'
            }),
            'numero_informe': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Número de informe'
            }),
            'cantidad': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '1'
            }),
        }

    def __init__(self, *args, ciudad=None, **kwargs):
        super().__init__(*args, **kwargs)
        obras = Obra.objects.select_related('constructora')
        if ciudad:
            obras = obras.filter(constructora__ciudad__iexact=ciudad)
            self.fields['tipo_servicio'].queryset = TipoServicio.objects.filter(
                ciudad__iexact=ciudad
            ).select_related('categoria')
        self.fields['obra'].queryset = obras.order_by('constructora__nombre', 'nombre')
        self.fields['obra'].label_from_instance = (
            lambda obj: f"{obj.constructora.nombre} → {obj.nombre}"
        )


class FiltroHistoricoForm(forms.Form):
    """Filtros para el histórico de registros."""
    constructora = forms.ModelChoiceField(
        queryset=Constructora.objects.all().order_by('nombre'),
        required=False,
        empty_label='-- Todas las constructoras --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    obra = forms.ModelChoiceField(
        queryset=Obra.objects.none(),
        required=False,
        empty_label='-- Todas las obras --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tipo_servicio = forms.ModelChoiceField(
        queryset=TipoServicio.objects.select_related('categoria'),
        required=False,
        empty_label='-- Todos los servicios --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    fecha_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    fecha_fin = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    def __init__(self, *args, ciudad=None, **kwargs):
        super().__init__(*args, **kwargs)
        _acotar_a_ciudad(self, ciudad)
        # Si viene constructora, filtrar obras
        data = kwargs.get('data') if 'data' in kwargs else (args[0] if args else None)
        constructora_id = data.get('constructora') if data else None
        if constructora_id:
            try:
                self.fields['obra'].queryset = Obra.objects.filter(
                    constructora_id=int(constructora_id),
                    constructora__in=self.fields['constructora'].queryset,
                ).order_by('nombre')
            except (ValueError, TypeError):
                pass


def _acotar_a_ciudad(form, ciudad):
    """Limita los selects de constructora (y servicio) a la ciudad activa."""
    if ciudad:
        form.fields['constructora'].queryset = Constructora.objects.filter(
            ciudad__iexact=ciudad
        ).order_by('nombre')
        if 'tipo_servicio' in form.fields:
            form.fields['tipo_servicio'].queryset = TipoServicio.objects.filter(
                ciudad__iexact=ciudad
            ).select_related('categoria')


class GenerarFacturaForm(forms.Form):
    """Formulario para generar factura: seleccionar obra y periodo."""
    constructora = forms.ModelChoiceField(
        queryset=Constructora.objects.all().order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Constructora'
    )
    obra = forms.ModelChoiceField(
        queryset=Obra.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Obra'
    )
    fecha_inicio = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Fecha inicio periodo'
    )
    fecha_fin = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Fecha fin periodo'
    )

    def __init__(self, *args, ciudad=None, **kwargs):
        super().__init__(*args, **kwargs)
        _acotar_a_ciudad(self, ciudad)
        if args and args[0]:
            constructora_id = args[0].get('constructora')
            if constructora_id:
                try:
                    self.fields['obra'].queryset = Obra.objects.filter(
                        constructora_id=int(constructora_id),
                        constructora__in=self.fields['constructora'].queryset,
                    ).order_by('nombre')
                except (ValueError, TypeError):
                    pass

    def clean(self):
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get('fecha_inicio')
        fecha_fin = cleaned_data.get('fecha_fin')
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise forms.ValidationError(
                'La fecha de inicio no puede ser mayor a la fecha fin.'
            )
        return cleaned_data
