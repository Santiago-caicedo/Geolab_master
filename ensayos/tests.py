"""
Tests de paridad de la macro de CILINDROS contra la macro Excel original.

Referencia de oro: PLANTILLA MACRO.xlsx (F-GT-05 v02) + plantilla de informe
F-AI-1-01 (ensayos/plantillas_xlsx/*.xlsx). La cadena de referencia se
re-implementa aquí de forma INDEPENDIENTE (tal cual las fórmulas del Excel)
para detectar cualquier deriva futura del código de producción:

  D.P  = promedio(D1..D3) + corrección_diámetro[3"|4"|6"]
  L.P  = promedio(L1..L3) + corrección_longitud[3"|4"|6"]
  área = π·D.P²/4/100                              (cm²)
  carga_corr = A0 + A1·R + A2·R² + A3·R³           (R = kN tal cual)
  esfuerzo   = (carga_corr·101.9716/área)/10       (MPa)
  %          = esfuerzo/f'c·100

Excel calcula en precisión completa y solo redondea al PRESENTAR
(half-away-from-zero). Estos tests verifican esa paridad a nivel de
presentación, que es lo que lee el cliente.

Correr con: python manage.py test ensayos
(Solo SimpleTestCase: no requiere base de datos con datos.)
"""
import math
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from django.test import SimpleTestCase

from ensayos.macros import (
    CORRECCION_CARGA_COEFS,
    CORRECCION_DIAMETRO_MM,
    CORRECCION_LONGITUD_MM,
    MacroCilindro,
    MacroCubo,
    MacroPrisma,
    corregir_carga_kn,
    parse_fc_mpa,
    redondear_half_up,
)


# ── Referencia independiente (fórmulas del Excel, precisión completa) ─────────

def excel_ref(d1, d2, d3, l1, l2, l3, carga, fc, dimension=''):
    """Cadena de PLANTILLA MACRO.xlsx re-implementada de forma independiente."""
    a0, a1, a2, a3 = (-1.36143, 1.07562, -1.80408e-4, 9.45963e-8)
    corr_d = {'3_pulg': -0.077, '4_pulg': -0.0245, '6_pulg': 0.003}
    corr_l = {'3_pulg': 0.17, '4_pulg': 0.1, '6_pulg': 0.072}
    diam = (d1 + d2 + d3) / 3 + corr_d.get(dimension, 0.0)
    lon = (l1 + l2 + l3) / 3 + corr_l.get(dimension, 0.0)
    area = math.pi * diam ** 2 / 4 / 100
    carga_corr = a0 + a1 * carga + a2 * carga ** 2 + a3 * carga ** 3
    esf = (carga_corr * 101.9716 / area) / 10 if carga > 0 else None
    pct = esf / fc * 100 if (esf is not None and fc) else None
    return {'diam': diam, 'lon': lon, 'area': area, 'esf': esf, 'pct': pct}


def make_esp(d1, d2, d3, l1, l2, l3, peso, carga, fc_texto, dimension=''):
    """Mock con la misma forma que ResultadoMuestra/Muestra (Decimales del ORM)."""
    dec = lambda v: Decimal(str(v)).quantize(Decimal('0.01')) if v is not None else None
    return SimpleNamespace(
        diametro_d1=dec(d1), diametro_d2=dec(d2), diametro_d3=dec(d3),
        longitud_l1=dec(l1), longitud_l2=dec(l2), longitud_l3=dec(l3),
        peso_gramos=dec(peso), carga_maxima_kn=dec(carga),
        muestra=SimpleNamespace(
            fecha_toma=date(2026, 6, 1), edad_ensayo_dias=28,
            fc_resistencia=fc_texto, dimension_especimen=dimension,
        ),
    )


class CorreccionInstrumentoTests(SimpleTestCase):
    """La tabla de corrección debe coincidir con la zona CORRECCION INSTRUMENTO
    de PLANTILLA MACRO.xlsx. Si el laboratorio recalibra, actualizar macros.py
    Y estos valores (vienen del certificado)."""

    def test_tabla_diametro(self):
        self.assertEqual(CORRECCION_DIAMETRO_MM,
                         {'3_pulg': -0.077, '4_pulg': -0.0245, '6_pulg': 0.003})

    def test_tabla_longitud(self):
        self.assertEqual(CORRECCION_LONGITUD_MM,
                         {'3_pulg': 0.17, '4_pulg': 0.1, '6_pulg': 0.072})

    def test_polinomio_prensa(self):
        self.assertEqual(CORRECCION_CARGA_COEFS,
                         (-1.36143, 1.07562, -1.80408e-4, 9.45963e-8))
        # Evaluación del polinomio en un punto (mismos coeficientes, a mano):
        r = 500.0
        esperado = -1.36143 + 1.07562 * r + -1.80408e-4 * r * r + 9.45963e-8 * r ** 3
        self.assertAlmostEqual(corregir_carga_kn(500), esperado, places=12)


