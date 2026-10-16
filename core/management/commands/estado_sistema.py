"""
Diagnóstico del estado del sistema en la base de datos actual (pensado para
producción). SOLO LECTURA: todo corre dentro de una transacción que en
PostgreSQL se declara READ ONLY y que además se revierte al terminar.

    python manage.py estado_sistema                       # todas las secciones
    python manage.py estado_sistema --seccion obras --detalle
    python manage.py estado_sistema --verificar-s3        # ¿los PDF son públicos?
    python manage.py estado_sistema --verificar-archivos 50

Secciones: sistema, usuarios, constructoras, obras, informes, remisiones,
ensayos, calidad, facturacion, s3.

Cada hallazgo sale marcado como [OK], [AVISO] o [RIESGO]; al final hay un
resumen con todos los avisos y riesgos.
"""

import re
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractYear
from django.utils import timezone

from users.ciudades import CIUDADES

SECCIONES = ('sistema', 'usuarios', 'constructoras', 'obras', 'informes',
             'remisiones', 'ensayos', 'calidad', 'facturacion', 's3')

_PREF = '|'.join(CIUDADES.values())
# Constructora: BUC46, IBA8, BOG3B (código reutilizado), BUC0-12, BUC0-12B (clientes varios)
RE_CONSTRUCTORA = re.compile(rf'^({_PREF})(\d+|0-\d+)[A-Z]?$')
# Obra: BUC46-9, IBA8-1, BUC0-12-1 (opcional letra final)
RE_OBRA = re.compile(rf'^({_PREF})(\d+[A-Z]?|0-\d+[A-Z]?)-\d+[A-Z]?$')


