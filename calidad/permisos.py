"""
Logica de permisos por carpeta para los Usuarios de Calidad.

Semantica:
- El permiso es EXACTO por carpeta: una carpeta tiene fila en
  AccesoCarpetaUsuario o esta bloqueada. No hay herencia implicita hacia las
  subcarpetas (la matriz de asignacion ofrece marcado en cascada, pero lo que
  vale es lo guardado). Asi, quitar una carpeta nunca requiere reglas de
  "denegacion" que compliquen el modelo.
- Los ANCESTROS de una carpeta permitida son "de paso": el usuario los ve en
  la navegacion para poder llegar a su carpeta, pero sin documentos y sin
  acciones (ni subir, ni eliminar, ni descargar).
- Areas visibles: solo aquellas con al menos una carpeta permitida.
"""

from collections import defaultdict

from .models import AccesoCarpetaUsuario, AreaCalidad, Carpeta


def grants_del_usuario(user, area=None):
    """Filas de acceso del usuario, opcionalmente limitadas a un area."""
    qs = AccesoCarpetaUsuario.objects.filter(usuario=user)
    if area is not None:
        qs = qs.filter(carpeta__area=area)
    return {g.carpeta_id: g for g in qs}


def permisos_en_carpeta(user, carpeta):
    """
    Permisos efectivos del usuario sobre una carpeta concreta.
    Devuelve dict(ver, cargar, eliminar, de_paso).
    """
    grants = grants_del_usuario(user, carpeta.area)
    g = grants.get(carpeta.pk)
    if g:
        return {
            'ver': g.puede_ver, 'cargar': g.puede_cargar,
            'eliminar': g.puede_eliminar, 'de_paso': False,
        }
    if carpeta.pk in _ancestros_de_paso(carpeta.area, grants):
        # Carpeta intermedia: se puede atravesar pero no operar.
        return {'ver': False, 'cargar': False, 'eliminar': False, 'de_paso': True}
    return None


def mapa_visibilidad_area(user, area):
    """
    Conjunto de carpetas del area que el usuario puede ver en la navegacion
    (permitidas + de paso) y sus filas de permiso.
    Devuelve (ids_visibles, grants_por_carpeta_id).
    """
    grants = grants_del_usuario(user, area)
    visibles = set(grants) | _ancestros_de_paso(area, grants)
    return visibles, grants


def areas_visibles(user):
    """Areas con al menos una carpeta permitida, con conteo de carpetas."""
    conteo = defaultdict(int)
    for g in AccesoCarpetaUsuario.objects.filter(
        usuario=user
    ).select_related('carpeta'):
        conteo[g.carpeta.area_id] += 1
    areas = AreaCalidad.objects.filter(pk__in=conteo)
    return [(area, conteo[area.pk]) for area in areas]


def _ancestros_de_paso(area, grants):
    """Ids de los ancestros de las carpetas permitidas (navegacion de paso)."""
    padres = dict(Carpeta.objects.filter(area=area).values_list('id', 'padre_id'))
    de_paso = set()
    for carpeta_id in grants:
        padre = padres.get(carpeta_id)
        while padre is not None and padre not in de_paso:
            de_paso.add(padre)
            padre = padres.get(padre)
    return de_paso - set(grants)
