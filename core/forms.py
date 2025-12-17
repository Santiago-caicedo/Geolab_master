from django import forms
from users.models import Constructora
from .models import Obra

class ConstructoraForm(forms.ModelForm):
    class Meta:
        model = Constructora
        fields = ['nombre', 'codigo', 'nit', 'ciudad']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ObraForm(forms.ModelForm):
    class Meta:
        model = Obra
        fields = ['nombre', 'codigo_obra'] # No dejamos editar la constructora padre por seguridad
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo_obra': forms.TextInput(attrs={'class': 'form-control'}),
        }