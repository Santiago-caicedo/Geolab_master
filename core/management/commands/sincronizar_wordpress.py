"""
Sincroniza constructoras, obras e informes desde el WordPress viejo, dejando
la base normalizada. Reemplaza a migrar_geolab y se puede correr las veces
que haga falta (idempotente): trae lo nuevo y corrige lo ya migrado.

    python manage.py sincronizar_wordpress --dry-run          # lee la base viva (WP_DB_* del .env)
    python manage.py sincronizar_wordpress
    python manage.py sincronizar_wordpress --dump portal.sql   # desde un volcado
    python manage.py sincronizar_wordpress --sin-informes --omitir 22054 --omitir 31000

Reglas (core/wp_normalizar.py):
- Obra: identidad = id_wp_original. nombre = nombre-proyecto; codigo_obra =
  código real ("BUC46-9"); ciudad/dirección/teléfono/contacto desde WP.
  Nunca se borra una obra (facturación y remisiones apuntan a ellas).
- Constructora: código = prefijo + número de empresa ("BUC46"); clientes
  varios "0-N" = código completo ("BUC0-12") + razón social. Las constructoras
  mal creadas por la migración vieja (p. ej. "IBA131") se RENOMBRAN al código
  correcto si todas sus obras van al mismo grupo (así se conservan usuarios
  y facturas); si no, sus obras se mueven y, cuando queda vacía y sin
  usuarios ni facturas, se elimina.
- Informes: identidad = id_wp_original; título = nombre del PDF; se ligan a
  la obra por id de WP. Los PDF se bajan aparte con descargar_archivos.
"""

import re
from collections import defaultdict

from decouple import config
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils.timezone import is_naive, make_aware

from core.models import Informe, Obra
from core.wp_fuente import FuenteDump, FuenteMySQL
from core.wp_normalizar import (
    ciudad_obra, clave_constructora, codigo_obra, nombre_obra, razon_social_canonica,
)
from facturacion.models import Factura
from users.models import ClienteExterno, Constructora


class _Rollback(Exception):
    pass


def _aware(fecha):
    if fecha is None:
        return None
    return make_aware(fecha) if is_naive(fecha) else fecha


