from django import forms
from django.forms import modelformset_factory

from .models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio,
)
from users.models import Constructora
from core.models import Obra


class CategoriaServicioForm(forms.ModelForm):
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


class TipoServicioForm(forms.ModelForm):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.select_related(
            'constructora'
        ).order_by('constructora__nombre', 'nombre')
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
        queryset=TipoServicio.objects.all().order_by('codigo'),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si viene constructora, filtrar obras
        if 'data' in kwargs and kwargs['data']:
            constructora_id = kwargs['data'].get('constructora')
            if constructora_id:
                try:
                    self.fields['obra'].queryset = Obra.objects.filter(
                        constructora_id=int(constructora_id)
                    ).order_by('nombre')
                except (ValueError, TypeError):
                    pass
        elif args and args[0]:
            constructora_id = args[0].get('constructora')
            if constructora_id:
                try:
                    self.fields['obra'].queryset = Obra.objects.filter(
                        constructora_id=int(constructora_id)
                    ).order_by('nombre')
                except (ValueError, TypeError):
                    pass


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if args and args[0]:
            constructora_id = args[0].get('constructora')
            if constructora_id:
                try:
                    self.fields['obra'].queryset = Obra.objects.filter(
                        constructora_id=int(constructora_id)
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
