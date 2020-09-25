from django.apps import AppConfig

from . import __version__


class MemberauditConfig(AppConfig):
    name = "memberaudit"
    label = "memberaudit"
    verbose_name = f"Member Audit v{__version__}"
