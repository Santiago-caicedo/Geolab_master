from django import forms
from django.contrib.auth.password_validation import validate_password

from users.models import UsuarioBase
from .models import Carpeta, Documento


class MultiFileInput(forms.FileInput):
    """FileInput que acepta múltiples archivos."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """
    FileField que valida una lista de archivos (receta de la doc de Django).
    Con el widget múltiple, value_from_datadict entrega una lista y el
    FileField estándar la rechaza ("No se ha enviado ningún fichero").
    """
    def clean(self, data, initial=None):
        limpiar_uno = super().clean
        if isinstance(data, (list, tuple)):
            return [limpiar_uno(archivo, initial) for archivo in data]
        return limpiar_uno(data, initial)


class SubirDocumentoForm(forms.Form):
    """Form para subir uno o múltiples archivos a una carpeta."""
    archivos = MultipleFileField(
        widget=MultiFileInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.txt,.csv'
        }),
        label='Archivos',
        required=True,
    )


class CrearUsuarioCalidadForm(forms.Form):
    """
    Form del coordinador para crear Usuarios de Calidad (rol confinado al SGC
    con permisos por carpeta). La vista crea usuario + perfil en transaccion.
    """
    username = forms.CharField(
        label='Usuario', max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'ej: maria.lopez', 'autofocus': True,
        }),
    )
    nombre = forms.CharField(
        label='Nombres', max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    apellido = forms.CharField(
        label='Apellidos', max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        label='Correo electrónico', required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if UsuarioBase.objects.filter(username=username).exists():
            raise forms.ValidationError('Ya existe un usuario con ese nombre.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', 'Las contraseñas no coinciden.')
            else:
                usuario_tentativo = UsuarioBase(
                    username=cleaned.get('username', ''),
                    email=cleaned.get('email', ''),
                )
                try:
                    validate_password(p1, usuario_tentativo)
                except forms.ValidationError as e:
                    self.add_error('password1', e)
        return cleaned


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
