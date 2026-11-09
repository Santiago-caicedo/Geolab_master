"""
Permisos dentro del módulo de Facturación.

Hay dos clases de usuario que entran al módulo:

- Acceso completo: superusuarios y staff administrativo de Geolab
  (`es_admin_geolab`). Ven todas las ciudades y todas las secciones, como siempre.
- Usuario de Facturación (`FuncionarioGeolab.area = 'facturacion'`): solo las
  ciudades y secciones de su `AccesoFacturacion`. El middleware
  `RestriccionFacturacionMiddleware` lo encierra en /facturacion/.

Cada vista del módulo se identifica por su `url_name` y `VISTAS` dice qué
secciones la abren. Una vista que no esté en `VISTAS` queda CERRADA para el
Usuario de Facturación (deny by default): al agregar una vista nueva hay que
ponerla aquí (un test revisa que todas las rutas del módulo estén).
"""

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from . import sede

# (clave, nombre, grupo, qué permite). El orden es el del menú lateral y decide
# la pantalla de inicio (la primera sección permitida).
SECCIONES = (
    ('panel', 'Panel de facturación', 'Panel',
     'Resumen del mes, lo que falta facturar y cobrar, y la tendencia.'),
    ('registrar', 'Registrar servicio', 'Operación',
     'Registrar servicios realizados a una obra.'),
    ('generar', 'Generar factura', 'Operación',
     'Vista previa y emisión de facturas, y descargar el PDF de la que acaba de generar.'),
    ('historico', 'Histórico', 'Operación',
     'Ver, editar y eliminar los servicios registrados.'),
    ('repositorio', 'Repositorio de facturas', 'Repositorio',
     'Ver las facturas, descargar el PDF, marcarlas pagadas o pendientes y anularlas.'),
    ('precios', 'Precios por obra', 'Configuración',
     'Ver y cambiar la lista de precios de cada obra.'),
    ('catalogo', 'Catálogo de servicios', 'Configuración',
     'Crear, editar y eliminar categorías y servicios.'),
    ('impuestos', 'Impuestos', 'Configuración',
     'Crear y editar el IVA. Ojo: los impuestos valen para TODAS las ciudades.'),
)
CLAVES = tuple(s[0] for s in SECCIONES)
NOMBRES = {s[0]: s[1] for s in SECCIONES}

# Pantalla principal de cada sección (inicio del usuario y enlaces del menú)
INICIO = {
    'panel': 'dashboard_facturacion',
    'registrar': 'crear_registro_facturacion',
    'generar': 'generar_factura',
    'historico': 'historico_facturacion',
    'repositorio': 'repositorio_clientes',
    'precios': 'precios_obras',
    'catalogo': 'catalogo_servicios',
    'impuestos': 'lista_impuestos',
}


def _s(*claves):
    return frozenset(claves)


# url_name → secciones que la abren (basta UNA)
VISTAS = {
    # Panel
    'dashboard_facturacion': _s('panel'),
    'api_facturacion_mensual': _s('panel'),
    # Operación
    'crear_registro_facturacion': _s('registrar'),
    'generar_factura': _s('generar'),
    'finalizar_factura': _s('generar'),
    'historico_facturacion': _s('historico'),
    'editar_registro_facturacion': _s('historico'),
    'eliminar_registro_facturacion': _s('historico'),
    # Repositorio
    'repositorio_clientes': _s('repositorio'),
    'repositorio_obras_cliente': _s('repositorio'),
    'repositorio_facturas_obra': _s('repositorio'),
    'anular_factura': _s('repositorio'),
    'marcar_factura_pagada': _s('repositorio'),
    'marcar_factura_pendiente': _s('repositorio'),
    # Quien genera una factura puede bajar su PDF aunque no tenga el repositorio
    'descargar_factura_pdf': _s('repositorio', 'generar'),
    # Configuración
    'precios_obras': _s('precios'),
    'gestionar_precios_obra': _s('precios'),
    'guardar_precio_obra': _s('precios'),
    'catalogo_servicios': _s('catalogo'),
    'crear_categoria_facturacion': _s('catalogo'),
    'editar_categoria_facturacion': _s('catalogo'),
    'crear_servicio_facturacion': _s('catalogo'),
    'editar_servicio_facturacion': _s('catalogo'),
    'eliminar_servicio_facturacion': _s('catalogo'),
    'lista_impuestos': _s('impuestos'),
    'crear_impuesto': _s('impuestos'),
    'editar_impuesto': _s('impuestos'),
    # APIs que usan varias pantallas: la abre cualquiera de ellas
    'api_get_obras_facturacion': _s('registrar', 'generar', 'historico'),
    'api_get_precio': _s('registrar'),
    'api_buscar_servicios': _s('registrar'),
}

