from django.conf import settings

# Activate developer mode for additional debug output. Undocumented feature
MEMBERAUDIT_DEVELOPER_MODE = getattr(settings, "MEMBERAUDIT_DEVELOPER_MODE", False)

# Maximum amount of mails fetched from ESI for each character
MEMBERAUDIT_MAX_MAILS = getattr(settings, "MEMBERAUDIT_MAX_MAILS", 250)

# Hours after a existing location (e.g. structure) becomes stale and gets updated
# e.g. for name changes of structures
MEMBERAUDIT_LOCATION_STALE_HOURS = getattr(
    settings, "MEMBERAUDIT_LOCATION_STALE_HOURS", 24
)
