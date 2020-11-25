import logging
from django.core.management.base import BaseCommand

from ... import __title__
from . import get_input
from ...models import Character
from ...tasks import update_all_characters
from ...utils import LoggerAddTag

logger = LoggerAddTag(logging.getLogger(__name__), __title__)


class Command(BaseCommand):
    help = "Updates all characters from ESI, regardless of stale state"

    def handle(self, *args, **options):
        self.stdout.write("Member Audit - Update all characters")
        self.stdout.write("=====================================")
        character_count = Character.objects.count()
        if character_count > 0:
            user_input = get_input(
                f"Are you sure you want to proceed for {character_count} character(s)?"
                " (Y/n)?"
            )
            if user_input == "Y":
                logger.info(
                    "Running command update_all_characters for %s characters.",
                    character_count,
                )
                self.stdout.write("Starting task to update all characters...")
                update_all_characters.delay(force_update=True)
                self.stdout.write(self.style.SUCCESS("Done"))

        else:
            self.stdout.write(self.style.WARNING("No characters found"))
