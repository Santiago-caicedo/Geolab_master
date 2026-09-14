from django.db import migrations

from users.ciudades import normalizar_ciudad


def normalizar(apps, schema_editor):
    """Unifica variantes de ciudad ("bucaramanga" / "Bucaramanga") en la forma canónica."""
    Constructora = apps.get_model('users', 'Constructora')
    for c in Constructora.objects.exclude(ciudad__isnull=True).exclude(ciudad=''):
        canonica = normalizar_ciudad(c.ciudad)
        if canonica != c.ciudad:
            c.ciudad = canonica
            c.save(update_fields=['ciudad'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_alter_funcionariogeolab_area'),
    ]

    operations = [
        migrations.RunPython(normalizar, migrations.RunPython.noop),
    ]
