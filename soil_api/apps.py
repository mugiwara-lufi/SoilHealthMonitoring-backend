from django.apps import AppConfig
from django.db.models.signals import post_migrate


class SoilApiConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'soil_api'

    def ready(self):
        # Disconnect built-in auth permission generation which is incompatible with MongoDB
        from django.contrib.auth.management import create_permissions
        post_migrate.disconnect(
            create_permissions,
            dispatch_uid="django.contrib.auth.management.create_permissions",
        )