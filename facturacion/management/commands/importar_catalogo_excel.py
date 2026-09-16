"""
Importa el catálogo de servicios de una sede y los precios por obra desde el
libro BASE DATOS <CIUDAD>.xlsm (hoja "LISTA DE PRECIO").

    python manage.py importar_catalogo_excel "BASE DATOS IBAGUE.xlsm" --ciudad Ibagué --dry-run
    python manage.py importar_catalogo_excel "BASE DATOS IBAGUE.xlsm" --ciudad Ibagué
    python manage.py importar_catalogo_excel "BASE DATOS IBAGUE.xlsm" --ciudad Ibagué --obra 8-1=IBA8-1 --obra 10-2=IBA10-2

Qué hace:
1. Categorías y servicios de la ciudad: crea los que faltan y actualiza
   nombre/norma/categoría de los existentes (busca por ciudad + código).
2. Precios por obra: cada columna de obra del Excel ("8-1") se resuelve a una
   Obra del sistema (ver facturacion/importar_excel.resolver_obra) y se
   escribe PrecioServicio(obra, servicio, precio) para cada celda con precio.
   Las columnas que no se puedan resolver se listan al final y se omiten;
   se asignan a mano con --obra CODIGO_EXCEL=CODIGO_OBRA.

Nunca borra nada. Todo corre en una transacción: con --dry-run se muestra el
resultado completo y no se guarda nada.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from collections import Counter

from facturacion.importar_excel import crear_obra, leer_lista_precios, resolver_obra
from facturacion.models import CategoriaServicio, PrecioServicio, TipoServicio
from users.ciudades import normalizar_ciudad


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = 'Importa catálogo (categorías + servicios) y precios por obra de una sede desde BASE DATOS <CIUDAD>.xlsm.'

    def add_arguments(self, parser):
        parser.add_argument('archivo', help='Ruta al .xlsm / .xlsx')
        parser.add_argument('--ciudad', required=True, help='Sede a la que pertenece el libro (Bucaramanga, Bogotá, Ibagué...)')
        parser.add_argument('--hoja', default='LISTA DE PRECIO')
        parser.add_argument('--dry-run', action='store_true', help='Muestra todo y no guarda nada')
        parser.add_argument('--sin-precios', action='store_true', help='Solo catálogo, no toca precios')
        parser.add_argument('--no-sobrescribir', action='store_true',
                            help='Conserva los precios ya cargados; solo llena los vacíos')
        parser.add_argument('--obra', action='append', default=[], metavar='CODIGO_EXCEL=CODIGO_OBRA',
                            help='Asignación manual de una columna del Excel a una obra del sistema (repetible)')
        parser.add_argument('--detalle', action='store_true', help='Lista cada servicio y precio escrito')
        parser.add_argument('--crear-obras', action='store_true',
                            help='Crea en el sistema las obras del Excel que no existan (bajo su constructora), '
                                 'con nombre "IBA 8-1" y código IBA8-1')

    # ─────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        ciudad = normalizar_ciudad(o['ciudad'])
        overrides = {}
        for par in o['obra']:
            if '=' not in par:
                raise CommandError(f'--obra espera CODIGO_EXCEL=CODIGO_OBRA, recibí "{par}"')
            k, v = par.split('=', 1)
            overrides[k.strip()] = v.strip()

        try:
            lectura = leer_lista_precios(o['archivo'], o['hoja'])
        except (OSError, ValueError) as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{o["archivo"]} -> ciudad {ciudad}: {len(lectura.categorias)} categorías, '
            f'{len(lectura.servicios)} servicios, {len(lectura.obras)} columnas de obra'
        ))
        if lectura.log:
            self.stdout.write(self.style.NOTICE(f'Limpieza del Excel ({len(lectura.log)} decisiones):'))
            for linea in lectura.log:
                self.stdout.write(f'  · {linea}')

        self._verificar_conflictos(ciudad, lectura)

        try:
            with transaction.atomic():
                servicios_db = self._cargar_catalogo(ciudad, lectura, o['detalle'])
                if not o['sin_precios']:
                    self._cargar_precios(ciudad, lectura, servicios_db, overrides, o['no_sobrescribir'], o['detalle'], o['crear_obras'])
                if o['dry_run']:
                    self.stdout.write(self.style.WARNING('\n[DRY-RUN] No se escribió nada en la base de datos.'))
                    raise _Rollback
        except _Rollback:
            return
        self.stdout.write(self.style.SUCCESS('\nImportación guardada.'))

    # ─────────────────────────────────────────────────────────────────
    def _verificar_conflictos(self, ciudad, lectura):
        """nombre único por ciudad: si ya hay un servicio con ese nombre y OTRO código, abortar antes de escribir."""
        codigo_por_nombre = {s.nombre.lower(): s.codigo for s in lectura.servicios}
        conflictos = []
        for s in TipoServicio.objects.filter(ciudad__iexact=ciudad):
            esperado = codigo_por_nombre.get(s.nombre.lower())
            if esperado and esperado != s.codigo:
                conflictos.append(f'  [{s.codigo}] "{s.nombre}"  (en el Excel es [{esperado}])')
        if conflictos:
            raise CommandError(
                f'No se cargó nada. En {ciudad} ya existen servicios con el mismo NOMBRE pero otro código:\n'
                + '\n'.join(conflictos)
                + '\nCorrígelos o elimínalos desde /facturacion/catalogo/ y vuelve a correr el comando.'
            )

    def _cargar_catalogo(self, ciudad, lectura, detalle):
        st = dict(cat_nuevas=0, cat_act=0, srv_nuevos=0, srv_act=0, igual=0)
        categorias = {}
        for codigo, nombre in lectura.categorias:
            cat, creada = CategoriaServicio.objects.get_or_create(
                ciudad=ciudad, codigo=codigo, defaults={'nombre': nombre},
            )
            if creada:
                st['cat_nuevas'] += 1
                self.stdout.write(f'  + Categoría {codigo} - {nombre}')
            elif cat.nombre != nombre:
                self.stdout.write(f'  ~ Categoría {codigo}: "{cat.nombre}" -> "{nombre}"')
                cat.nombre = nombre
                cat.save(update_fields=['nombre'])
                st['cat_act'] += 1
            categorias[codigo] = cat

        servicios_db = {}
        for s in lectura.servicios:
            cat = categorias[s.categoria]
            srv = TipoServicio.objects.filter(ciudad=ciudad, codigo=s.codigo).first()
            if srv is None:
                srv = TipoServicio.objects.create(categoria=cat, codigo=s.codigo, nombre=s.nombre, norma=s.norma)
                st['srv_nuevos'] += 1
                if detalle:
                    self.stdout.write(f'  + [{s.codigo}] {s.nombre}')
            else:
                cambios = []
                if srv.nombre != s.nombre:
                    cambios.append(f'nombre "{srv.nombre}" -> "{s.nombre}"')
                    srv.nombre = s.nombre
                if srv.norma != s.norma:
                    cambios.append(f'norma "{srv.norma}" -> "{s.norma}"')
                    srv.norma = s.norma
                if srv.categoria_id != cat.pk:
                    cambios.append(f'categoría {srv.categoria.codigo} -> {cat.codigo}')
                    srv.categoria = cat
                if cambios:
                    srv.save()
                    st['srv_act'] += 1
                    self.stdout.write(f'  ~ [{s.codigo}] ' + '; '.join(cambios))
                else:
                    st['igual'] += 1
            servicios_db[s.codigo] = srv

        self.stdout.write(self.style.SUCCESS(
            f'Catálogo {ciudad}: categorías {st["cat_nuevas"]} nuevas / {st["cat_act"]} actualizadas; '
            f'servicios {st["srv_nuevos"]} nuevos / {st["srv_act"]} actualizados / {st["igual"]} sin cambios.'
        ))
        return servicios_db

    def _cargar_precios(self, ciudad, lectura, servicios_db, overrides, no_sobrescribir, detalle, crear_obras):
        self.stdout.write(self.style.MIGRATE_HEADING('\nPrecios por obra'))
        columnas_por_empresa = Counter(cod.partition('-')[0] for cod in lectura.obras)
        resueltas, sin_resolver, creadas = {}, [], 0
        for cod_excel in lectura.obras:
            obra, motivo, candidatas = resolver_obra(
                ciudad, cod_excel, lectura, overrides, columnas_por_empresa[cod_excel.partition('-')[0]],
            )
            if obra is None and crear_obras and candidatas is not None:
                nueva = crear_obra(ciudad, cod_excel, lectura)
                if nueva is not None:
                    obra, motivo, creadas = nueva, f'obra CREADA (--crear-obras) bajo {nueva.constructora.nombre}', creadas + 1
            n_precios = sum(1 for s in lectura.servicios if cod_excel in s.precios)
            etiqueta = lectura.nombres_obras.get(cod_excel, '')
            if obra:
                resueltas[cod_excel] = (obra, motivo, n_precios, etiqueta)
            else:
                sin_resolver.append((cod_excel, etiqueta, n_precios, motivo, candidatas))

        # Una obra del sistema solo puede recibir UNA columna del Excel: si dos
        # columnas caen en la misma obra, se conserva la más confiable y las
        # demás pasan a "sin resolver" (se pisarían los precios entre sí).
        por_obra = {}
        for cod_excel, (obra, motivo, n, etiqueta) in resueltas.items():
            por_obra.setdefault(obra.pk, []).append(cod_excel)
        for pk, cods in por_obra.items():
            if len(cods) < 2:
                continue
            prioridad = lambda c: 0 if resueltas[c][1].startswith(('--obra', 'código de obra', 'nombre de obra')) else 1
            cods_orden = sorted(cods, key=prioridad)
            for cod_excel in cods_orden[1:]:
                obra, motivo, n, etiqueta = resueltas.pop(cod_excel)
                sin_resolver.append((cod_excel, etiqueta, n,
                                     f'la obra {obra.codigo_obra} ya quedó asignada a la columna {cods_orden[0]} '
                                     f'(use --crear-obras o --obra {cod_excel}=CODIGO_OBRA)', []))

        for cod_excel in lectura.obras:
            if cod_excel in resueltas:
                obra, motivo, n, etiqueta = resueltas[cod_excel]
                self.stdout.write(f'  ✓ {cod_excel:>6} {etiqueta[:28]:28} -> {obra.codigo_obra} · {obra.nombre[:40]}  ({n} precios; {motivo})')
        if creadas:
            self.stdout.write(self.style.NOTICE(f'  {creadas} obra(s) creadas con --crear-obras'))
        resueltas = {k: v[0] for k, v in resueltas.items()}

        creados = actualizados = iguales = conservados = 0
        for s in lectura.servicios:
            srv = servicios_db[s.codigo]
            for cod_excel, precio in s.precios.items():
                obra = resueltas.get(cod_excel)
                if obra is None:
                    continue
                ps, creado = PrecioServicio.objects.get_or_create(
                    obra=obra, tipo_servicio=srv, defaults={'precio': precio},
                )
                if creado:
                    creados += 1
                elif ps.precio == precio:
                    iguales += 1
                elif no_sobrescribir and ps.precio is not None:
                    conservados += 1
                else:
                    if detalle:
                        self.stdout.write(f'  ~ {obra.codigo_obra} [{s.codigo}] {ps.precio} -> {precio}')
                    ps.precio = precio
                    ps.save(update_fields=['precio'])
                    actualizados += 1

        self.stdout.write(self.style.SUCCESS(
            f'Precios: {creados} nuevos, {actualizados} actualizados, {iguales} sin cambios'
            + (f', {conservados} conservados (--no-sobrescribir)' if conservados else '')
            + f' en {len(resueltas)} obras.'
        ))
        if sin_resolver:
            self.stdout.write(self.style.WARNING(f'\n{len(sin_resolver)} columnas de obra NO se pudieron asignar (sus precios se omitieron):'))
            for cod_excel, etiqueta, n, motivo, candidatas in sin_resolver:
                self.stdout.write(f'  ✗ {cod_excel:>6} {etiqueta[:28]:28} {n:>3} precios · {motivo}')
                for o in candidatas[:6]:
                    self.stdout.write(f'        candidata: --obra {cod_excel}={o.codigo_obra}   ({o.nombre[:50]})')
            self.stdout.write('  Asigna con --obra CODIGO_EXCEL=CODIGO_OBRA y vuelve a correr (es idempotente).')
