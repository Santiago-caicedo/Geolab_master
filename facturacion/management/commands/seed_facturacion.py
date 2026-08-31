"""
Datos sinteticos para el modulo de facturacion.

Crea catalogo (categorias + servicios), IVA, listas de precios por obra,
registros de servicio repartidos en los ultimos meses y algunas facturas
ya emitidas (con sus registros vinculados).

    python manage.py seed_facturacion
    python manage.py seed_facturacion --meses 12 --obras 5 --limpiar
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Obra
from users.models import Constructora
from facturacion.models import (
    CategoriaServicio, TipoServicio, PrecioServicio,
    Impuesto, RegistroServicio, Factura,
)

# (codigo_categoria, nombre_categoria, [(codigo_servicio, nombre, norma, precio_base)])
CATALOGO = [
    ('1', 'CONCRETOS', [
        ('1.1', 'Toma de cilindros de concreto en obra', 'NTC 550', 18000),
        ('1.2', 'Ensayo de compresion de cilindros', 'NTC 673', 22000),
        ('1.3', 'Ensayo de compresion de cubos de mortero', 'NTC 220', 25000),
        ('1.4', 'Ensayo de flexion de vigas', 'NTC 2871', 85000),
        ('1.5', 'Asentamiento del concreto (slump)', 'NTC 396', 15000),
        ('1.6', 'Extraccion de nucleos de concreto', 'NTC 3658', 145000),
    ]),
    ('2', 'SUELOS', [
        ('2.1', 'Densidad de campo cono y arena', 'INV E-161', 65000),
        ('2.2', 'Proctor modificado', 'INV E-142', 210000),
        ('2.3', 'CBR de laboratorio', 'INV E-148', 340000),
        ('2.4', 'Limites de Atterberg', 'INV E-125', 78000),
        ('2.5', 'Granulometria por tamizado', 'INV E-123', 72000),
        ('2.6', 'Humedad natural', 'INV E-122', 28000),
    ]),
    ('3', 'ASFALTOS', [
        ('3.1', 'Extraccion de asfalto por centrifuga', 'INV E-732', 195000),
        ('3.2', 'Estabilidad y flujo Marshall', 'INV E-748', 260000),
        ('3.3', 'Densidad de mezcla asfaltica', 'INV E-733', 110000),
    ]),
    ('4', 'ACEROS', [
        ('4.1', 'Ensayo de traccion en varilla', 'NTC 2289', 95000),
        ('4.2', 'Ensayo de doblado en varilla', 'NTC 2289', 68000),
        ('4.3', 'Ensayo de traccion en malla electrosoldada', 'NTC 5806', 105000),
    ]),
    ('5', 'AGREGADOS', [
        ('5.1', 'Desgaste en maquina de Los Angeles', 'INV E-218', 185000),
        ('5.2', 'Equivalente de arena', 'INV E-133', 88000),
        ('5.3', 'Masa unitaria de agregados', 'NTC 92', 62000),
    ]),
    ('6', 'MAMPOSTERIA', [
        ('6.1', 'Compresion de bloques de concreto', 'NTC 4076', 42000),
        ('6.2', 'Compresion de muretes', 'NTC 3495', 130000),
    ]),
    ('7', 'TRANSPORTE', [
        ('7.1', 'Transporte de muestras area urbana', '', 55000),
        ('7.2', 'Transporte de muestras fuera del casco urbano', '', 120000),
        ('7.3', 'Desplazamiento de tecnico a obra', '', 90000),
    ]),
]

CONSTRUCTORAS_DEMO = [
    ('Constructora Demo Andina S.A.S', 'DEMO-01', '900123456-1', 'Bucaramanga'),
    ('Edificaciones Demo del Norte Ltda', 'DEMO-02', '900654321-7', 'Bogota'),
]

OBRAS_DEMO = [
    'Torre Demo Alameda', 'Conjunto Demo Portal', 'Via Demo Km 12',
    'Bodegas Demo Zona Franca', 'Urbanizacion Demo Miraflores',
]


class Command(BaseCommand):
    help = 'Carga datos sinteticos en el modulo de facturacion.'

    def add_arguments(self, parser):
        parser.add_argument('--meses', type=int, default=8,
                            help='Meses hacia atras a poblar (default: 8)')
        parser.add_argument('--obras', type=int, default=5,
                            help='Maximo de obras a usar/crear (default: 5)')
        parser.add_argument('--registros', type=int, default=220,
                            help='Registros de servicio a crear (default: 220)')
        parser.add_argument('--limpiar', action='store_true',
                            help='Borra facturas, registros, precios y catalogo antes de cargar')
        parser.add_argument('--semilla', type=int, default=42,
                            help='Semilla del random para resultados reproducibles')

    @transaction.atomic
    def handle(self, *args, **opts):
        random.seed(opts['semilla'])
        self.hoy = timezone.now().date()

        if opts['limpiar']:
            self._limpiar()

        iva = self._crear_iva()
        servicios = self._crear_catalogo()
        obras = self._obtener_obras(opts['obras'])
        self._crear_precios(obras, servicios)
        registros = self._crear_registros(obras, servicios, opts['meses'], opts['registros'])
        facturas = self._crear_facturas(obras, iva, opts['meses'])

        self.stdout.write(self.style.SUCCESS(
            f"\nListo:\n"
            f"  Categorias: {CategoriaServicio.objects.count()}\n"
            f"  Servicios:  {TipoServicio.objects.count()}\n"
            f"  Obras con precios: {len(obras)}\n"
            f"  Precios cargados: {PrecioServicio.objects.exclude(precio=None).count()}\n"
            f"  Registros creados: {registros}\n"
            f"  Facturas creadas: {facturas} "
            f"(pendientes de facturar: {RegistroServicio.objects.filter(factura__isnull=True).count()})\n"
        ))

    # ── pasos ────────────────────────────────────────────────────────────────

    def _limpiar(self):
        self.stdout.write('Limpiando datos de facturacion...')
        Factura.objects.all().delete()
        RegistroServicio.objects.all().delete()
        PrecioServicio.objects.all().delete()
        TipoServicio.objects.all().delete()
        CategoriaServicio.objects.all().delete()

    def _crear_iva(self):
        iva, creado = Impuesto.objects.get_or_create(
            nombre='IVA', defaults={'porcentaje': Decimal('19.00'), 'activo': True}
        )
        if not creado and not iva.activo:
            iva.activo = True
            iva.save(update_fields=['activo'])
        self.stdout.write(f'IVA: {iva.porcentaje}%')
        return iva

    def _crear_catalogo(self):
        """Devuelve [(TipoServicio, precio_base)]."""
        servicios = []
        for cod_cat, nombre_cat, items in CATALOGO:
            categoria, _ = CategoriaServicio.objects.get_or_create(
                codigo=cod_cat, defaults={'nombre': nombre_cat}
            )
            for cod, nombre, norma, base in items:
                tipo, _ = TipoServicio.objects.get_or_create(
                    codigo=cod,
                    defaults={'categoria': categoria, 'nombre': nombre, 'norma': norma},
                )
                servicios.append((tipo, base))
        self.stdout.write(f'Catalogo: {len(servicios)} servicios en {len(CATALOGO)} categorias')
        return servicios

    def _obtener_obras(self, maximo):
        obras = list(Obra.objects.select_related('constructora')[:maximo])
        if obras:
            self.stdout.write(f'Usando {len(obras)} obras existentes')
            return obras

        self.stdout.write('No hay obras: creando constructoras y obras demo')
        constructoras = []
        for nombre, codigo, nit, ciudad in CONSTRUCTORAS_DEMO:
            c, _ = Constructora.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': nombre, 'nit': nit, 'ciudad': ciudad},
            )
            constructoras.append(c)

        for i, nombre in enumerate(OBRAS_DEMO[:maximo]):
            obra, _ = Obra.objects.get_or_create(
                codigo_obra=f'OB-DEMO-{i + 1:02d}',
                defaults={'nombre': nombre,
                          'constructora': constructoras[i % len(constructoras)]},
            )
            obras.append(obra)
        return obras

    def _crear_precios(self, obras, servicios):
        """Cada obra recibe su lista: ~85% de los servicios con precio, el resto vacio."""
        nuevos = []
        for obra in obras:
            factor = Decimal(str(round(random.uniform(0.90, 1.25), 2)))  # tarifa por obra
            existentes = set(
                PrecioServicio.objects.filter(obra=obra)
                .values_list('tipo_servicio_id', flat=True)
            )
            for tipo, base in servicios:
                if tipo.pk in existentes:
                    continue
                precio = None
                if random.random() < 0.85:
                    precio = (Decimal(base) * factor).quantize(Decimal('1'))
                nuevos.append(PrecioServicio(obra=obra, tipo_servicio=tipo, precio=precio))
        if nuevos:
            PrecioServicio.objects.bulk_create(nuevos)
        self.stdout.write(f'Precios: {len(nuevos)} filas nuevas')

    def _crear_registros(self, obras, servicios, meses, cantidad):
        usuario = self._usuario()
        creados = 0
        consecutivo = RegistroServicio.objects.count() + 1000

        for obra in obras:
            precios = {
                p.tipo_servicio_id: p.precio
                for p in PrecioServicio.objects.filter(obra=obra).exclude(precio=None)
            }
            if not precios:
                continue
            por_obra = cantidad // len(obras)
            for _ in range(por_obra):
                tipo, _base = random.choice(servicios)
                precio = precios.get(tipo.pk)
                if precio is None:
                    continue
                dias_atras = random.randint(0, meses * 30)
                fecha = self.hoy - timedelta(days=dias_atras)
                consecutivo += 1
                RegistroServicio.objects.create(
                    obra=obra,
                    tipo_servicio=tipo,
                    fecha_realizacion=fecha,
                    cantidad=random.choice([1, 1, 1, 2, 2, 3, 4, 6, 8, 12]),
                    numero_informe=f'INF-{fecha.year}-{consecutivo}',
                    precio_unitario_congelado=precio,
                    creado_por=usuario,
                )
                creados += 1
        self.stdout.write(f'Registros de servicio: {creados}')
        return creados

    def _crear_facturas(self, obras, iva, meses):
        """
        Factura los meses cerrados (deja el mes actual y el anterior sin facturar,
        para que 'Generar factura' tenga con que trabajar).
        """
        usuario = self._usuario()
        creadas = 0

        for obra in obras:
            for atras in range(meses, 1, -1):
                inicio = self._primer_dia(atras)
                fin = self._primer_dia(atras - 1) - timedelta(days=1)

                registros = list(RegistroServicio.objects.filter(
                    obra=obra,
                    fecha_realizacion__range=(inicio, fin),
                    factura__isnull=True,
                ).select_related('tipo_servicio__categoria'))
                if not registros:
                    continue

                # Mismo criterio que finalizar_factura: normales siempre gravados,
                # transporte solo si se marca (aqui, al azar por factura).
                cobrar_iva_transporte = random.random() < 0.5
                subtotal = Decimal('0')
                base_iva = Decimal('0')
                for r in registros:
                    subtotal += r.subtotal
                    if r.es_transporte:
                        if cobrar_iva_transporte:
                            base_iva += r.subtotal
                    else:
                        base_iva += r.subtotal

                monto_iva = (base_iva * iva.porcentaje / 100).quantize(Decimal('0.01'))
                total = (subtotal + monto_iva).quantize(Decimal('0.01'))

                estado = 'PAGADA' if atras > 3 else random.choice(
                    ['PENDIENTE', 'PENDIENTE', 'PAGADA', 'ANULADA']
                )
                factura = Factura.objects.create(
                    constructora=obra.constructora,
                    obra=obra,
                    fecha_inicio_periodo=inicio,
                    fecha_fin_periodo=fin,
                    fecha_emision=fin + timedelta(days=random.randint(1, 6)),
                    subtotal=subtotal,
                    monto_iva=monto_iva,
                    total=total,
                    iva_transporte_facturado=cobrar_iva_transporte,
                    estado=estado,
                    emitida_por=usuario,
                )
                if estado == 'ANULADA':
                    # Anulada = registros liberados (como hace anular_factura)
                    continue
                RegistroServicio.objects.filter(
                    pk__in=[r.pk for r in registros]
                ).update(factura=factura)
                creadas += 1

        self.stdout.write(f'Facturas: {creadas}')
        return creadas

    # ── helpers ──────────────────────────────────────────────────────────────

    def _primer_dia(self, meses_atras):
        mes = self.hoy.month - meses_atras
        anio = self.hoy.year
        while mes <= 0:
            mes += 12
            anio -= 1
        return self.hoy.replace(year=anio, month=mes, day=1)

    def _usuario(self):
        if not hasattr(self, '_cache_usuario'):
            from users.models import UsuarioBase
            self._cache_usuario = UsuarioBase.objects.filter(
                es_geolab=True
            ).first() or UsuarioBase.objects.first()
        return self._cache_usuario
