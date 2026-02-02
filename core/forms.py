from django import forms
from users.models import Constructora
from .models import Obra, Informe


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