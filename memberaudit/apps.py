from django.apps import AppConfig

from . import __version__


class MemberAuditConfig(AppConfig):
    name = "memberaudit"
    label = "memberaudit"
    verbose_name = f"Member Audit v{__version__}"

    def ready(self):
        import memberaudit.signals  # noqa: F401