class MacroCilindroExactaTests(SimpleTestCase):
    def test_correccion_diametro_4pulg(self):
        m = MacroCilindro()
        vals = m.calcular_valores_exactos(
            101.6, 101.6, 101.6, 203.2, 203.2, 203.2, 250, '28', dimension='4_pulg')
        self.assertAlmostEqual(vals['diametro_real'], 101.6 - 0.0245, places=12)
        self.assertAlmostEqual(vals['longitud_real'], 203.2 + 0.1, places=12)

    def test_legacy_sin_correccion(self):
        m = MacroCilindro()
        vals = m.calcular_valores_exactos(
            101.6, 101.6, 101.6, 203.2, 203.2, 203.2, 250, '28', dimension='')
        self.assertAlmostEqual(vals['diametro_real'], 101.6, places=12)
        self.assertAlmostEqual(vals['longitud_real'], 203.2, places=12)

    def test_sin_redondeos_intermedios(self):
        """El área debe salir del diámetro corregido EXACTO, no del redondeado.
        Caso donde el redondeo intermedio antiguo cambiaba la presentación."""
        m = MacroCilindro()
        vals = m.calcular_valores_exactos(
            74.70, 74.83, 74.59, 149.4, 150.3, 148.2, 30.51, '21', dimension='')
        ref = excel_ref(74.70, 74.83, 74.59, 149.4, 150.3, 148.2, 30.51, 21.0)
        self.assertAlmostEqual(vals['area'], ref['area'], places=9)
        # display: 43.83 (con el redondeo intermedio antiguo daba 43.84)
        self.assertEqual(redondear_half_up(vals['area'], 2), Decimal('43.83'))

    def test_bateria_vs_referencia(self):
        """Barrido con semilla fija: paridad contra la referencia Excel
        en valores crudos y en presentación."""
        m = MacroCilindro()
        rng = random.Random(20260726)
        dims = ['3_pulg', '4_pulg', '6_pulg', '']
        for _ in range(3000):
            d = round(rng.uniform(70, 160), 2)
            d1, d2, d3 = d, round(d + rng.uniform(-2, 2), 2), round(d + rng.uniform(-2, 2), 2)
            l = round(rng.uniform(140, 320), 2)
            l1, l2, l3 = l, round(l + rng.uniform(-4, 4), 2), round(l + rng.uniform(-4, 4), 2)
            carga = round(rng.uniform(0.5, 900), 2)
            fc = rng.choice([21.0, 28.0, 35.0, 42.0, 17.5])
            dim = rng.choice(dims)
            vals = m.calcular_valores_exactos(
                d1, d2, d3, l1, l2, l3, carga, str(fc), dimension=dim)
            ref = excel_ref(d1, d2, d3, l1, l2, l3, carga, fc, dim)
            for k_prod, k_ref, nd in [('diametro_real', 'diam', 2), ('longitud_real', 'lon', 2),
                                      ('area', 'area', 2), ('esfuerzo', 'esf', 2),
                                      ('porcentaje', 'pct', 1)]:
                p, r = vals[k_prod], ref[k_ref]
                self.assertIsNotNone(p, k_prod)
                self.assertAlmostEqual(p, r, delta=abs(r) * 1e-12 + 1e-12,
                                       msg=f'{k_prod} crudo difiere')
                self.assertEqual(redondear_half_up(p, nd), redondear_half_up(r, nd),
                                 f'{k_prod} difiere en presentación')

    def test_carga_cero_no_da_esfuerzo(self):
        m = MacroCilindro()
        vals = m.calcular_valores_exactos(
            101.6, 101.6, 101.6, 203.2, 203.2, 203.2, 0, '28', dimension='4_pulg')
        self.assertIsNone(vals['esfuerzo'])
        self.assertIsNone(vals['porcentaje'])


