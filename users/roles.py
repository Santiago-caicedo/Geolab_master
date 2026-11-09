"""
Catálogo único de roles del portal y diagnóstico de cada cuenta.

Lo usa el Panel de usuarios (users/views_panel.py): un rol es un área de
FuncionarioGeolab (familia "geolab") o un rol de ClienteExterno (familia
"cliente"). Las claves son las mismas que guardan esos modelos.
"""

from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist


@dataclass(frozen=True)
class Rol:
    clave: str
    familia: str          # 'geolab' | 'cliente'
    nombre: str
    alcance: str          # qué puede hacer, en una frase
    icono: str


ROLES = [
    Rol('admin', 'geolab', 'Administrativo', 'Todo el portal.', 'briefcase'),
    Rol('lab', 'geolab', 'Supervisor de laboratorio', 'Todo el portal.', 'clipboard2-data'),
    Rol('recepcion', 'geolab', 'Recepción de muestras', 'Todo el portal.', 'inbox'),
    Rol('tecnico', 'geolab', 'Técnico de laboratorio',
        'Ensayos y su panel; en Calidad, solo las áreas que se le den.', 'eyedropper'),
    Rol('calidad', 'geolab', 'Coordinador de Calidad',
        'Solo Calidad, donde manda: ve todo, sube, elimina y crea usuarios de calidad.', 'patch-check'),
    Rol('calidad_usuario', 'geolab', 'Usuario de Calidad',
        'Solo Calidad, y solo las carpetas que se le asignen.', 'folder2-open'),
    Rol('facturacion', 'geolab', 'Usuario de Facturación',
        'Solo Facturación, con las ciudades y secciones que se le asignen.', 'receipt-cutoff'),
    Rol('director', 'cliente', 'Director',
        'Todas las obras de su empresa: informes y remisiones.', 'buildings'),
    Rol('residente', 'cliente', 'Residente', 'Solo las obras que se le asignen.', 'person-workspace'),
    Rol('remitente', 'cliente', 'Remitente', 'Solo crear remisiones de las obras asignadas.', 'send'),
]

POR_CLAVE = {r.clave: r for r in ROLES}
GEOLAB = [r for r in ROLES if r.familia == 'geolab']
CLIENTE = [r for r in ROLES if r.familia == 'cliente']
TODO_EL_PORTAL = {'admin', 'lab', 'recepcion'}
CON_OBRAS = {'residente', 'remitente'}
FAMILIAS = {'geolab': 'Geolab', 'cliente': 'Clientes'}


def perfil_geolab(user):
    try:
        return user.perfil_geolab
    except ObjectDoesNotExist:
        return None


def perfil_cliente(user):
    try:
        return user.perfil_cliente
    except ObjectDoesNotExist:
        return None


def rol_de(user):
    """Clave del rol efectivo, o None si la cuenta no tiene uno válido."""
    if user.es_geolab:
        perfil = perfil_geolab(user)
        return perfil.area if perfil and perfil.area in POR_CLAVE else None
    if user.es_cliente:
        perfil = perfil_cliente(user)
        return perfil.rol if perfil and perfil.rol in POR_CLAVE else None
    return None


def familia_de(user):
    if user.es_geolab:
        return 'geolab'
    if user.es_cliente:
        return 'cliente'
    return None


def problemas_de(user):
    """
    Lo que está mal en la cuenta, como (gravedad, texto); gravedad 'rojo' = da
    más acceso del debido, 'ambar' = la persona no puede trabajar.
    Usa las anotaciones de la lista (num_carpetas, num_obras) si existen.
    """
    out = []
    if user.es_geolab and user.es_cliente:
        out.append(('rojo', 'Está marcada como Geolab y como cliente a la vez.'))
    if user.es_geolab and not perfil_geolab(user) and not user.is_superuser:
        out.append(('rojo', 'Es de Geolab pero no tiene área: hoy el portal la trata como administrador total.'))
    if user.es_cliente and not user.es_geolab and not perfil_cliente(user):
        out.append(('ambar', 'Es cliente pero no tiene empresa: no puede ver nada.'))
    if not user.es_geolab and not user.es_cliente and not user.is_superuser:
        out.append(('ambar', 'No tiene rol: al entrar solo ve una página de espera.'))
    rol = rol_de(user)
    if rol == 'facturacion':
        acceso = acceso_facturacion(user)
        if not acceso or not acceso.ciudades or not acceso.secciones:
            out.append(('ambar', 'Sin ciudades o sin secciones de Facturación: no puede entrar.'))
    elif rol == 'calidad_usuario':
        n = getattr(user, 'num_carpetas', None)
        if n is None:
            n = user.accesos_carpetas_calidad.count()
        if not n:
            out.append(('ambar', 'Sin carpetas de Calidad asignadas: no ve nada.'))
    elif rol in CON_OBRAS:
        n = getattr(user, 'num_obras', None)
        if n is None:
            perfil = perfil_cliente(user)
            n = perfil.obras_asignadas.count() if perfil else 0
        if not n:
            out.append(('ambar', 'Sin obras asignadas: no ve ninguna obra.'))
    return out


def acceso_facturacion(user):
    try:
        return user.acceso_facturacion
    except ObjectDoesNotExist:
        return None
