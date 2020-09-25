from django.conf import settings


# Maximum amount of mails fetched from ESI for each character
MEMBERAUDIT_MAX_MAILS = getattr(settings, "MEMBERAUDIT_MAX_MAILS", 250)
