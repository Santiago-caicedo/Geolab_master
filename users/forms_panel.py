"""
Formulario único del Panel de usuarios: cuenta + rol + lo que ese rol necesita.

- Geolab: área (FuncionarioGeolab) y código de empleado.
  · Usuario de Facturación: ciudades y secciones (AccesoFacturacion).
  · Técnico: áreas de Calidad con lectura o edición (AccesoAreaUsuario).
  · Usuario de Calidad: sus carpetas se asignan en otra pantalla del panel.
- Cliente: empresa, rol, cargo, teléfono y, para residente/remitente, sus obras.

Todo se guarda en una transacción: nunca queda un usuario es_geolab=True sin
perfil (el fallback de es_admin_geolab lo volvería administrador total).
"""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from calidad.models import AccesoAreaUsuario, AreaCalidad
from core.models import Obra
from facturacion import permisos as permisos_fx
from facturacion import sede
from facturacion.models import AccesoFacturacion

from . import roles
from .models import ClienteExterno, Constructora, FuncionarioGeolab, UsuarioBase

NIVELES_CALIDAD = [('', 'Sin acceso'), ('lectura', 'Lectura'), ('edicion', 'Edición')]


class UsuarioPanelForm(forms.Form):
    rol = forms.ChoiceField(label='Rol', error_messages={'required': 'Elija el rol de la persona.'})
    username = forms.CharField(label='Usuario', max_length=150)
    nombre = forms.CharField(label='Nombres', max_length=150, required=False)
    apellido = forms.CharField(label='Apellidos', max_length=150, required=False)
    email = forms.EmailField(label='Correo electrónico', required=False)
    password1 = forms.CharField(label='Contraseña', required=False, strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label='Repetir contraseña', required=False, strip=False, widget=forms.PasswordInput)
    superusuario = forms.BooleanField(label='Superusuario', required=False)
    admin_django = forms.BooleanField(label='Acceso al admin de Django', required=False)

    # Geolab
    codigo_empleado = forms.CharField(label='Código de empleado', max_length=20, required=False)
    ciudades = forms.MultipleChoiceField(label='Ciudades', required=False, widget=forms.CheckboxSelectMultiple)
    secciones = forms.MultipleChoiceField(label='Secciones', required=False, widget=forms.CheckboxSelectMultiple,
                                          choices=[(c, n) for c, n, _g, _d in permisos_fx.SECCIONES])

    # Cliente
    empresa = forms.ModelChoiceField(label='Empresa', required=False, queryset=Constructora.objects.order_by('nombre'))
    cargo = forms.CharField(label='Cargo', max_length=100, required=False)
    telefono = forms.CharField(label='Teléfono', max_length=20, required=False)
    obras = forms.ModelMultipleChoiceField(label='Obras', required=False, queryset=Obra.objects.all())

    def __init__(self, *args, usuario=None, actor=None, **kwargs):
        self.usuario = usuario
        self.actor = actor
        super().__init__(*args, **kwargs)

        # Una cuenta existente no cambia de familia (Geolab <-> cliente): sus datos cuelgan de perfiles
        # distintos. Solo una cuenta sin familia puede recibir cualquier rol.
        familia = roles.familia_de(usuario) if usuario else None
        opciones = [r for r in roles.ROLES if not familia or r.familia == familia]
        self.fields['rol'].choices = [(r.clave, r.nombre) for r in opciones]

        disponibles = sede.ciudades_disponibles()
        guardadas = []
        acceso = roles.acceso_facturacion(usuario) if usuario else None
        if acceso:
            guardadas = [c for c in acceso.ciudades if c not in disponibles]
        self.fields['ciudades'].choices = [(c, c) for c in disponibles + guardadas]

        self.areas_calidad = list(AreaCalidad.objects.all())
        for area in self.areas_calidad:
            self.fields[f'calidad_{area.pk}'] = forms.ChoiceField(
                label=f'{area.numero}. {area.nombre}', required=False, choices=NIVELES_CALIDAD)

        if usuario is None:
            # Al crear se pide el nombre; al editar no, porque hay cuentas viejas (WordPress) sin él
            self.fields['nombre'].required = True
            self.fields['password1'].required = True
            self.fields['password2'].required = True

    # ── iniciales de una cuenta existente ─────────────────────────────────
    @staticmethod
    def iniciales(usuario):
        datos = {
            'rol': roles.rol_de(usuario) or '',
            'username': usuario.username, 'nombre': usuario.first_name,
            'apellido': usuario.last_name, 'email': usuario.email,
            'superusuario': usuario.is_superuser,
            'admin_django': usuario.is_staff,
        }
        geo = roles.perfil_geolab(usuario)
        if geo:
            datos['codigo_empleado'] = geo.codigo_empleado
        acceso = roles.acceso_facturacion(usuario)
        if acceso:
            datos['ciudades'] = acceso.ciudades
            datos['secciones'] = acceso.secciones
        for a in AccesoAreaUsuario.objects.filter(usuario=usuario):
            datos[f'calidad_{a.area_id}'] = 'edicion' if a.puede_editar else 'lectura'
        cli = roles.perfil_cliente(usuario)
        if cli:
            datos.update(empresa=cli.empresa_id, cargo=cli.cargo, telefono=cli.telefono,
                         obras=list(cli.obras_asignadas.values_list('pk', flat=True)))
        return datos

    def campos_calidad(self):
        return [self[f'calidad_{a.pk}'] for a in self.areas_calidad]

    # ── validación ────────────────────────────────────────────────────────
    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        otros = UsuarioBase.objects.filter(username__iexact=username)
        if self.usuario:
            otros = otros.exclude(pk=self.usuario.pk)
        if otros.exists():
            raise forms.ValidationError('Ya existe un usuario con ese nombre.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email:
            otros = UsuarioBase.objects.filter(email__iexact=email)
            if self.usuario:
                otros = otros.exclude(pk=self.usuario.pk)
            if otros.exists():
                raise forms.ValidationError('Otro usuario ya tiene ese correo.')
        return email

    def clean(self):
        datos = super().clean()
        rol = roles.POR_CLAVE.get(datos.get('rol'))

        p1, p2 = datos.get('password1'), datos.get('password2')
        if p1 or p2:
            if p1 != p2:
                self.add_error('password2', 'Las contraseñas no coinciden.')
            else:
                tentativo = UsuarioBase(username=datos.get('username') or '', email=datos.get('email') or '',
                                        first_name=datos.get('nombre') or '', last_name=datos.get('apellido') or '')
                try:
                    validate_password(p1, tentativo)
                except forms.ValidationError as e:
                    self.add_error('password1', e)

        # Nadie se quita a sí mismo el superusuario (ni deja el portal sin uno)
        if self.usuario and self.actor and self.usuario.pk == self.actor.pk and self.usuario.is_superuser \
                and not datos.get('superusuario'):
            self.add_error('superusuario', 'No puede quitarse a sí mismo el superusuario.')
        if self.usuario and self.actor and self.usuario.pk == self.actor.pk and self.usuario.is_staff                 and not datos.get('admin_django'):
            self.add_error('admin_django', 'No puede quitarse a sí mismo el acceso al admin de Django.')

        if not rol:
            return datos

        if rol.clave == 'facturacion':
            if not datos.get('ciudades'):
                self.add_error('ciudades', 'Elija al menos una ciudad.')
            if not datos.get('secciones'):
                self.add_error('secciones', 'Elija al menos una sección.')

        if rol.familia == 'cliente':
            if not datos.get('email'):
                self.add_error('email', 'Los clientes necesitan correo: por ahí les llegan los avisos.')
            empresa = datos.get('empresa')
            if not empresa:
                self.add_error('empresa', 'Elija la empresa.')
            elif rol.clave in roles.CON_OBRAS:
                ajenas = [o for o in datos.get('obras') or [] if o.constructora_id != empresa.pk]
                if ajenas:
                    self.add_error('obras', 'Hay obras que no son de esa empresa: ' + ', '.join(o.nombre for o in ajenas[:3]))
        return datos

    def rol_elegido(self):
        return roles.POR_CLAVE[self.cleaned_data['rol']]

    def secciones_ordenadas(self):
        elegidas = set(self.cleaned_data.get('secciones') or [])
        return [c for c in permisos_fx.CLAVES if c in elegidas]

    # ── guardar ───────────────────────────────────────────────────────────
    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        rol = self.rol_elegido()
        usuario = self.usuario or UsuarioBase(is_active=True)
        usuario.username = d['username']
        usuario.first_name = d.get('nombre') or ''
        usuario.last_name = d.get('apellido') or ''
        usuario.email = d.get('email') or ''
        usuario.es_geolab = rol.familia == 'geolab'
        usuario.es_cliente = rol.familia == 'cliente'
        # Son independientes: el admin de Django exige is_staff, así que un superusuario sin él
        # manda en todo el portal pero no entra a /admin/.
        usuario.is_superuser = bool(d.get('superusuario'))
        usuario.is_staff = bool(d.get('admin_django'))
        if d.get('password1'):
            usuario.set_password(d['password1'])
        usuario.save()

        if rol.familia == 'geolab':
            FuncionarioGeolab.objects.update_or_create(
                user=usuario, defaults={'area': rol.clave, 'codigo_empleado': d.get('codigo_empleado') or ''})
            if rol.clave == 'facturacion':
                AccesoFacturacion.objects.update_or_create(
                    usuario=usuario, defaults={'ciudades': d['ciudades'], 'secciones': self.secciones_ordenadas(),
                                               'actualizado_por': self.actor})
            if rol.clave == 'tecnico':
                self._guardar_areas_calidad(usuario)
        else:
            cliente, _ = ClienteExterno.objects.update_or_create(
                user=usuario, defaults={'empresa': d['empresa'], 'rol': rol.clave,
                                        'cargo': d.get('cargo') or '', 'telefono': d.get('telefono') or ''})
            if rol.clave in roles.CON_OBRAS:
                cliente.obras_asignadas.set(d.get('obras') or [])
            else:
                # El director ve toda su empresa; si cambió de empresa, no se queda con obras de la anterior
                cliente.obras_asignadas.remove(*cliente.obras_asignadas.exclude(constructora=d['empresa']))
        return usuario

    def _guardar_areas_calidad(self, usuario):
        for area in self.areas_calidad:
            nivel = self.cleaned_data.get(f'calidad_{area.pk}') or ''
            if not nivel:
                AccesoAreaUsuario.objects.filter(usuario=usuario, area=area).delete()
                continue
            AccesoAreaUsuario.objects.update_or_create(
                usuario=usuario, area=area,
                defaults={'puede_editar': nivel == 'edicion', 'asignado_por': self.actor})