# Rutas del módulo que no pasan por VISTAS: el selector de ciudad (lo abre todo
# usuario del módulo, con sus ciudades) y la administración de usuarios (solo
# superusuarios, con su propio decorador).
SIN_SECCION = frozenset({
    'seleccionar_ciudad_facturacion',
    'usuarios_facturacion', 'crear_usuario_facturacion',
    'editar_usuario_facturacion', 'estado_usuario_facturacion',
})


def tiene_todo(user):
    """Acceso completo: superusuario o staff administrativo de Geolab."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or (user.es_geolab and user.es_admin_geolab)


def es_restringido(user):
    """Usuario de Facturación (los superusuarios nunca lo son)."""
    return user.is_authenticated and not user.is_superuser and user.es_usuario_facturacion


def acceso_de(user):
    try:
        return user.acceso_facturacion
    except (ObjectDoesNotExist, AttributeError):
        return None


def secciones_de(user):
    if tiene_todo(user):
        return frozenset(CLAVES)
    if not es_restringido(user):
        return frozenset()
    acceso = acceso_de(user)
    return frozenset(s for s in (acceso.secciones if acceso else []) if s in CLAVES)


def ciudades_de(user):
    """Ciudades que el usuario puede elegir (las que existen hoy en Constructora.ciudad)."""
    disponibles = sede.ciudades_disponibles()
    if tiene_todo(user):
        return disponibles
    if not es_restringido(user):
        return []
    acceso = acceso_de(user)
    permitidas = {c.lower() for c in (acceso.ciudades if acceso else [])}
    return [c for c in disponibles if c.lower() in permitidas]


def puede_ciudad(user, ciudad):
    if tiene_todo(user):
        return True
    return bool(ciudad) and ciudad.lower() in {c.lower() for c in ciudades_de(user)}


def ciudad_unica(user):
    """La ciudad a fijar sin preguntar: solo para el Usuario de Facturación con una sola."""
    if not es_restringido(user):
        return None
    ciudades = ciudades_de(user)
    return ciudades[0] if len(ciudades) == 1 else None


def puede_entrar(user):
    """¿Puede usar el módulo? El Usuario de Facturación necesita al menos una ciudad y una sección."""
    if tiene_todo(user):
        return True
    return es_restringido(user) and bool(secciones_de(user)) and bool(ciudades_de(user))


def puede_vista(user, url_name):
    if tiene_todo(user):
        return True
    if not es_restringido(user):
        return False
    secciones = VISTAS.get(url_name)
    return bool(secciones and secciones & secciones_de(user))


def puede_seccion(user, clave):
    return clave in secciones_de(user)


def url_inicio(user):
    """Primera pantalla permitida (el panel para quien lo tiene)."""
    permitidas = secciones_de(user)
    for clave in CLAVES:
        if clave in permitidas:
            return reverse(INICIO[clave])
    return reverse('seleccionar_ciudad_facturacion')


def nombre_de_vista(url_name):
    secciones = VISTAS.get(url_name) or ()
    for clave in CLAVES:
        if clave in secciones:
            return NOMBRES[clave]
    return 'esta pantalla'


def grupos():
    """[(grupo, [(clave, nombre, descripcion), ...]), ...] en el orden del menú."""
    salida = []
    for clave, nombre, grupo, descripcion in SECCIONES:
        if not salida or salida[-1][0] != grupo:
            salida.append((grupo, []))
        salida[-1][1].append((clave, nombre, descripcion))
    return salida


class _Mapa(dict):
    """Lo que los templates del módulo preguntan: {{ fx_puede.historico }}, fx_puede.inicio…"""


def mapa(user):
    secciones = secciones_de(user)
    m = _Mapa({clave: clave in secciones for clave in CLAVES})
    m['inicio'] = url_inicio(user)
    m['restringido'] = es_restringido(user)
    m['portal'] = not es_restringido(user)  # enlaces fuera del módulo (empresas, obras)
    m['usuarios'] = user.is_superuser
    m['cambiar_ciudad'] = not es_restringido(user) or len(ciudades_de(user)) > 1
    m['operacion'] = any(m[c] for c in ('registrar', 'generar', 'historico'))
    m['configuracion'] = any(m[c] for c in ('precios', 'catalogo', 'impuestos')) or m['usuarios']
    return m


def contexto(request):
    """Context processor: `fx_puede` en las páginas de /facturacion/ (calculado al usarlo)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    if not request.path.startswith('/facturacion/') and not user.es_usuario_facturacion:
        return {}
    from django.utils.functional import SimpleLazyObject
    return {'fx_puede': SimpleLazyObject(lambda: mapa(user))}
