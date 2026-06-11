"""
Macros de cálculo por geometría de espécimen.

Cada macro implementa las fórmulas específicas para un tipo de geometría.
El registry permite obtener la macro correcta dado un tipo de geometría.
"""

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from math import pi

from .geometry import GEOMETRIA_CILINDRO, GEOMETRIA_CUBO, GEOMETRIA_PRISMA


class MacroBase(ABC):
    """Clase base para macros de cálculo de ensayos."""

    geometry_key = None

    # Etiquetas para columnas en templates
    field_labels = {
        'group_diametro': 'DIÁMETRO (mm)',
        'group_longitud': 'LONGITUD (mm)',
        'diametro_d1': 'D1',
        'diametro_d2': 'D2',
        'diametro_d3': 'D3',
        'longitud_l1': 'L1',
        'longitud_l2': 'L2',
        'longitud_l3': 'L3',
    }

    @abstractmethod
    def calcular_area(self, diametro_real, longitud_real=None):
        """Calcula el área de la sección transversal."""
        pass

    def calcular_dimension_real(self, v1, v2, v3):
        """Promedio de 3 mediciones. Igual para todas las geometrías."""
        if all([v1, v2, v3]):
            return round((v1 + v2 + v3) / 3, 2)
        return None

    def calcular_esfuerzo(self, carga_kn, area):
        """Esfuerzo en MPa. Fórmula estándar, override si es diferente."""
        if carga_kn and area:
            return round((carga_kn * Decimal('101.9716') / area) / 10, 2)
        return None

    def calcular_porcentaje(self, esfuerzo, fc_resistencia):
        """Porcentaje de desarrollo vs resistencia esperada."""
        if esfuerzo and fc_resistencia:
            try:
                fc = Decimal(str(fc_resistencia))
                if fc > 0:
                    return round((esfuerzo / fc) * 100, 1)
            except (ValueError, TypeError, InvalidOperation):
                pass
        return None


class MacroCilindro(MacroBase):
    """
    Macro para cilindros (3", 4", 6").
    Fórmula actual del sistema — no se modifica.
    """

    geometry_key = GEOMETRIA_CILINDRO

    field_labels = {
        'group_diametro': 'DIÁMETRO (mm)',
        'group_longitud': 'LONGITUD (mm)',
        'diametro_d1': 'D1',
        'diametro_d2': 'D2',
        'diametro_d3': 'D3',
        'longitud_l1': 'L1',
        'longitud_l2': 'L2',
        'longitud_l3': 'L3',
    }

    def calcular_area(self, diametro_real, longitud_real=None):
        """ÁREA = π × d² / 4 / 100"""
        if diametro_real:
            area = (Decimal(str(pi)) * (diametro_real ** 2) / 4) / 100
            return round(area, 2)
        return None


class MacroCubo(MacroBase):
    """
    Macro para cubos (50mm / 5x5cm).
    Ensayo de compresión en cubos NTC 220.

    Fórmulas (del Excel INF1078-2026):
      ancho_cm = avg(D1,D2,D3) / 10
      largo_cm = avg(L1,L2,L3) / 10
      area_cm2 = ancho_cm × largo_cm
      esfuerzo_kgcm2 = (carga_kn × 101.96) / area_cm2
      esfuerzo_mpa = esfuerzo_kgcm2 × 0.09807
    """

    geometry_key = GEOMETRIA_CUBO

    field_labels = {
        'group_diametro': 'ANCHO (mm)',
        'group_longitud': 'LARGO (mm)',
        'diametro_d1': 'A1',
        'diametro_d2': 'A2',
        'diametro_d3': 'A3',
        'longitud_l1': 'L1',
        'longitud_l2': 'L2',
        'longitud_l3': 'L3',
    }

    def calcular_area(self, diametro_real, longitud_real=None):
        """ÁREA (cm²) = (ancho_mm/10) × (largo_mm/10)"""
        if diametro_real and longitud_real:
            ancho_cm = diametro_real / Decimal('10')
            largo_cm = longitud_real / Decimal('10')
            return round(ancho_cm * largo_cm, 2)
        return None

    def calcular_esfuerzo(self, carga_kn, area):
        """
        Esfuerzo en MPa para cubos.
        esfuerzo_kgcm2 = (carga_kn × 101.96) / area_cm2
        esfuerzo_mpa = esfuerzo_kgcm2 × 0.09807
        """
        if carga_kn and area:
            esfuerzo_kgcm2 = (carga_kn * Decimal('101.96')) / area
            esfuerzo_mpa = esfuerzo_kgcm2 * Decimal('0.09807')
            return round(esfuerzo_mpa, 2)
        return None


