from functools import wraps

from django.http import HttpResponseForbidden, HttpResponseNotFound

from .models import Character


def fetch_character_if_allowed(*args_select_related):
    """Asserts the current user has access to the character
    and loads the given character if it exists

    Args:
    - Optionally add list of parms for select_related. 
    Note that "character_ownership" is already included.

    Returns:
    - 403 if user has no access
    - 404 if character does not exist 
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, character_pk, *args, **kwargs):
            try:
                args_select_related_2 = args_select_related + ("character_ownership",)
                character = Character.objects.select_related(
                    *args_select_related_2
                ).get(pk=character_pk)
            except Character.DoesNotExist:
                return HttpResponseNotFound()

            if not character.user_has_access(request.user):
                return HttpResponseForbidden()

            return view_func(request, character_pk, character, *args, **kwargs)

        return _wrapped_view

    return decorator
