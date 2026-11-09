"""Formulario del superusuario para crear y editar Usuarios de Facturación."""

from django import forms
from django.contrib.auth.password_validation import validate_password

from users.models import UsuarioBase

from . import permisos, sede


class UsuarioFacturacionForm(forms.Form):
    """
    Datos de la cuenta + ciudades + secciones. Al crear, la contraseña es
    obligatoria; al editar, en blanco deja la que tenía.
    """
    username = forms.CharField(label='Usuario', max_length=150)
    nombre = forms.CharField(label='Nombres', max_length=150)
    apellido = forms.CharField(label='Apellidos', max_length=150, required=False)
    email = forms.EmailField(label='Correo electrónico', required=False)
    password1 = forms.CharField(label='Contraseña', required=False, strip=False,
                                widget=forms.PasswordInput(render_value=False))
    password2 = forms.CharField(label='Repetir contraseña', required=False, strip=False,
                                widget=forms.PasswordInput(render_value=False))
    ciudades = forms.MultipleChoiceField(label='Ciudades', widget=forms.CheckboxSelectMultiple,
                                         error_messages={'required': 'Elija al menos una ciudad.'})
    secciones = forms.MultipleChoiceField(label='Secciones', widget=forms.CheckboxSelectMultiple,
                                          choices=[(c, n) for c, n, _g, _d in permisos.SECCIONES],
                                          error_messages={'required': 'Elija al menos una sección.'})

    def __init__(self, *args, usuario=None, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        disponibles = sede.ciudades_disponibles()
        # Una ciudad guardada que ya no tiene constructoras sigue en la lista, para poder quitarla
        guardadas = []
        if usuario is not None:
            acceso = permisos.acceso_de(usuario)
            guardadas = [c for c in (acceso.ciudades if acceso else []) if c not in disponibles]
        self.fields['ciudades'].choices = [(c, c) for c in disponibles + guardadas]
        if usuario is None:
            self.fields['password1'].required = True
            self.fields['password2'].required = True

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        otros = UsuarioBase.objects.filter(username__iexact=username)
        if self.usuario is not None:
            otros = otros.exclude(pk=self.usuario.pk)
        if otros.exists():
            raise forms.ValidationError('Ya existe un usuario con ese nombre.')
        return username

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get('password1'), datos.get('password2')
        if p1 or p2:
            if p1 != p2:
                self.add_error('password2', 'Las contraseñas no coinciden.')
            else:
                tentativo = self.usuario or UsuarioBase()
                tentativo.username = datos.get('username') or tentativo.username
                tentativo.email = datos.get('email') or ''
                try:
                    validate_password(p1, tentativo)
                except forms.ValidationError as e:
                    self.add_error('password1', e)
        return datos

    def secciones_ordenadas(self):
        elegidas = set(self.cleaned_data['secciones'])
        return [c for c in permisos.CLAVES if c in elegidas]