class MacroPrisma(MacroBase):
    """
    Macro para vigas/prismas (15x15cm).
    Ensayo de flexión NTC 2871 (2004-12-16).

    Fórmula A (falla en tercio medio):
      R_MPa = (P_kgf × L) / (b × d²) × 10

    Fórmula B (falla fuera del tercio medio, a < 5% luz):
      R_MPa = (3 × P_kgf × a) / (b × d²) × 10

    donde:
      P_kgf = carga_kn × 101.96
      L = luz entre apoyos (mm)
      b = ancho promedio (mm, de D1-D3)
      d = altura (mm, de L1-L3)
      a = distancia de la falla al apoyo más próximo (mm)
    """

    geometry_key = GEOMETRIA_PRISMA

    field_labels = {
        'group_diametro': 'ANCHO b (mm)',
        'group_longitud': 'ALTURA d (mm)',
        'diametro_d1': 'b1',
        'diametro_d2': 'b2',
        'diametro_d3': 'b3',
        'longitud_l1': 'd1',
        'longitud_l2': 'd2',
        'longitud_l3': 'd3',
    }

    def calcular_area(self, diametro_real, longitud_real=None):
        """
        Para vigas no hay 'área' como tal. Retorna None.
        El esfuerzo se calcula directamente en calcular_esfuerzo_viga().
        """
        return None

    def calcular_esfuerzo(self, carga_kn, area):
        """No aplica para vigas. Usar calcular_esfuerzo_viga()."""
        return None

    def calcular_porcentaje(self, esfuerzo_mpa, fc_resistencia):
        """
        Para vigas, fc_resistencia (MR) viene en kg/cm².
        % = esfuerzo_mpa / MR_kgcm2 * 1000

        Esto es porque:
          R_kgcm2 = R_mpa × 10
          % = R_kgcm2 / MR_kgcm2 × 100
            = R_mpa × 10 / MR_kgcm2 × 100
            = R_mpa / MR_kgcm2 × 1000
        """
        if esfuerzo_mpa and fc_resistencia:
            try:
                mr = Decimal(str(fc_resistencia))
                if mr > 0:
                    return round(esfuerzo_mpa / mr * Decimal('1000'), 1)
            except (ValueError, TypeError, InvalidOperation):
                pass
        return None

    def calcular_esfuerzo_viga(self, carga_kn, b_mm, d_mm, luz_mm, distancia_falla_mm, formula):
        """
        Módulo de rotura (R) en MPa para vigas.

        Args:
            carga_kn: Carga máxima en kN
            b_mm: Ancho promedio en mm (de D1-D3)
            d_mm: Altura promedio en mm (de L1-L3)
            luz_mm: Luz entre apoyos en mm
            distancia_falla_mm: Distancia de la falla al apoyo más próximo en mm
            formula: 'A' o 'B'

        Returns:
            Decimal: Módulo de rotura en MPa
        """
        if not all([carga_kn, b_mm, d_mm]):
            return None

        p_kgf = carga_kn * Decimal('101.96')
        denominador = b_mm * (d_mm ** 2)

        if denominador == 0:
            return None

        if formula == 'A':
            if not luz_mm:
                return None
            r_mpa = (p_kgf * luz_mm) / denominador * Decimal('10')
        elif formula == 'B':
            if not distancia_falla_mm:
                return None
            r_mpa = (Decimal('3') * p_kgf * distancia_falla_mm) / denominador * Decimal('10')
        else:
            return None

        return round(r_mpa, 4)


# ── Registry ──

MACRO_REGISTRY = {
    GEOMETRIA_CILINDRO: MacroCilindro(),
    GEOMETRIA_CUBO: MacroCubo(),
    GEOMETRIA_PRISMA: MacroPrisma(),
}


def get_macro(geometria):
    """Obtiene la macro de cálculo para un tipo de geometría.
    Fallback a cilindro si la geometría no se reconoce."""
    return MACRO_REGISTRY.get(geometria, MACRO_REGISTRY[GEOMETRIA_CILINDRO])
