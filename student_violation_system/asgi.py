"""
ASGI config for student_violation_system project with Channels routing.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "student_violation_system.settings")

django_asgi_app = get_asgi_application()

try:
	from channels.auth import AuthMiddlewareStack
	from channels.routing import ProtocolTypeRouter, URLRouter
	from violations.routing import websocket_urlpatterns

	application = ProtocolTypeRouter({
		"http": django_asgi_app,
		"websocket": AuthMiddlewareStack(
			URLRouter(websocket_urlpatterns)
		),
	})
except Exception:
	# Fallback to plain Django ASGI app if Channels isn't installed/configured
	application = django_asgi_app
