from .utils import clean_setting

# Activate developer mode for additional debug output. Undocumented feature
MEMBERAUDIT_DEVELOPER_MODE = clean_setting("MEMBERAUDIT_DEVELOPER_MODE", False)

# Hours after a existing location (e.g. structure) becomes stale and gets updated
# e.g. for name changes of structures
MEMBERAUDIT_LOCATION_STALE_HOURS = clean_setting("MEMBERAUDIT_LOCATION_STALE_HOURS", 24)

# Maximum amount of mails fetched from ESI for each character
MEMBERAUDIT_MAX_MAILS = clean_setting("MEMBERAUDIT_MAX_MAILS", 250)

# Global timeout for tasks in seconds to reduce task accumulation during outages
MEMBERAUDIT_TASKS_TIME_LIMIT = clean_setting("MEMBERAUDIT_TASKS_TIME_LIMIT", 7200)

# Technical parameter defining the maximum number of asset items processed in each pass
# when updating character assets.
# A higher value reduces duration, but also increases task queue congestion
MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS = clean_setting(
    "MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS", 250
)

# Technical parameter defining the maximum number of objects processed per run
# of Django batch methods, e.g. bulk_create and bulk_update
MEMBERAUDIT_BULK_METHODS_BATCH_SIZE = clean_setting(
    "MEMBERAUDIT_BULK_METHODS_BATCH_SIZE", 500
)
