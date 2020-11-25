import logging
from django.core.management.base import BaseCommand

from esi.models import Token
from allianceauth.authentication.models import CharacterOwnership

from ... import __title__
from . import get_input
from ...models import Character, Location, MailEntity
from ...tasks import update_all_characters
from ...utils import LoggerAddTag

logger = LoggerAddTag(logging.getLogger(__name__), __title__)


class Command(BaseCommand):
    help = "Reset all character data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reload",
            action="store_true",
            help="Also start reloading",
        )

    def handle(self, *args, **options):
        self.stdout.write("Member Audit - Reset all characters")
        self.stdout.write("===================================")

        self.stdout.write(
            "This command deletes all locally stored character data, "
            "but maintains character skeletons, so they can be reloaded from ESI."
        )
        if options["reload"]:
            self.stdout.write("Will also start the task for reloading all characters.")

        self.stdout.write()
        self.stdout.write(
            "!! Please make sure your supervisors are shut down before running this command. !!"
        )
        self.stdout.write()
        self.stdout.write("ATTENTION!")
        self.stdout.write(
            "- ESI does not provide for historical data, "
            "so you will loose data like older mails and wallet journal entries. "
        )
        self.stdout.write(
            "- Also, all characters will be reset, e.g. sharing will be turned off."
        )
        self.stdout.write("- Doctrines will stay intact.")
        self.stdout.write()

        user_input = get_input("Are you sure you want to proceed? (Y/n)?")
        if user_input == "Y":
            logger.info("Running command reset_all_characters for %s characters.")
            self.stdout.write(
                self.style.SUCCESS("Character data reset has been started!")
            )
            self.stdout.write("Deleting Characters...")
            Character.objects.all().delete()
            self.stdout.write("Deleting Locations...")
            Location.objects.all().delete()
            self.stdout.write("Deleting MailEntities...")
            MailEntity.objects.all().delete()

            character_ids = set(
                Token.objects.all()
                .require_scopes(Character.get_esi_scopes())
                .require_valid()
                .values_list("character_id", flat=True)
            )
            self.stdout.write(f"Recreating {len(character_ids)} characters ...")
            for character_ownership in CharacterOwnership.objects.filter(
                character__character_id__in=character_ids
            ):
                Character.objects.create(character_ownership=character_ownership)

            if options["reload"]:
                update_all_characters.delay()
                self.stdout.write("Started task to reload all character data")

            self.stdout.write(self.style.SUCCESS("Done"))
        else:
            self.stdout.write(self.style.WARNING("Aborted"))
