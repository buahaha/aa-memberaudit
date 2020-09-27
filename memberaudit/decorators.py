from functools import wraps

from django.http import HttpResponseForbidden, HttpResponseNotFound

from .models import Owner


def fetch_owner_if_allowed(*args_select_related):
    """Asserts the current user has access to the owner
    and loads the given owner if it exists

    Args:
    - Optionally add list of parms for select_related. 
    Note that "character_ownership" is already included.

    Returns:
    - 403 if user has no access
    - 404 if owner does not exist 
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, owner_pk, *args, **kwargs):
            try:
                args_select_related_2 = args_select_related + ("character_ownership",)
                owner = Owner.objects.select_related(*args_select_related_2).get(
                    pk=owner_pk
                )
            except Owner.DoesNotExist:
                return HttpResponseNotFound()

            if not owner.user_has_access(request.user):
                return HttpResponseForbidden()

            return view_func(request, owner_pk, owner, *args, **kwargs)

        return _wrapped_view

    return decorator
