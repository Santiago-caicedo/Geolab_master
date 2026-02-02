from django import forms
from django.forms import inlineformset_factory
from .models import RemisionMuestras, Muestra


class CrearRemisionForm(forms.ModelForm):
    """
    Formulario para que Staff Geolab cree una nueva remisión.
    Solo campos básicos - la obra viene pre-seleccionada.
    El número de remisión (orden_trabajo) se genera automáticamente.
    """
    class Meta:
        model = RemisionMuestras
        fields = ['email_destinatario']
        widgets = {
            'email_destinatario': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@ejemplo.com',
                'required': True,
            }),
        }
        labels = {
            'email_destinatario': 'Email del destinatario en obra',
        }


class ResponderRemisionForm(forms.ModelForm):
    """
    Formulario para que el cliente llene la parte de custodia y manifiesto.
    """
    class Meta:
        model = RemisionMuestras
        fields = [
            # Cadena custodia cliente
            'cliente_fecha',
            'cliente_estado',
            'cliente_firma_nombre',
            'cliente_observaciones',
            # Manifiesto
            'firmante_nombre',
            'firmante_cargo',
            'firmante_email',
            'firmante_telefono',
            'acepta_veracidad',
        ]
        widgets = {
            'cliente_fecha': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'cliente_estado': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Bueno',
            }),
            'cliente_firma_nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de quien entrega',
            }),
            'cliente_observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Observaciones adicionales...',
            }),
            'firmante_nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre completo',
                'required': True,
            }),
            'firmante_cargo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Ingeniero Residente',
                'required': True,
            }),
            'firmante_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@ejemplo.com',
                'required': True,
            }),
            'firmante_telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Teléfono de contacto',
            }),
            'acepta_veracidad': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'required': True,
            }),
        }

    def clean_acepta_veracidad(self):
        acepta = self.cleaned_data.get('acepta_veracidad')
        if not acepta:
            raise forms.ValidationError('Debe aceptar la declaración de veracidad para continuar.')
        return acepta


class MuestraForm(forms.ModelForm):
    """
    Formulario para cada muestra individual.
    """
    class Meta:
        model = Muestra
        fields = [
            'numero_muestra',
            'cantidad',
            'tipo_muestra',
            'diametro_longitud',
            'ensayo_flexion',
            'ensayo_compresion',
            'ensayo_absorcion',
            'ensayo_otros',
            'localizacion',
            'fecha_toma',
            'edad_ensayo_dias',
            'fc_resistencia',
        ]
        widgets = {
            'numero_muestra': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'style': 'width: 70px;',
                'min': '1',
            }),
            'cantidad': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'style': 'width: 60px;',
                'min': '1',
            }),
            'tipo_muestra': forms.Select(attrs={
                'class': 'form-select form-select-sm',
            }),
            'diametro_longitud': forms.TextInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'style': 'width: 70px;',
                'placeholder': 'cm',
            }),
            'ensayo_flexion': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'ensayo_compresion': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'ensayo_absorcion': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'ensayo_otros': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Especificar...',
                'style': 'width: 100px;',
            }),
            'localizacion': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Ej: T4 - Muros P1',
            }),
            'fecha_toma': forms.DateInput(attrs={
                'class': 'form-control form-control-sm',
                'type': 'date',
            }),
            'edad_ensayo_dias': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'style': 'width: 70px;',
                'placeholder': 'dias',
            }),
            'fc_resistencia': forms.TextInput(attrs={
                'class': 'form-control form-control-sm text-center',
                'style': 'width: 90px;',
                'placeholder': 'Psi/MPa',
            }),
        }


# Formset para manejar múltiples muestras
MuestraFormSet = inlineformset_factory(
    RemisionMuestras,
    Muestra,
    form=MuestraForm,
    extra=1,        # 1 fila inicial vacía
    can_delete=True,
    min_num=0,      # Sin mínimo (la validación se hace en la vista)
    validate_min=False,
)


class CrearRemisionClienteForm(forms.ModelForm):
    """
    Formulario para que el Remitente cree una remision con cadena de custodia.
    Los campos de firma se auto-completan desde el usuario logueado.
    """
    class Meta:
        model = RemisionMuestras
        fields = [
            'cliente_fecha',
            'cliente_estado',
            'cliente_firma_nombre',
            'cliente_observaciones',
        ]
        widgets = {
            'cliente_fecha': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'cliente_estado': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Bueno',
            }),
            'cliente_firma_nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de quien entrega',
            }),
            'cliente_observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Observaciones adicionales...',
            }),
        }


class RecepcionLabForm(forms.ModelForm):
    """
    Formulario para que Geolab complete la recepción en laboratorio.
    """
    class Meta:
        model = RemisionMuestras
        fields = [
            'lab_fecha',
            'lab_cantidad',
            'lab_estado',
            'lab_firma_nombre',
            'lab_observaciones',
            'revisado_por',
            'programado',
            'fecha_revision',
            'firma_revision',
        ]
        widgets = {
            'lab_fecha': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'lab_cantidad': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
            'lab_estado': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Estado de las muestras recibidas',
            }),
            'lab_firma_nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de quien recibe',
            }),
            'lab_observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
            }),
            'revisado_por': forms.TextInput(attrs={
                'class': 'form-control',
            }),
            'programado': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'fecha_revision': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'firma_revision': forms.TextInput(attrs={
                'class': 'form-control',
            }),
        }
