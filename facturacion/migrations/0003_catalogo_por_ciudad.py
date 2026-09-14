"""
Catálogo de servicios por ciudad (sede).

Antes codigo/nombre eran únicos globalmente. Cada sede tiene su propia lista
(el mismo código puede ser otro servicio en otra ciudad), así que:
- CategoriaServicio y TipoServicio ganan `ciudad`;
- las filas existentes (catálogo cargado con cargar_catalogo_bucaramanga)
  quedan en 'Bucaramanga';
- la unicidad pasa a ser por (ciudad, codigo) y (ciudad, nombre).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('facturacion', '0002_clave_orden'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoriaservicio',
            name='ciudad',
            field=models.CharField(db_index=True, default='Bucaramanga', max_length=100, verbose_name='Ciudad (sede)'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tiposervicio',
            name='ciudad',
            field=models.CharField(db_index=True, default='Bucaramanga', editable=False, max_length=100, verbose_name='Ciudad (sede)'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='categoriaservicio',
            name='codigo',
            field=models.CharField(max_length=20, verbose_name='Código'),
        ),
        migrations.AlterField(
            model_name='tiposervicio',
            name='codigo',
            field=models.CharField(max_length=20, verbose_name='Código'),
        ),
        migrations.AlterField(
            model_name='tiposervicio',
            name='nombre',
            field=models.CharField(max_length=255, verbose_name='Nombre'),
        ),
        migrations.AddConstraint(
            model_name='categoriaservicio',
            constraint=models.UniqueConstraint(fields=('ciudad', 'codigo'), name='categoria_codigo_unico_por_ciudad'),
        ),
        migrations.AddConstraint(
            model_name='tiposervicio',
            constraint=models.UniqueConstraint(fields=('ciudad', 'codigo'), name='servicio_codigo_unico_por_ciudad'),
        ),
        migrations.AddConstraint(
            model_name='tiposervicio',
            constraint=models.UniqueConstraint(fields=('ciudad', 'nombre'), name='servicio_nombre_unico_por_ciudad'),
        ),
    ]
