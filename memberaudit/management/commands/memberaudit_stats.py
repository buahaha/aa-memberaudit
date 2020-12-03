import json
import logging
from django.core.management.base import BaseCommand

from ... import __title__
from ...models import CharacterUpdateStatus
from ...utils import LoggerAddTag

logger = LoggerAddTag(logging.getLogger(__name__), __title__)


class Command(BaseCommand):
    help = "This command returns current statistics as JSON"

    def handle(self, *args, **options):
        stats = CharacterUpdateStatus.objects.calculate_statistics()
        stats_out = json.dumps(
            {"update_statistics": stats}, sort_keys=True, indent=4, ensure_ascii=False
        )
        self.stdout.write(stats_out)