class Command(BaseCommand):
    help = 'Diagnóstico de solo lectura del estado de la base de datos (producción).'

    def add_arguments(self, parser):
        parser.add_argument('--seccion', action='append', choices=SECCIONES,
                            help='Solo estas secciones (se puede repetir)')
        parser.add_argument('--detalle', action='store_true',
                            help='Lista ejemplos de cada hallazgo')
        parser.add_argument('--limite', type=int, default=10,
                            help='Máximo de ejemplos por hallazgo con --detalle (default 10)')
        parser.add_argument('--verificar-s3', action='store_true',
                            help='Pide SIN credenciales un archivo de muestra para saber si el bucket es público')
        parser.add_argument('--verificar-archivos', type=int, default=0, metavar='N',
                            help='Comprueba que existan en el storage los archivos de N informes al azar')

    # ── salida ────────────────────────────────────────────────────────────
    def titulo(self, texto):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n══ {texto} ══'))

    def dato(self, etiqueta, valor):
        self.stdout.write(f'  {etiqueta}: {valor}')

    def ok(self, texto):
        self.stdout.write(self.style.SUCCESS(f'  [OK] {texto}'))

    def aviso(self, texto, ejemplos=None):
        self.hallazgos.append(('AVISO', self.seccion_actual, texto))
        self.stdout.write(self.style.WARNING(f'  [AVISO] {texto}'))
        self._ejemplos(ejemplos)

    def riesgo(self, texto, ejemplos=None):
        self.hallazgos.append(('RIESGO', self.seccion_actual, texto))
        self.stdout.write(self.style.ERROR(f'  [RIESGO] {texto}'))
        self._ejemplos(ejemplos)

    def _ejemplos(self, ejemplos):
        if not (self.detalle and ejemplos):
            return
        for e in list(ejemplos)[:self.limite]:
            self.stdout.write(f'      - {e}')

    def revisar(self, cantidad, texto, ejemplos=None, grave=False):
        """OK si cantidad == 0; si no, AVISO (o RIESGO si grave)."""
        if not cantidad:
            self.ok(texto.format(n=0))
        elif grave:
            self.riesgo(texto.format(n=cantidad), ejemplos)
        else:
            self.aviso(texto.format(n=cantidad), ejemplos)

    @staticmethod
    def conteo(qs, campo):
        filas = qs.values(campo).annotate(n=Count('pk')).order_by(campo).values_list(campo, 'n')
        return ', '.join(f'{k or "(vacío)"}={v}' for k, v in filas) or '—'

    # ── principal ─────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        self.detalle = o['detalle']
        self.limite = o['limite']
        self.verificar_archivos = o['verificar_archivos']
        self.hallazgos = []
        self.hoy = timezone.localdate()
        secciones = o['seccion'] or [s for s in SECCIONES if s != 's3' or o['verificar_s3']]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Estado del sistema Geolab · {timezone.localtime():%Y-%m-%d %H:%M} · '
            f'base "{connection.settings_dict["NAME"]}" en {connection.settings_dict.get("HOST") or "local"}'))
        self.stdout.write('(solo lectura: no se modifica nada)')

        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as c:
                    c.execute('SET TRANSACTION READ ONLY')
            for nombre in secciones:
                self.seccion_actual = nombre
                try:
                    # savepoint por sección: si una falla, las demás siguen
                    with transaction.atomic():
                        getattr(self, f'sec_{nombre}')()
                except Exception as exc:  # noqa: BLE001 - es un diagnóstico
                    self.riesgo(f'La sección falló: {type(exc).__name__}: {exc}')
            transaction.set_rollback(True)

        self.resumen()

    def resumen(self):
        self.titulo('RESUMEN')
        riesgos = [h for h in self.hallazgos if h[0] == 'RIESGO']
        avisos = [h for h in self.hallazgos if h[0] == 'AVISO']
        if not self.hallazgos:
            self.stdout.write(self.style.SUCCESS('  Sin avisos ni riesgos.'))
            return
        for tipo, seccion, texto in riesgos + avisos:
            estilo = self.style.ERROR if tipo == 'RIESGO' else self.style.WARNING
            self.stdout.write(estilo(f'  [{tipo}] {seccion}: {texto}'))
        self.stdout.write(f'\n  Total: {len(riesgos)} riesgos, {len(avisos)} avisos.')

    # ── secciones ─────────────────────────────────────────────────────────
    def sec_sistema(self):
        import django
        self.titulo('Sistema')
        self.dato('Django', django.get_version())
        self.dato('DEBUG', settings.DEBUG)
        self.dato('Zona horaria', f'{settings.TIME_ZONE} (hoy local = {self.hoy})')
        storage = settings.STORAGES.get('default', {}).get('BACKEND', '?') if hasattr(settings, 'STORAGES') else '?'
        self.dato('Storage de archivos', storage)
        self.dato('MEDIA_URL', settings.MEDIA_URL)
        if settings.DEBUG:
            self.riesgo('DEBUG=True en este entorno (en producción debe ser False)')

        executor = MigrationExecutor(connection)
        pendientes = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.revisar(len(pendientes), '{n} migraciones sin aplicar',
                     [f'{m.app_label}.{m.name}' for m, _ in pendientes], grave=True)

    def sec_usuarios(self):
        from users.models import ClienteExterno, UsuarioBase
        self.titulo('Usuarios')
        U = UsuarioBase.objects
        self.dato('Total', f'{U.count()} (activos {U.filter(is_active=True).count()})')
        self.dato('Superusuarios', ', '.join(U.filter(is_superuser=True).values_list('username', flat=True)) or '—')
        geolab = U.filter(es_geolab=True)
        self.dato('Geolab por área', self.conteo(geolab.filter(perfil_geolab__isnull=False), 'perfil_geolab__area'))
        clientes = U.filter(es_cliente=True)
        self.dato('Clientes por rol', self.conteo(clientes.filter(perfil_cliente__isnull=False), 'perfil_cliente__rol'))

        sin_perfil = geolab.filter(perfil_geolab__isnull=True, is_active=True)
        self.revisar(sin_perfil.count(),
                     '{n} usuarios Geolab activos SIN perfil FuncionarioGeolab (quedan como admin total por el fallback de es_admin_geolab)',
                     sin_perfil.values_list('username', flat=True), grave=True)
        cli_sin = clientes.filter(perfil_cliente__isnull=True, is_active=True)
        self.revisar(cli_sin.count(), '{n} clientes activos sin perfil ClienteExterno (dan error 500 al entrar)',
                     cli_sin.values_list('username', flat=True))
        ambos = U.filter(es_geolab=True, es_cliente=True)
        self.revisar(ambos.count(), '{n} usuarios marcados como Geolab Y cliente a la vez',
                     ambos.values_list('username', flat=True), grave=True)
        ninguno = U.filter(es_geolab=False, es_cliente=False, is_superuser=False, is_active=True)
        self.revisar(ninguno.count(), '{n} usuarios activos sin tipo (ni Geolab ni cliente)',
                     ninguno.values_list('username', flat=True))
        tecnicos = geolab.filter(perfil_geolab__area='tecnico', is_active=True).count()
        if tecnicos:
            self.aviso(f'{tecnicos} técnicos activos: hoy pueden crear usuarios/empresas/obras '
                       '(las vistas revisan es_geolab, no es_admin_geolab)')

        # Residentes: obras asignadas y que sean de su propia empresa
        residentes = ClienteExterno.objects.filter(rol='residente', user__is_active=True)
        sin_obras = residentes.annotate(n=Count('obras_asignadas')).filter(n=0)
        self.revisar(sin_obras.count(), '{n} residentes activos sin obras asignadas (no ven nada)',
                     sin_obras.values_list('user__username', flat=True))
        cruzados = sorted({
            f'{p.user.username} ({p.empresa.codigo}) → {o.codigo_obra}'
            for p in residentes.select_related('user', 'empresa').prefetch_related('obras_asignadas')
            for o in p.obras_asignadas.all() if o.constructora_id != p.empresa_id
        })
        self.revisar(len(cruzados), '{n} asignaciones de residentes a obras de OTRA empresa',
                     cruzados, grave=True)

        limite = timezone.now() - timedelta(days=180)
        dormidos = U.filter(is_active=True).filter(Q(last_login__lt=limite) | Q(last_login__isnull=True))
        self.dato('Activos sin entrar hace 6+ meses (o nunca)', dormidos.count())

    def sec_constructoras(self):
        from users.models import Constructora
        self.titulo('Constructoras')
        C = Constructora.objects
        self.dato('Total', C.count())
        self.dato('Por ciudad', self.conteo(C, 'ciudad'))

        sin_ciudad = C.filter(Q(ciudad__isnull=True) | Q(ciudad=''))
        self.revisar(sin_ciudad.count(), '{n} sin ciudad (no aparecen en Facturación)',
                     [str(c) for c in sin_ciudad])
        no_canon = C.exclude(ciudad__in=list(CIUDADES)).exclude(Q(ciudad__isnull=True) | Q(ciudad=''))
        self.revisar(no_canon.count(), '{n} con ciudad fuera de las sedes (Bucaramanga/Bogotá/Ibagué)',
                     [f'{c} → {c.ciudad}' for c in no_canon])

        todas = list(C.annotate(n_obras=Count('obras'), n_usuarios=Count('usuarios', distinct=True)))
        malas = [c for c in todas if not RE_CONSTRUCTORA.match(c.codigo or '')]
        self.revisar(len(malas), '{n} con código fuera de la convención (BUC46, BUC0-12, BOG3B…)',
                     [str(c) for c in malas])
        pref_ciudad = [c for c in todas if c.ciudad in CIUDADES and RE_CONSTRUCTORA.match(c.codigo or '')
                       and not c.codigo.startswith(CIUDADES[c.ciudad])]
        self.revisar(len(pref_ciudad), '{n} cuyo prefijo de código no coincide con su ciudad',
                     [f'{c} en {c.ciudad}' for c in pref_ciudad])
        nombre_codigo = [c for c in todas if (c.nombre or '').replace(' ', '').upper() == (c.codigo or '').upper()]
        self.revisar(len(nombre_codigo), '{n} cuyo nombre es el código (herencia de migrar_geolab)',
                     [str(c) for c in nombre_codigo])
        vacias = [c for c in todas if c.n_obras == 0]
        self.revisar(len(vacias), '{n} sin obras', [f'{c} ({c.n_usuarios} usuarios)' for c in vacias])

        por_nombre = Counter(re.sub(r'[^A-Z0-9]', '', (c.nombre or '').upper()) for c in todas)
        repetidas = [c for c in todas if por_nombre[re.sub(r'[^A-Z0-9]', '', (c.nombre or '').upper())] > 1]
        self.revisar(len(repetidas), '{n} comparten razón social con otra constructora (¿duplicadas?)',
                     sorted(str(c) for c in repetidas))
        sufijo = [c for c in todas if re.search(r'\d[B-Z]$', c.codigo or '')]
        if sufijo:
            self.aviso(f'{len(sufijo)} con sufijo B/C… (código reutilizado en WordPress: corregir allá)',
                       [str(c) for c in sufijo])

    def sec_obras(self):
        from core.models import Obra
        self.titulo('Obras')
        O = Obra.objects.select_related('constructora')
        self.dato('Total', O.count())
        self.dato('Por ciudad', self.conteo(O, 'constructora__ciudad'))
        self.dato('Con id de WordPress', O.filter(id_wp_original__isnull=False).count())

        obras = list(O)
        malas = [o for o in obras if not RE_OBRA.match(o.codigo_obra or '')]
        self.revisar(len(malas), '{n} con código fuera de la convención (BUC46-9, BUC0-12-1…)',
                     [f'{o.codigo_obra} · {o.nombre} ({o.constructora.codigo})' for o in malas])
        ajenas = [o for o in obras if RE_OBRA.match(o.codigo_obra or '')
                  and not o.codigo_obra.startswith(f'{o.constructora.codigo}-')]
        self.revisar(len(ajenas), '{n} cuyo código no empieza por el de su constructora',
                     [f'{o.codigo_obra} en {o.constructora.codigo}' for o in ajenas])
        con_id = [o for o in obras if o.id_wp_original and (o.codigo_obra or '').endswith(f'-{o.id_wp_original}')]
        self.revisar(len(con_id), '{n} con código "<cliente>-<id WordPress>" (formato viejo de migrar_geolab)',
                     [f'{o.codigo_obra} · {o.nombre}' for o in con_id])
        sin_nombre = [o for o in obras if not (o.nombre or '').strip()
                      or (o.nombre or '').replace(' ', '').upper() == (o.codigo_obra or '').upper()
                      or RE_OBRA.match((o.nombre or '').replace(' ', '').upper())]
        self.revisar(len(sin_nombre), '{n} cuyo nombre es un código o está vacío (falta el nombre real del proyecto)',
                     [f'{o.codigo_obra} · "{o.nombre}"' for o in sin_nombre])
        repetidos = [c for c, n in Counter(o.codigo_obra for o in obras).items() if n > 1]
        self.revisar(len(repetidos), '{n} códigos de obra repetidos', repetidos)
        sin_contacto = sum(1 for o in obras if not (o.direccion or o.telefono or o.contacto or o.celular))
        self.dato('Sin dirección/teléfono/contacto', sin_contacto)

    def sec_informes(self):
        from core.models import Informe
        self.titulo('Informes (PDF de WordPress / cargados)')
        I = Informe.objects
        total = I.count()
        con_archivo = I.exclude(Q(archivo='') | Q(archivo__isnull=True))
        pendientes = I.filter(Q(archivo='') | Q(archivo__isnull=True)).exclude(
            Q(url_archivo_original__isnull=True) | Q(url_archivo_original=''))
        huerfanos = I.filter(Q(archivo='') | Q(archivo__isnull=True)).filter(
            Q(url_archivo_original__isnull=True) | Q(url_archivo_original=''))
        self.dato('Total', total)
        self.dato('Con archivo', con_archivo.count())
        self.dato('Último', I.order_by('-fecha_creacion').values_list('fecha_creacion', flat=True).first())
        self.dato('Por año', ', '.join(f'{r["anio"]}={r["n"]}' for r in
                  I.exclude(fecha_creacion__isnull=True).values(anio=ExtractYear('fecha_creacion'))
                  .annotate(n=Count('pk')).order_by('anio')))
        self.revisar(pendientes.count(), '{n} sin PDF descargado todavía (correr descargar_archivos)',
                     pendientes.values_list('titulo', flat=True))
        self.revisar(huerfanos.count(), '{n} sin archivo ni URL de origen (no se pueden recuperar)',
                     huerfanos.values_list('titulo', flat=True))

        if self.verificar_archivos:
            from django.core.files.storage import default_storage
            muestra = list(con_archivo.order_by('?')[:self.verificar_archivos])
            faltan = [inf.archivo.name for inf in muestra if not default_storage.exists(inf.archivo.name)]
            self.revisar(len(faltan), f'{{n}} de {len(muestra)} archivos de muestra NO existen en el storage',
                         faltan, grave=True)

    def sec_remisiones(self):
        from solicitudes.models import Muestra, RemisionMuestras
        self.titulo('Remisiones y muestras')
        R = RemisionMuestras.objects
        self.dato('Total', R.count())
        self.dato('Por estado', self.conteo(R, 'estado'))
        ult = R.order_by('-fecha_creacion').first()
        self.dato('Última', f'{ult.fecha_creacion:%Y-%m-%d} · {ult.obra}' if ult else '—')

        token_vivo = R.exclude(Q(token_acceso__isnull=True) | Q(token_acceso='')).exclude(estado='completada')
        self.revisar(token_vivo.count(),
                     '{n} remisiones con token público aún respondible (flujo deprecado /remision/<token>/)',
                     [f'#{r.pk} OT {r.orden_trabajo} · {r.obra}' for r in token_vivo], grave=True)

        con_hoja = R.filter(estado='completada', hoja_trabajo__isnull=True).filter(
            muestras__in=Muestra.objects.exclude(tipo_muestra__in=Muestra.TIPOS_SIN_HOJA)).distinct()
        self.revisar(con_hoja.count(), '{n} remisiones completadas con concreto pero SIN hoja de trabajo (correr sincronizar_hojas)',
                     [f'#{r.pk} OT {r.orden_trabajo} · {r.obra}' for r in con_hoja], grave=True)

        M = Muestra.objects
        self.dato('Muestras por tipo', self.conteo(M, 'tipo_muestra'))
        self.dato('Muestras por geometría', self.conteo(M, 'geometria'))
        sin_dim = M.exclude(tipo_muestra__in=Muestra.TIPOS_SIN_HOJA).filter(
            Q(dimension_especimen__isnull=True) | Q(dimension_especimen=''))
        self.revisar(sin_dim.count(), '{n} muestras de concreto/otros sin dimensión (se calculan sin corrección de instrumento)',
                     [f'muestra {m.pk} · remisión {m.remision_id}' for m in sin_dim])
        acero_mal = M.exclude(tipo_muestra__in=Muestra.TIPOS_SIN_HOJA).filter(geometria='acero')
        self.revisar(acero_mal.count(), '{n} muestras NO acero con dimensión de acero (geometría incoherente)',
                     [f'muestra {m.pk} · {m.tipo_muestra} {m.dimension_especimen}' for m in acero_mal], grave=True)
        multiples = M.filter(cantidad__gt=1).exclude(tipo_muestra__in=Muestra.TIPOS_SIN_HOJA).count()
        if multiples:
            self.aviso(f'{multiples} muestras con cantidad > 1: cada una tiene UN solo resultado (confirmar con el laboratorio)')

    def sec_ensayos(self):
        from ensayos.models import ConsecutivoInforme, HojaTrabajo, InformeEnsayo, ResultadoMuestra
        self.titulo('Ensayos')
        self.dato('Hojas por estado', self.conteo(HojaTrabajo.objects, 'estado'))
        Rm = ResultadoMuestra.objects
        self.dato('Resultados por estado', self.conteo(Rm, 'estado'))

        pendientes = Rm.filter(estado='pendiente').values_list(
            'pk', 'muestra__fecha_toma', 'muestra__edad_ensayo_dias', 'hoja_trabajo__remision__obra__codigo_obra')
        hoy, vencidos = [], []
        for pk, toma, edad, obra in pendientes:
            if not (toma and edad is not None):
                continue
            falla = toma + timedelta(days=edad)
            if falla == self.hoy:
                hoy.append(obra)
            elif falla < self.hoy:
                vencidos.append((falla, obra, pk))
        self.dato('Pendientes para HOY', len(hoy))
        self.revisar(len(vencidos), '{n} resultados pendientes con fecha de falla vencida',
                     [f'{f} · {o} (resultado {pk})' for f, o, pk in sorted(vencidos)])

        vigas = Rm.filter(estado='completado', muestra__geometria='prisma').filter(
            Q(luz_entre_apoyos__isnull=True) | Q(formula_flexion=''))
        self.revisar(vigas.count(), '{n} vigas "completadas" sin luz entre apoyos o fórmula (sin módulo de rotura)',
                     [f'resultado {r.pk}' for r in vigas], grave=True)
        con_fallido = HojaTrabajo.objects.filter(resultados__estado='fallido').exclude(estado='completada').distinct()
        self.revisar(con_fallido.count(), '{n} hojas con muestras descartadas que nunca podrán cerrarse',
                     [f'hoja {h.pk} · {h.remision.obra}' for h in con_fallido])

        anio = self.hoy.year
        cons = ConsecutivoInforme.objects.filter(anio=anio).first()
        emitidos = InformeEnsayo.objects.filter(numero_informe__contains=str(anio)).count()
        self.dato(f'Informes de ensayo {anio}', f'{emitidos} emitidos · consecutivo en {cons.ultimo if cons else "—"}')
        if cons and cons.ultimo > emitidos:
            self.aviso(f'El consecutivo {anio} va en {cons.ultimo} pero hay {emitidos} informes: '
                       f'{cons.ultimo - emitidos} números saltados (regeneraciones) o el contador arrancó en otro número')

    def sec_calidad(self):
        from calidad.models import AccesoAreaUsuario, AccesoCarpetaUsuario, AreaCalidad, Carpeta, Documento
        self.titulo('Calidad (SGC)')
        self.dato('Áreas', AreaCalidad.objects.count())
        self.dato('Carpetas', Carpeta.objects.count())
        bytes_total = Documento.objects.aggregate(t=Sum('tamano_bytes'))['t'] or 0
        self.dato('Documentos', f'{Documento.objects.count()} ({bytes_total / 1024 / 1024:.1f} MB)')
        self.dato('Por tipo', self.conteo(Documento.objects, 'tipo_archivo'))
        self.dato('Accesos por área / por carpeta',
                  f'{AccesoAreaUsuario.objects.count()} / {AccesoCarpetaUsuario.objects.count()}')
        if AreaCalidad.objects.count() != 8:
            self.aviso(f'Hay {AreaCalidad.objects.count()} áreas (se esperaban 8; correr importar_calidad)')
        peligrosos = Documento.objects.filter(
            Q(archivo__iendswith='.html') | Q(archivo__iendswith='.htm') | Q(archivo__iendswith='.svg')
            | Q(archivo__iendswith='.js') | Q(archivo__iendswith='.exe'))
        self.revisar(peligrosos.count(), '{n} documentos con extensión ejecutable/HTML (posible XSS)',
                     peligrosos.values_list('archivo', flat=True), grave=True)

    def sec_facturacion(self):
        from core.models import Obra
        from facturacion.models import (CategoriaServicio, Factura, Impuesto, PrecioServicio,
                                        RegistroServicio, TipoServicio)
        self.titulo('Facturación')
        imp = ', '.join(f'{i.nombre} {i.porcentaje}%' for i in Impuesto.objects.filter(activo=True))
        self.dato('Impuestos activos', imp or '—')
        if not imp:
            self.aviso('No hay impuestos activos (las facturas saldrían sin IVA)')

        ciudades = sorted(set(CategoriaServicio.objects.values_list('ciudad', flat=True))
                          | set(Obra.objects.exclude(constructora__ciudad__isnull=True)
                                .values_list('constructora__ciudad', flat=True).distinct()) - {''})
        for ciudad in ciudades:
            obras = Obra.objects.filter(constructora__ciudad__iexact=ciudad)
            precios = PrecioServicio.objects.filter(obra__in=obras)
            regs = RegistroServicio.objects.filter(obra__in=obras)
            facts = Factura.objects.filter(constructora__ciudad__iexact=ciudad)
            self.stdout.write(f'  ── {ciudad}')
            self.dato('    Catálogo', f'{CategoriaServicio.objects.filter(ciudad=ciudad).count()} categorías, '
                                       f'{TipoServicio.objects.filter(ciudad=ciudad).count()} servicios')
            self.dato('    Obras con precios', f'{obras.filter(lista_de_precios__isnull=False).distinct().count()} '
                                               f'de {obras.count()} ({precios.count()} precios)')
            self.dato('    Registros', f'{regs.count()} · sin facturar {regs.filter(factura__isnull=True).count()} '
                                       f'(diferidos {regs.filter(factura__isnull=True, facturar_despues=True).count()})')
            por_estado = facts.values('estado').annotate(n=Count('pk'), t=Sum('total')).order_by('estado')
            self.dato('    Facturas', ', '.join(f'{f["estado"]}={f["n"]} (${f["t"] or 0:,.0f})' for f in por_estado) or '—')
            if obras.exists() and not TipoServicio.objects.filter(ciudad=ciudad).exists():
                self.aviso(f'{ciudad}: tiene obras pero no tiene catálogo de servicios')

        cruzados = PrecioServicio.objects.exclude(tipo_servicio__ciudad=F('obra__constructora__ciudad'))
        self.revisar(cruzados.count(), '{n} precios de obra con un servicio de OTRA ciudad',
                     [f'{p.obra} · {p.tipo_servicio}' for p in cruzados.select_related('obra', 'tipo_servicio')], grave=True)
        en_cero = PrecioServicio.objects.filter(precio__lte=0).count()
        self.revisar(en_cero, '{n} precios por obra en $0')
        reg_cero = RegistroServicio.objects.filter(precio_unitario_congelado__lte=0)
        self.revisar(reg_cero.count(), '{n} registros con precio congelado en $0',
                     [f'registro {r.pk} · {r.obra_id}' for r in reg_cero])
        vacias = Factura.objects.exclude(estado='ANULADA').filter(total__gt=0).annotate(
            n=Count('registros')).filter(n=0)
        self.revisar(vacias.count(), '{n} facturas con total > 0 y sin registros (doble envío al finalizar)',
                     [f'factura {f.pk} · {f.constructora} · ${f.total:,.0f}' for f in vacias], grave=True)
        descuadre = []
        for f in Factura.objects.exclude(estado='ANULADA').annotate(s=Sum('registros__subtotal')):
            if f.s is not None and f.s != f.subtotal:
                descuadre.append(f'factura {f.pk}: subtotal {f.subtotal} vs registros {f.s}')
        self.revisar(len(descuadre), '{n} facturas cuyo subtotal no cuadra con sus registros', descuadre, grave=True)

    def sec_s3(self):
        import requests
        from core.models import Informe
        self.titulo('S3: ¿los archivos son públicos?')
        inf = Informe.objects.exclude(Q(archivo='') | Q(archivo__isnull=True)).order_by('-pk').first()
        if not inf:
            self.aviso('No hay informes con archivo para probar')
            return
        url = inf.archivo.url
        firmada = 'X-Amz-Signature' in url or 'Signature=' in url
        self.dato('URL generada', ('firmada (vence)' if firmada else 'SIN firma (permanente)'))
        sin_firma = url.split('?')[0]
        try:
            r = requests.get(sin_firma, headers={'Range': 'bytes=0-0'}, timeout=15, allow_redirects=False)
        except requests.RequestException as exc:
            self.aviso(f'No se pudo consultar el archivo: {exc}')
            return
        self.dato('Respuesta sin credenciales', r.status_code)
        if r.status_code in (200, 206):
            self.riesgo('Un informe se descarga SIN credenciales ni firma: el bucket/prefijo es público '
                        '(cualquiera con la URL baja PDF de clientes)')
        elif r.status_code == 403:
            self.ok('El bucket rechaza descargas sin firma (privado)')
            if not firmada:
                self.riesgo('Pero el portal genera URLs sin firma: los enlaces a archivos deberían estar fallando')
        else:
            self.aviso(f'Respuesta inesperada {r.status_code} (¿settings de S3 o archivo inexistente?)')