class RedondeoPresentacionTests(SimpleTestCase):
    def test_half_up_como_excel(self):
        # round() de Python daría 2.34 (banker's); Excel muestra 2.35
        self.assertEqual(redondear_half_up(2.345, 2), Decimal('2.35'))
        self.assertEqual(redondear_half_up(139.5, 0), Decimal('140'))
        self.assertEqual(redondear_half_up(-2.345, 2), Decimal('-2.35'))

    def test_parse_fc(self):
        self.assertEqual(parse_fc_mpa('21'), 21.0)
        self.assertEqual(parse_fc_mpa('28 MPa'), 28.0)
        self.assertEqual(parse_fc_mpa('3000 psi'), round(3000 / 145.0377, 2))
        self.assertEqual(parse_fc_mpa('210 kg/cm2'), round(210 * 0.0980665, 2))
        self.assertIsNone(parse_fc_mpa(''))
        self.assertIsNone(parse_fc_mpa(None))


class InformeInyeccionTests(SimpleTestCase):
    """_calcular_dependientes debe inyectar la cadena exacta al informe."""

    def _deps(self, esp):
        from ensayos.informes import _calcular_dependientes
        return {k[0]: v[1] for k, v in _calcular_dependientes(esp, 10).items()}

    def test_columnas_principales(self):
        esp = make_esp(101.30, 101.45, 101.20, 202.9, 203.4, 203.1,
                       3720.5, 250.75, '28', dimension='4_pulg')
        out = self._deps(esp)
        ref = excel_ref(101.30, 101.45, 101.20, 202.9, 203.4, 203.1, 250.75, 28.0, '4_pulg')
        self.assertAlmostEqual(out['I'], ref['diam'], places=9)
        self.assertAlmostEqual(out['H'], ref['lon'], places=9)
        self.assertAlmostEqual(out['J'], ref['area'], places=9)
        self.assertEqual(out['L'], 250.75)  # carga kN TAL CUAL
        carga_corr = corregir_carga_kn(250.75)
        self.assertAlmostEqual(out['K'], carga_corr / 0.009807, places=6)
        self.assertAlmostEqual(out['O'], ref['esf'], places=9)
        self.assertAlmostEqual(out['N'], (carga_corr / 0.009807) / ref['area'], places=6)
        self.assertAlmostEqual(out['P'], out['N'] / 0.07, places=6)
        self.assertAlmostEqual(out['Q'], ref['pct'], places=9)
        self.assertAlmostEqual(out['S'], ref['lon'] / ref['diam'], places=9)

    def test_densidad_mround_half_up(self):
        # La densidad usa MROUND de Excel: múltiplo de 10, mitades LEJOS de cero.
        esp = make_esp(100.0, 100.0, 100.0, 200.0, 200.0, 200.0,
                       1000.0, 250.0, '28', dimension='')
        out = self._deps(esp)
        j = math.pi * 100.0 ** 2 / 400
        dens = 1000.0 / (j * 200.0 / 1e7) / 1000
        esperado = int((Decimal(repr(dens)) / 10).quantize(
            Decimal(1), rounding=ROUND_HALF_UP) * 10)
        self.assertEqual(out['R'], esperado)

    def test_carga_cero_no_inyecta_resistencias(self):
        esp = make_esp(101.6, 101.6, 101.6, 203.2, 203.2, 203.2,
                       3720.0, 0, '28', dimension='4_pulg')
        out = self._deps(esp)
        self.assertEqual(out['L'], 0.0)
        for col in ('K', 'N', 'O', 'P', 'Q'):
            self.assertNotIn(col, out)  # las fórmulas del template resuelven a 0/""


class OtrasGeometriasSinCambiosTests(SimpleTestCase):
    """Cubo y prisma conservan su comportamiento previo (aún no auditados
    contra su Excel original — solo cilindros en esta fase)."""

    def test_cubo(self):
        m = MacroCubo()
        area = m.calcular_area(Decimal('50.00'), Decimal('50.00'))
        self.assertEqual(area, Decimal('25.00'))
        esf = m.calcular_esfuerzo(Decimal('100'), area)
        esperado = round((Decimal('100') * Decimal('101.96') / area) * Decimal('0.09807'), 2)
        self.assertEqual(esf, esperado)

    def test_prisma(self):
        m = MacroPrisma()
        r = m.calcular_esfuerzo_viga(
            Decimal('30'), Decimal('150'), Decimal('150'),
            Decimal('450'), None, 'A')
        esperado = round((Decimal('30') * Decimal('101.96') * Decimal('450'))
                         / (Decimal('150') * Decimal('150') ** 2) * Decimal('10'), 4)
        self.assertEqual(r, esperado)
