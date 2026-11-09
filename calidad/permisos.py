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


# ── Matriz de permisos por carpeta (pantalla del coordinador y Panel de usuarios) ──

def arbol_permisos(usuario):
    """
    Árbol de carpetas por área, aplanado con su nivel y la fila de permisos del
    usuario: [{'area', 'filas': [{'carpeta', 'nivel', 'grant'}]}].
    """
    grants = {g.carpeta_id: g for g in AccesoCarpetaUsuario.objects.filter(usuario=usuario)}
    secciones = []
    for area in AreaCalidad.objects.all():
        hijos = defaultdict(list)
        for carpeta in Carpeta.objects.filter(area=area):
            hijos[carpeta.padre_id].append(carpeta)
        filas = []

        def aplanar(padre_id, nivel):
            for carpeta in hijos.get(padre_id, []):
                filas.append({'carpeta': carpeta, 'nivel': nivel, 'grant': grants.get(carpeta.pk)})
                aplanar(carpeta.pk, nivel + 1)

        aplanar(None, 0)
        if filas:
            secciones.append({'area': area, 'filas': filas})
    return secciones


def guardar_permisos(usuario, datos, asignado_por):
    """
    Reemplaza los permisos del usuario por los marcados en `datos` (request.POST
    con ver_<pk>, cargar_<pk>, eliminar_<pk>). Cargar o eliminar implican ver.
    Devuelve cuántas carpetas quedaron con acceso. Llamar dentro de una transacción.
    """
    AccesoCarpetaUsuario.objects.filter(usuario=usuario).delete()
    nuevos = []
    for pk in Carpeta.objects.values_list('pk', flat=True):
        cargar = f'cargar_{pk}' in datos
        eliminar = f'eliminar_{pk}' in datos
        if f'ver_{pk}' in datos or cargar or eliminar:
            nuevos.append(AccesoCarpetaUsuario(
                usuario=usuario, carpeta_id=pk, puede_ver=True,
                puede_cargar=cargar, puede_eliminar=eliminar, asignado_por=asignado_por,
            ))
    AccesoCarpetaUsuario.objects.bulk_create(nuevos)
    return len(nuevos)
