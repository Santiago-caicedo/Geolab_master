from django import forms
from .models import Carpeta, Documento


class MultiFileInput(forms.FileInput):
    """FileInput que acepta múltiples archivos."""
    allow_multiple_selected = True


class SubirDocumentoForm(forms.Form):
    """Form para subir uno o múltiples archivos a una carpeta."""
    archivos = forms.FileField(
        widget=MultiFileInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.txt,.csv'
        }),
        label='Archivos',
        required=True,
    )


class CrearCarpetaForm(forms.ModelForm):
    """Form para crear una nueva subcarpeta."""
    class Meta:
        model = Carpeta
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de la carpeta',
                'autofocus': True,
            }),
        }
