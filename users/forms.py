from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import UsuarioBase, ClienteExterno, Constructora
from core.models import Obra


class LoginForm(AuthenticationForm):
    """Formulario de Login personalizado con estilos Bootstrap"""
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control form-control-lg',
        'placeholder': 'Usuario o Correo',
        'autofocus': True
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control form-control-lg',
        'placeholder': 'Contraseña'
    }))


class ClienteExternoForm(forms.ModelForm):
    """
    Formulario para crear/editar ClienteExterno.
    Incluye campos del UsuarioBase (username, email, password, nombre, apellido)
    y campos del ClienteExterno (empresa, rol, cargo, telefono).
    """
    # Campos del UsuarioBase
    username = forms.CharField(
        label='Usuario',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'nombre.apellido'
        }),
        help_text='Nombre de usuario para iniciar sesión'
    )
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'correo@empresa.com'
        })
    )
    first_name = forms.CharField(
        label='Nombre',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre'
        })
    )
    last_name = forms.CharField(
        label='Apellido',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Apellido'
        })
    )
    password = forms.CharField(
        label='Contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Dejar vacío para mantener la actual'
        }),
        help_text='Mínimo 8 caracteres. Dejar vacío para no cambiar.'
    )
    password_confirm = forms.CharField(
        label='Confirmar contraseña',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repetir contraseña'
        })
    )

    # Obras asignadas (para residentes y remitentes)
    obras_asignadas = forms.ModelMultipleChoiceField(
        queryset=Obra.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        }),
        label='Obras asignadas',
        help_text='Selecciona las obras a las que tendra acceso (aplica para Residente y Remitente)'
    )

    class Meta:
        model = ClienteExterno
        fields = ['empresa', 'rol', 'cargo', 'telefono']
        widgets = {
            'empresa': forms.Select(attrs={'class': 'form-select'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
            'cargo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Ingeniero Residente'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 3001234567'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.instance_user = kwargs.pop('instance_user', None)
        super().__init__(*args, **kwargs)

        # Si es edición, prellenar campos del usuario
        if self.instance and self.instance.pk:
            user = self.instance.user
            self.fields['username'].initial = user.username
            self.fields['email'].initial = user.email
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            # Obras asignadas actuales
            self.fields['obras_asignadas'].initial = self.instance.obras_asignadas.all()

        # Filtrar obras según la empresa seleccionada
        if self.instance and self.instance.pk and self.instance.empresa:
            self.fields['obras_asignadas'].queryset = Obra.objects.filter(
                constructora=self.instance.empresa
            ).order_by('nombre')
        elif 'empresa' in self.data:
            try:
                empresa_id = int(self.data.get('empresa'))
                self.fields['obras_asignadas'].queryset = Obra.objects.filter(
                    constructora_id=empresa_id
                ).order_by('nombre')
            except (ValueError, TypeError):
                pass

    def clean_username(self):
        username = self.cleaned_data.get('username')
        # Verificar que no exista otro usuario con ese username
        qs = UsuarioBase.objects.filter(username=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise ValidationError('Este nombre de usuario ya está en uso.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Verificar que no exista otro usuario con ese email
        qs = UsuarioBase.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise ValidationError('Este correo electrónico ya está registrado.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        # Si es creación, la contraseña es obligatoria
        if not self.instance.pk and not password:
            self.add_error('password', 'La contraseña es obligatoria para nuevos usuarios.')

        # Validar que las contraseñas coincidan
        if password and password != password_confirm:
            self.add_error('password_confirm', 'Las contraseñas no coinciden.')

        # Validar longitud mínima
        if password and len(password) < 8:
            self.add_error('password', 'La contraseña debe tener al menos 8 caracteres.')

        return cleaned_data

    def save(self, commit=True):
        # Crear o actualizar el UsuarioBase
        if self.instance.pk:
            # Edición
            user = self.instance.user
        else:
            # Creación
            user = UsuarioBase()
            user.es_cliente = True

        user.username = self.cleaned_data['username']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']

        # Actualizar contraseña solo si se proporcionó
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)

        if commit:
            user.save()

        # Guardar el ClienteExterno
        cliente = super().save(commit=False)
        cliente.user = user

        if commit:
            cliente.save()
            # Actualizar obras asignadas (para residentes)
            obras = self.cleaned_data.get('obras_asignadas', [])
            # Limpiar asignaciones anteriores y agregar las nuevas
            for obra in Obra.objects.filter(residentes_asignados=cliente):
                obra.residentes_asignados.remove(cliente)
            for obra in obras:
                obra.residentes_asignados.add(cliente)

        return cliente