from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from users.forms import LoginForm

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- RUTA DE LOGIN AJUSTADA ---
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=LoginForm,
        redirect_authenticated_user=True  # <--- AGREGAR ESTO (Si ya entró, mándalo al home)
    ), name='login'),

    path('accounts/', include('django.contrib.auth.urls')),
    
    # La raíz ('') apunta al dashboard_router, que tiene @login_required.
    # Por lo tanto, si no estás logueado, Django leerá el LOGIN_URL de settings
    # y te mandará al login automáticamente.
    path('', include('core.urls')),

    # Módulo de Remisiones de Muestras
    path('', include('solicitudes.urls')),

    # Módulo de Ensayos de Laboratorio (F-GT-05)
    path('', include('ensayos.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)