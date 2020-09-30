from django.conf import settings

# Activate developer mode for additional debug output. Undocumented feature
MEMBERAUDIT_DEVELOPER_MODE = getattr(settings, "MEMBERAUDIT_DEVELOPER_MODE", False)

# Maximum amount of mails fetched from ESI for each character
MEMBERAUDIT_MAX_MAILS = getattr(settings, "MEMBERAUDIT_MAX_MAILS", 250)