class Command(BaseCommand):
    help = 'Trae y normaliza constructoras, obras e informes desde el WordPress viejo (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--dump', help='Volcado .sql de WordPress en vez de la base viva')
        parser.add_argument('--dry-run', action='store_true', help='Muestra todo y no guarda nada')
        parser.add_argument('--sin-informes', action='store_true', help='Solo constructoras y obras')
        parser.add_argument('--omitir', action='append', type=int, default=[], metavar='ID_WP',
                            help='ID de proyecto de WordPress a ignorar (repetible)')
        parser.add_argument('--detalle', action='store_true', help='Lista cada obra e informe tocado')

    # ─────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        fuente = self._fuente(o['dump'])
        try:
            proyectos = fuente.proyectos()
            informes = [] if o['sin_informes'] else fuente.informes()
        finally:
            fuente.cerrar()
        self.detalle = o['detalle']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'WordPress: {len(proyectos)} proyectos, {len(informes)} informes'
        ))
        try:
            with transaction.atomic():
                grupos, obras_wp = self._clasificar(proyectos, set(o['omitir']))
                destino = self._sincronizar_constructoras(grupos)
                self._sincronizar_obras(obras_wp, destino)
                self._eliminar_obras_basura()
                self._limpiar_constructoras()
                if informes:
                    self._sincronizar_informes(informes)
                self._avisos()
                if o['dry_run']:
                    self.stdout.write(self.style.WARNING('\n[DRY-RUN] No se escribió nada en la base de datos.'))
                    raise _Rollback
        except _Rollback:
            return
        self.stdout.write(self.style.SUCCESS('\nSincronización guardada.'))

    def _fuente(self, dump):
        if dump:
            return FuenteDump(dump)
        try:
            return FuenteMySQL(
                host=config('WP_DB_HOST', default='localhost'),
                user=config('WP_DB_USER', default='root'),
                password=config('WP_DB_PASSWORD', default=''),
                db=config('WP_DB_NAME', default='wp_backup'),
            )
        except Exception as e:  # noqa: BLE001 - se informa tal cual
            raise CommandError(f'No se pudo conectar a la base de WordPress (WP_DB_* en .env): {e}')

    # ─────────────────────────────────────────────────────────────────
    def _clasificar(self, proyectos, omitir):
        """Agrupa los proyectos publicados por constructora normalizada."""
        grupos = defaultdict(list)          # (codigo, es_varios) -> [proyecto]
        obras_wp = []
        self.saltados = []
        for p in sorted(proyectos, key=lambda x: (x.fecha or _MIN, x.id)):
            if p.id in omitir:
                self.saltados.append((p, '--omitir'))
                continue
            if p.estado != 'publish':
                self.saltados.append((p, f'estado {p.estado}'))
                continue
            codigo, varios = clave_constructora(p)
            if codigo is None:
                self.saltados.append((p, f'código de cliente irreconocible "{p.m("codigo-cliente_743")}"'))
                continue
            grupos[(codigo, varios)].append(p)
            obras_wp.append((p, codigo, varios))

        # Clientes varios: mismo "0-N" con razones sociales distintas = empresas distintas
        finales = {}
        self.varios_desdoblados = []
        for (codigo, varios), lista in grupos.items():
            if not varios:
                finales[codigo] = lista
                continue
            por_razon = defaultdict(list)
            for p in lista:
                por_razon[_clave_razon(p.m('razon-social'))].append(p)
            for n, (_, sub) in enumerate(sorted(por_razon.items(), key=lambda kv: min((x.fecha or _MIN) for x in kv[1]))):
                cod = codigo if n == 0 else f'{codigo}{chr(ord("A") + n)}'
                finales[cod] = sub
                if n:
                    self.varios_desdoblados.append((codigo, cod, sub[0].m('razon-social')))
        # mapa proyecto -> código final
        self.codigo_de = {p.id: cod for cod, lista in finales.items() for p in lista}
        return finales, [(p, self.codigo_de[p.id]) for p, _, _ in obras_wp]

    # ─────────────────────────────────────────────────────────────────
    def _sincronizar_constructoras(self, grupos):
        """Crea/renombra/actualiza constructoras. Devuelve {codigo: Constructora}."""
        self.stdout.write(self.style.MIGRATE_HEADING('\nConstructoras'))
        destino, st = {}, defaultdict(int)
        usados = set()
        for codigo, lista in sorted(grupos.items()):
            nombre = razon_social_canonica([p.m('razon-social') for p in lista])
            ciudad = razon_social_canonica([ciudad_obra(p) for p in lista])
            ids = [p.id for p in lista]
            actual = Constructora.objects.filter(codigo__iexact=codigo).first()
            if actual is None:
                # ¿Alguna constructora vieja tiene TODAS sus obras en este grupo? -> renombrar
                candidatas = (
                    Constructora.objects.filter(obras__id_wp_original__in=ids)
                    .exclude(pk__in=usados).annotate(n=Count('obras', distinct=True)).distinct()
                )
                for c in candidatas:
                    if c.n == Obra.objects.filter(constructora=c, id_wp_original__in=ids).count():
                        actual = c
                        self.stdout.write(f'  ~ {c.codigo} renombrada a {codigo}  ({nombre})')
                        st['renombradas'] += 1
                        actual.codigo = codigo
                        break
            if actual is None:
                actual = Constructora(codigo=codigo)
                st['creadas'] += 1
                self.stdout.write(f'  + {codigo}  {nombre}  [{ciudad}]')
            else:
                cambios = []
                if actual.nombre != nombre:
                    cambios.append(f'nombre "{actual.nombre}" -> "{nombre}"')
                if (actual.ciudad or '') != ciudad:
                    cambios.append(f'ciudad "{actual.ciudad}" -> "{ciudad}"')
                if cambios and self.detalle:
                    self.stdout.write(f'  ~ {codigo}: ' + '; '.join(cambios))
                if cambios:
                    st['actualizadas'] += 1
            actual.nombre, actual.ciudad = nombre, ciudad
            actual.save()
            usados.add(actual.pk)
            destino[codigo] = actual
        self.stdout.write(self.style.SUCCESS(
            f'Constructoras: {st["creadas"]} creadas, {st["renombradas"]} renombradas, {st["actualizadas"]} actualizadas.'
        ))
        return destino

    # ─────────────────────────────────────────────────────────────────
    def _sincronizar_obras(self, obras_wp, destino):
        self.stdout.write(self.style.MIGRATE_HEADING('\nObras'))
        st = defaultdict(int)
        self.sin_codigo, self.sin_nombre, codigos = [], [], defaultdict(list)
        for p, codigo_c in obras_wp:
            if not p.m('nombre-proyecto'):
                self.sin_nombre.append(p)
            c = destino[codigo_c]
            cod = codigo_obra(p, codigo_c)
            if cod is None:
                cod = f'{codigo_c}-WP{p.id}'
                self.sin_codigo.append((p, cod))
            codigos[cod].append(p)
            datos = dict(
                nombre=nombre_obra(p)[:255], codigo_obra=cod[:50], constructora=c,
                fecha_creacion=_aware(p.fecha),
                direccion=p.m('direccion')[:255], telefono=p.m('telefono')[:50],
                contacto=p.m('persona-de-contacto-1')[:150], celular=p.m('celular-1')[:50],
            )
            obra = Obra.objects.filter(id_wp_original=p.id).first()
            if obra is None:
                Obra.objects.create(id_wp_original=p.id, **datos)
                st['creadas'] += 1
                self.stdout.write(f'  + {cod:12} {datos["nombre"][:45]:45} ({c.codigo})')
                continue
            cambios = [k for k, v in datos.items() if getattr(obra, k) != v]
            if cambios:
                for k, v in datos.items():
                    setattr(obra, k, v)
                obra.save()
                st['actualizadas'] += 1
                if self.detalle or 'constructora' in cambios or 'codigo_obra' in cambios:
                    self.stdout.write(f'  ~ {cod:12} {datos["nombre"][:45]:45} cambios: {", ".join(cambios)}')
            else:
                st['iguales'] += 1
        self.codigos_repetidos = {k: v for k, v in codigos.items() if len(v) > 1}
        self.stdout.write(self.style.SUCCESS(
            f'Obras: {st["creadas"]} creadas, {st["actualizadas"]} actualizadas, {st["iguales"]} sin cambios.'
        ))

    # ─────────────────────────────────────────────────────────────────
    def _eliminar_obras_basura(self):
        """
        Obras que la migración vieja trajo de proyectos basura (código de cliente
        irreconocible). Se eliminan SOLO si no tienen nada colgado (informes,
        remisiones, precios, registros, facturas...); si lo tienen, se avisa.
        """
        self.basura_conservada = []
        ids = [p.id for p, motivo in self.saltados if motivo.startswith('código de cliente')]
        for obra in Obra.objects.filter(id_wp_original__in=ids):
            dependencias = _dependencias(obra)
            if dependencias:
                self.basura_conservada.append((obra, dependencias))
                continue
            self.stdout.write(f'  - obra basura "{obra.nombre}" ({obra.codigo_obra}) eliminada')
            obra.delete()

    def _limpiar_constructoras(self):
        """Constructoras que quedaron sin obras: mover usuarios/facturas si es inequívoco y borrar."""
        self.no_borradas = []
        borradas = 0
        for c in Constructora.objects.annotate(n=Count('obras')).filter(n=0):
            usuarios = ClienteExterno.objects.filter(empresa=c).count()
            facturas = Factura.objects.filter(constructora=c).count()
            if usuarios or facturas:
                self.no_borradas.append((c, usuarios, facturas))
                continue
            self.stdout.write(f'  - {c.codigo} "{c.nombre}" eliminada (sin obras, usuarios ni facturas)')
            c.delete()
            borradas += 1
        if borradas:
            self.stdout.write(self.style.SUCCESS(f'Constructoras vacías eliminadas: {borradas}.'))

    # ─────────────────────────────────────────────────────────────────
    def _sincronizar_informes(self, informes):
        self.stdout.write(self.style.MIGRATE_HEADING('\nInformes'))
        obras = {o.id_wp_original: o for o in Obra.objects.exclude(id_wp_original__isnull=True)}
        st = defaultdict(int)
        self.informes_sin_obra = 0
        existentes = {i.id_wp_original: i for i in Informe.objects.exclude(id_wp_original__isnull=True)}
        nuevos = []
        for inf in informes:
            if inf.estado != 'publish':
                st['no_publicados'] += 1
                continue
            obra = obras.get(inf.proyecto_id)
            if obra is None:
                self.informes_sin_obra += 1
                continue
            titulo = (inf.url_pdf.rsplit('/', 1)[-1] if inf.url_pdf else inf.titulo)[:255]
            actual = existentes.get(inf.id)
            if actual is None:
                nuevos.append(Informe(
                    id_wp_original=inf.id, titulo=titulo, obra=obra,
                    fecha_creacion=_aware(inf.fecha), url_archivo_original=inf.url_pdf,
                ))
                continue
            cambios = []
            if actual.obra_id != obra.pk:
                actual.obra = obra
                cambios.append('obra')
            if actual.titulo != titulo:
                actual.titulo = titulo
                cambios.append('titulo')
            if (actual.url_archivo_original or None) != inf.url_pdf:
                actual.url_archivo_original = inf.url_pdf
                cambios.append('url')
            if cambios:
                actual.save()
                st['actualizados'] += 1
            else:
                st['iguales'] += 1
        Informe.objects.bulk_create(nuevos, batch_size=1000)
        st['creados'] = len(nuevos)
        self.stdout.write(self.style.SUCCESS(
            f'Informes: {st["creados"]} creados, {st["actualizados"]} actualizados, {st["iguales"]} sin cambios, '
            f'{st["no_publicados"]} no publicados, {self.informes_sin_obra} sin obra.'
        ))
        if nuevos:
            self.stdout.write('  Los PDF nuevos se descargan con: python manage.py descargar_archivos')

    # ─────────────────────────────────────────────────────────────────
    def _avisos(self):
        avisos = []
        for p, motivo in self.saltados:
            avisos.append(f'proyecto WP {p.id} "{p.titulo}" omitido: {motivo}')
        for base, cod, razon in self.varios_desdoblados:
            avisos.append(f'cliente varios {base} con otra razón social -> creado como {cod} ("{razon}")')
        for p, cod in self.sin_codigo:
            avisos.append(f'obra WP {p.id} "{p.titulo}" sin código reconocible: se usó {cod}')
        for cod, lista in self.codigos_repetidos.items():
            avisos.append(f'código de obra {cod} repetido en WP: ' + ', '.join(f'{p.id} "{nombre_obra(p)}"' for p in lista))
        for c, u, f in self.no_borradas:
            avisos.append(f'constructora {c.codigo} "{c.nombre}" quedó sin obras pero tiene {u} usuario(s) y {f} factura(s): revisar a mano')
        for obra, dep in self.basura_conservada:
            avisos.append(f'obra basura "{obra.nombre}" ({obra.codigo_obra}) NO se eliminó: tiene {dep}')
        for p in self.sin_nombre:
            avisos.append(f'obra WP {p.id} "{p.titulo}" no tiene nombre-proyecto en WordPress: se usó el título como nombre')
        if avisos:
            self.stdout.write(self.style.WARNING(f'\nAvisos ({len(avisos)}):'))
            for a in avisos:
                self.stdout.write(f'  ! {a}')


def _dependencias(obra):
    """'3 informes, 1 remisiones' o '' si nada apunta a la obra (recorre todas las relaciones inversas)."""
    partes = []
    for rel in obra._meta.related_objects:
        accessor = rel.get_accessor_name()
        n = getattr(obra, accessor).count()
        if n:
            partes.append(f'{n} {rel.related_model._meta.verbose_name_plural}')
    for m2m in obra._meta.many_to_many:
        n = getattr(obra, m2m.name).count()
        if n:
            partes.append(f'{n} {m2m.verbose_name}')
    return ', '.join(partes)


def _clave_razon(razon):
    return re.sub(r'[^A-Z0-9]', '', (razon or '').upper())


from datetime import datetime  # noqa: E402
_MIN = datetime(1900, 1, 1)
