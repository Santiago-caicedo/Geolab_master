import unicodedata
from datetime import datetime, time

import re

from django import forms
from django.utils import timezone
from users.models import Constructora
from .models import Obra


def _sin_acentos(texto):
    """Normaliza para comparar ciudades sin distinguir tildes ni mayúsculas."""
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto or '')
        if not unicodedata.combining(c)
    ).strip().lower()


MAX_INFORMES_POR_CARGA = 100   # = DATA_UPLOAD_MAX_NUMBER_FILES por defecto de Django
TIPOS_PDF = ('application/pdf', 'application/x-pdf', 'application/acrobat', '')


def titulo_desde_archivo(nombre):
    """'INF 0340-2026 VIGAS.pdf' -> 'INF 0340-2026 VIGAS' (el título del informe es el nombre del archivo)."""
    base = nombre.replace('\\', '/').rsplit('/', 1)[-1]
    if base.lower().endswith('.pdf'):
        base = base[:-4]
    return base.strip()[:255]


class VariosPdfInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class VariosPdfField(forms.FileField):
    """Campo de archivos múltiples: devuelve una lista de archivos subidos."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', VariosPdfInput(attrs={
            'class': 'form-control',
            'accept': '.pdf,application/pdf',
            'multiple': True,
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            return [super(VariosPdfField, self).clean(d, initial) for d in data if d]
        return [super().clean(data, initial)] if data else super().clean(data, initial)


class InformeForm(forms.Form):
    """Carga de uno o varios informes técnicos (PDF) a una obra.
    Cada archivo es un Informe; su título es el nombre del archivo."""

    obra = forms.ModelChoiceField(
        queryset=Obra.objects.none(), label='Obra destino',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    # Fecha que se muestra en el portal (Informe.fecha_creacion). Por defecto hoy,
    # editable para cargar informes de fechas anteriores. Es la misma para todos.
    fecha = forms.DateField(
        label='Fecha del informe',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
    )
    archivos = VariosPdfField(label='Archivos PDF')

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

        hoy = timezone.localdate()
        self.fields['fecha'].initial = hoy
        self.fields['fecha'].widget.attrs['max'] = hoy.isoformat()

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha > timezone.localdate():
            raise forms.ValidationError('La fecha del informe no puede ser futura.')
        return fecha

    def fecha_creacion(self):
        """Fecha elegida como datetime: hoy = hora actual; otro día = mediodía de ese día."""
        fecha = self.cleaned_data['fecha']
        if fecha == timezone.localdate():
            return timezone.now()
        return timezone.make_aware(datetime.combine(fecha, time(12, 0)))

    def clean_archivos(self):
        """Todos deben ser PDF de verdad (extensión, tipo y contenido); si uno falla no se carga ninguno."""
        archivos = self.cleaned_data.get('archivos') or []
        if len(archivos) > MAX_INFORMES_POR_CARGA:
            raise forms.ValidationError(
                f'Máximo {MAX_INFORMES_POR_CARGA} informes por carga (elegiste {len(archivos)}).')
        errores, vistos = [], set()
        for archivo in archivos:
            nombre = archivo.name
            if not nombre.lower().endswith('.pdf'):
                errores.append(f'"{nombre}" no es un PDF.')
                continue
            if getattr(archivo, 'content_type', '') not in TIPOS_PDF:
                errores.append(f'"{nombre}" no es un PDF válido.')
                continue
            archivo.seek(0)
            inicio = archivo.read(1024)
            archivo.seek(0)
            if b'%PDF' not in inicio:
                errores.append(f'"{nombre}" no es un PDF válido (el contenido no es PDF).')
                continue
            titulo = titulo_desde_archivo(nombre)
            if not titulo:
                errores.append(f'"{nombre}" no tiene nombre.')
            elif titulo.lower() in vistos:
                errores.append(f'"{nombre}" está repetido en la selección.')
            vistos.add(titulo.lower())
        if errores:
            raise forms.ValidationError(errores)
        return archivos

    def informes_repetidos(self, obra):
        """Títulos que la obra ya tiene (se cargan igual, pero se avisa)."""
        titulos = [titulo_desde_archivo(a.name) for a in self.cleaned_data['archivos']]
        existentes = set(
            obra.informes.filter(titulo__in=titulos).values_list('titulo', flat=True))
        return [t for t in titulos if t in existentes]


class ConstructoraForm(forms.ModelForm):
    # Prefijo del código interno según la ciudad (fuente única: users/ciudades.py).
    # El código se arma como PREFIJO + número.
    CIUDAD_PREFIJOS = Constructora.CIUDADES
    CIUDAD_CHOICES = [('', '-- Seleccionar --')] + [(c, c) for c in CIUDAD_PREFIJOS]

    ciudad = forms.ChoiceField(
        choices=CIUDAD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_ciudad'}),
    )
    # Texto, no <input type="number">: los códigos de clientes varios (BUC0-12) y los sufijos de
    # código reutilizado (BOG1B) no son enteros y un campo numérico los mostraba vacío al editar.
    numero_codigo = forms.CharField(
        label='Número de código',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 23',
            'inputmode': 'numeric',
            'autocomplete': 'off',
        }),
    )
    _NUMERO_EMPRESA = re.compile(r'^\d+(-\d+)?[A-Z]?$')   # 23 · 0-12 (cliente varios) · 1B (código reutilizado)

    class Meta:
        model = Constructora
        fields = ['nombre', 'ciudad', 'nit']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Al editar, normalizar la ciudad legacy al valor del selector y
        # separar el número del prefijo para pre-llenar el campo.
        if self.instance and self.instance.pk:
            ciudad_actual = _sin_acentos(self.instance.ciudad)
            canonica = next(
                (c for c in self.CIUDAD_PREFIJOS if _sin_acentos(c) == ciudad_actual),
                '',
            )
            if canonica:
                self.initial['ciudad'] = canonica
            codigo = self.instance.codigo or ''
            prefijo = self.CIUDAD_PREFIJOS.get(canonica, '')
            if prefijo and codigo.upper().startswith(prefijo):
                self.fields['numero_codigo'].initial = codigo[len(prefijo):].strip()
            else:
                self.fields['numero_codigo'].initial = codigo

    def clean_numero_codigo(self):
        numero = (self.cleaned_data.get('numero_codigo') or '').strip().upper().replace(' ', '')
        if not self._NUMERO_EMPRESA.match(numero):
            raise forms.ValidationError(
                'Ingrese solo el número, sin el prefijo de ciudad: 23, o 0-12 para clientes varios.'
            )
        return numero

    def clean_ciudad(self):
        ciudad = self.cleaned_data.get('ciudad')
        # La sede de facturación sale de esta ciudad: cambiarla movería facturas y registros
        # a otra sede, cuyo catálogo de servicios es distinto.
        if self.instance.pk and ciudad and _sin_acentos(ciudad) != _sin_acentos(self.instance.ciudad or ''):
            from facturacion.models import RegistroServicio
            facturas = self.instance.facturas.count()
            registros = RegistroServicio.objects.filter(obra__constructora=self.instance).count()
            if facturas or registros:
                raise forms.ValidationError(
                    f'Esta empresa tiene {facturas} factura(s) y {registros} servicio(s) registrado(s) en '
                    f'{self.instance.ciudad}. Cambiar la ciudad los pasaría a otra sede con otro catálogo; '
                    'si de verdad cambió de sede, hay que hacerlo con cuidado desde la base de datos.'
                )
        return ciudad

    def clean(self):
        cleaned = super().clean()
        ciudad = cleaned.get('ciudad')
        numero = cleaned.get('numero_codigo')
        if ciudad and numero:
            prefijo = self.CIUDAD_PREFIJOS.get(ciudad)
            if not prefijo:
                self.add_error('ciudad', 'No hay prefijo de código definido para esta ciudad.')
                return cleaned
            codigo = f"{prefijo}{numero}"
            duplicados = Constructora.objects.filter(codigo__iexact=codigo)
            if self.instance and self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error('numero_codigo', f'Ya existe una empresa con el código {codigo}.')
            else:
                self._codigo_generado = codigo
        return cleaned

    def save(self, commit=True):
        empresa = super().save(commit=False)
        empresa.codigo = self._codigo_generado
        if commit:
            empresa.save()
        return empresa

class ObraForm(forms.ModelForm):
    # El código de obra se arma como CODIGO_EMPRESA + '-' + número (ej: BUC52-1).
    # Texto (ver ConstructoraForm): hay obras migradas con código que no sigue al de su empresa
    # (BOG1-13 bajo BOG1B, BOG10-WP590); al editarlas se muestra el código completo.
    numero_codigo = forms.CharField(
        label='Número de obra',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: 1',
            'inputmode': 'numeric',
            'autocomplete': 'off',
        }),
    )
    _NUMERO_OBRA = re.compile(r'^\d+(-\d+)*$')                      # 1 · 12-1 (obra de cliente varios)
    _CODIGO_COMPLETO = re.compile(r'^[A-Z]{3}\d+(-\d+)?[A-Z]?-[\w-]+$')  # BOG1-13 · BOG10-WP590

    class Meta:
        model = Obra
        fields = ['nombre']  # codigo_obra se construye desde el prefijo; constructora no se edita
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.constructora = kwargs.pop('constructora', None)
        super().__init__(*args, **kwargs)
        # Al editar, la constructora viene de la instancia.
        if self.constructora is None and self.instance and self.instance.pk:
            self.constructora = self.instance.constructora
        # Pre-llenar el número separándolo del prefijo. Si el código no sigue al de la
        # empresa, se edita completo (sin prefijo delante).
        self.codigo_completo = False
        if self.instance and self.instance.pk and self.instance.codigo_obra:
            codigo = self.instance.codigo_obra
            if self.prefijo_codigo and codigo.upper().startswith(self.prefijo_codigo.upper()):
                self.fields['numero_codigo'].initial = codigo[len(self.prefijo_codigo):]
            else:
                self.codigo_completo = True
                self.fields['numero_codigo'].initial = codigo
                self.fields['numero_codigo'].label = 'Código de obra'
                self.fields['numero_codigo'].widget.attrs.pop('inputmode', None)

    @property
    def prefijo_codigo(self):
        if self.codigo_completo:
            return ''
        return f"{self.constructora.codigo}-" if self.constructora else ''

    def clean_numero_codigo(self):
        numero = (self.cleaned_data.get('numero_codigo') or '').strip().upper().replace(' ', '')
        if self.codigo_completo:
            if not self._CODIGO_COMPLETO.match(numero):
                raise forms.ValidationError('Escriba el código completo de la obra, por ejemplo BOG1-13.')
            return numero
        if not self._NUMERO_OBRA.match(numero):
            raise forms.ValidationError('Ingrese solo el número de obra (ej: 1), sin el prefijo.')
        return numero

    def clean(self):
        cleaned = super().clean()
        numero = cleaned.get('numero_codigo')
        if numero and self.constructora:
            codigo = numero if self.codigo_completo else f"{self.constructora.codigo}-{numero}"
            duplicados = Obra.objects.filter(
                constructora=self.constructora, codigo_obra__iexact=codigo
            )
            if self.instance and self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error(
                    'numero_codigo',
                    f'Ya existe una obra con el código {codigo} en esta empresa.',
                )
            else:
                self._codigo_generado = codigo
        return cleaned

    def save(self, commit=True):
        obra = super().save(commit=False)
        obra.codigo_obra = self._codigo_generado
        if commit:
            obra.save()
        return obra