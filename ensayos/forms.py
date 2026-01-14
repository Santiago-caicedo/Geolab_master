from django import forms
from .models import ResultadoMuestra


class ResultadoMuestraForm(forms.ModelForm):
    """
    Formulario para editar los resultados de una muestra.
    El técnico llena las mediciones y el sistema calcula el resto.
    """

    class Meta:
        model = ResultadoMuestra
        fields = [
            'diametro_d1', 'diametro_d2', 'diametro_d3',
            'longitud_l1', 'longitud_l2', 'longitud_l3',
            'peso_gramos',
            'carga_maxima_kn',
            'forma_falla',
            'fecha_ensayo',
            'observaciones',
            'estado',
        ]
        widgets = {
            'diametro_d1': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'D1',
            }),
            'diametro_d2': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'D2',
            }),
            'diametro_d3': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'D3',
            }),
            'longitud_l1': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'L1',
            }),
            'longitud_l2': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'L2',
            }),
            'longitud_l3': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'L3',
            }),
            'peso_gramos': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'Peso (g)',
            }),
            'carga_maxima_kn': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'step': '0.01',
                'placeholder': 'Carga (KN)',
            }),
            'forma_falla': forms.Select(attrs={
                'class': 'form-select form-select-sm',
            }),
            'fecha_ensayo': forms.DateInput(attrs={
                'class': 'form-control form-control-sm',
                'type': 'date',
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control form-control-sm',
                'rows': 2,
                'placeholder': 'Observaciones...',
            }),
            'estado': forms.Select(attrs={
                'class': 'form-select form-select-sm',
            }),
        }


class ResultadoMuestraInlineForm(forms.ModelForm):
    """
    Formulario compacto para edición inline (en tabla).
    Solo los campos de medición más importantes.
    """

    class Meta:
        model = ResultadoMuestra
        fields = [
            'diametro_d1', 'diametro_d2', 'diametro_d3',
            'longitud_l1', 'longitud_l2', 'longitud_l3',
            'peso_gramos',
            'carga_maxima_kn',
            'forma_falla',
        ]
        widgets = {
            'diametro_d1': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'diametro_d2': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'diametro_d3': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'longitud_l1': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'longitud_l2': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'longitud_l3': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 70px;',
            }),
            'peso_gramos': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 80px;',
            }),
            'carga_maxima_kn': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'step': '0.01',
                'style': 'width: 80px;',
            }),
            'forma_falla': forms.Select(attrs={
                'class': 'form-select form-select-sm',
                'style': 'width: 120px;',
            }),
        }
