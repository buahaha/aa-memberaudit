"""
view constants
"""

from django.utils.translation import gettext_lazy

MY_DATETIME_FORMAT = "Y-M-d H:i"
SKILLQUEUE_DATETIME_FORMAT = "%Y-%b-%d %H:%M"  # it's a special one ...
MAIL_LABEL_ID_ALL_MAILS = 0
MAP_SKILL_LEVEL_ARABIC_TO_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
UNGROUPED_SKILL_SET = gettext_lazy("[Ungrouped]")
DEFAULT_ICON_SIZE = 32
CHARACTER_VIEWER_DEFAULT_TAB = "mails"
SKILL_SET_DEFAULT_ICON_TYPE_ID = 3327
