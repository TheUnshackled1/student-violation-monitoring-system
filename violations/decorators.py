from functools import wraps
from typing import Iterable

from django.contrib import messages
from django.contrib.auth.decorators import login_required as django_login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.db import models

from .models import User


def login_required(view_func):
    """Alias to Django's login_required to keep imports local to app."""
    return django_login_required(view_func)


def role_required(allowed_roles: Iterable[str]):
    """Restrict access to users whose User.role is in allowed_roles.

    If unauthenticated, defer to LOGIN_URL via login_required.
    If authenticated but role not allowed, redirect to role router with a message.
    """

    def decorator(view_func):
        @django_login_required
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            user = request.user
            # Superuser bypass: grant access to all role-restricted views
            if getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)
            role = getattr(user, "role", None)
            if role in allowed_roles:
                return view_func(request, *args, **kwargs)

            # Optionally, return 403. Here we redirect to a safe landing with a message.
            messages.warning(request, "You do not have permission to access that page.")
            return redirect("violations:route_dashboard")

        return _wrapped

    return decorator
