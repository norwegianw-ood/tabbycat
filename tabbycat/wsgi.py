import os
from django.core.wsgi import get_wsgi_application

# Point explicitly to production settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tabbycat.settings.production")

application = get_wsgi_application()
