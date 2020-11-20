import random

from celery import shared_task, chain

from bravado.exception import (
    HTTPBadGateway,
    HTTPGatewayTimeout,
    HTTPServiceUnavailable,
    HTTPError,
)
from esi.models import Token
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.models import EveEntity, EveMarketPrice

from django.db import transaction
from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from . import __title__
from .app_settings import (
    MEMBERAUDIT_TASKS_TIME_LIMIT,
    MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS,
    MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
    MEMBERAUDIT_UPDATE_STALE_RING_2,
)
from .core import esi_errors
from .models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterMail,
    CharacterUpdateStatus,
    Location,
)

from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)

DEFAULT_TASK_PRIORITY = 6

# params for all tasks
TASK_DEFAULT_KWARGS = {
    "time_limit": MEMBERAUDIT_TASKS_TIME_LIMIT,
}

# params for tasks that make ESI calls
TASK_ESI_KWARGS = {
    **TASK_DEFAULT_KWARGS,
    **{
        "autoretry_for": (
            OSError,
            HTTPBadGateway,
            HTTPGatewayTimeout,
            HTTPServiceUnavailable,
        ),
        "retry_kwargs": {"max_retries": 3},
        "retry_backoff": True,
    },
}


@shared_task(**TASK_DEFAULT_KWARGS)
def run_regular_updates() -> None:
    """Main task to be run on a regular basis to keep everyting updated and running"""
    if not is_esi_online():
        logger.info(
            "ESI is currently offline. Can not start ESI related tasks. Aborting"
        )
        return

    update_market_prices.apply_async(priority=DEFAULT_TASK_PRIORITY)
    update_all_characters.apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_DEFAULT_KWARGS)
def update_all_characters() -> None:
    """Start the update of all registered characters"""
    for character in Character.objects.all():
        update_character.apply_async(
            kwargs={"character_pk": character.pk}, priority=DEFAULT_TASK_PRIORITY
        )


# Main character update tasks


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character(character_pk: int, force_update=False) -> bool:
    """Start respective update tasks for all stale sections of a character

    Args:
    - character_pk: PL of character to update
    - force_update: When set to True will always update regardless of stale status

    Returns:
    - True when update was conducted
    - False when no updated was needed
    """
    character = Character.objects.get(pk=character_pk)
    all_sections = Character.update_sections()
    needs_update = force_update
    for section in all_sections:
        needs_update |= character.is_update_section_stale(section)

    if not needs_update:
        logger.info("%s: No update required", character)
        return False

    logger.info("%s: Starting character update", character)
    sections = all_sections.difference(
        {
            Character.UPDATE_SECTION_ASSETS,
            Character.UPDATE_SECTION_MAILS,
            Character.UPDATE_SECTION_CONTACTS,
            Character.UPDATE_SECTION_CONTRACTS,
            Character.UPDATE_SECTION_WALLET_JOURNAL,
        }
    )
    for section in sorted(sections):
        if force_update or character.is_update_section_stale(section):
            update_character_section.apply_async(
                kwargs={
                    "character_pk": character.pk,
                    "section": section,
                },
                priority=DEFAULT_TASK_PRIORITY,
            )

    if force_update or character.is_update_section_stale(
        Character.UPDATE_SECTION_MAILS
    ):
        update_character_mails.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UPDATE_SECTION_CONTACTS
    ):
        update_character_contacts.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UPDATE_SECTION_CONTRACTS
    ):
        update_character_contracts.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UPDATE_SECTION_ASSETS
    ):
        update_character_assets.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )
    if force_update or character.is_update_section_stale(
        Character.UPDATE_SECTION_WALLET_JOURNAL
    ):
        update_character_wallet_journal.apply_async(
            kwargs={"character_pk": character.pk},
            priority=DEFAULT_TASK_PRIORITY,
        )

    return True


# Update sections


@shared_task(**{**TASK_ESI_KWARGS}, **{"base": QueueOnce})
def update_character_section(character_pk: int, section: str) -> None:
    """Task that updates the section of a character"""
    character = Character.objects.get(pk=character_pk)
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    _character_update_with_error_logging(
        character, section, getattr(character, Character.section_method_name(section))
    )
    _log_character_update_success(character, section)


def _character_update_with_error_logging(
    character: Character, section: str, method: object, *args, **kwargs
):
    """Allows catching and logging of any exceptions occuring
    during an character update
    """
    try:
        return method(*args, **kwargs)
    except Exception as ex:
        error_message = f"{type(ex).__name__}: {str(ex)}"
        if isinstance(ex, HTTPError):
            error_status, _ = esi_errors.update(ex.response.headers)
            if error_status:
                logger.info("%s, %s: %s", character, section, error_status)

        logger.error(
            "%s: %s: Error ocurred: %s",
            character,
            Character.section_display_name(section),
            error_message,
            exc_info=True,
        )
        CharacterUpdateStatus.objects.update_or_create(
            character=character,
            section=section,
            defaults={
                "is_success": False,
                "error_message": error_message,
            },
        )
        raise ex


def _log_character_update_success(character: Character, section: str):
    """Logs character update success for a section"""
    logger.info(
        "%s: %s update completed", character, Character.section_display_name(section)
    )
    CharacterUpdateStatus.objects.update_or_create(
        character=character, section=section, defaults={"is_success": True}
    )


@shared_task(**TASK_ESI_KWARGS)
def update_unresolved_eve_entities(
    character_pk: int, section: str, last_in_chain: bool = False
) -> None:
    """Bulk resolved all unresolved EveEntity objects in database and logs errors to respective section

    Optionally logs success for given update section
    """
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, section, EveEntity.objects.bulk_update_new_esi
    )
    if last_in_chain:
        _log_character_update_success(character, section)


# Special tasks for updating assets


@shared_task(**TASK_ESI_KWARGS)
def update_character_assets(character_pk: int) -> None:
    """Main tasks for updating the character's assets"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_ASSETS
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    character.update_status_set.filter(section=section).delete()
    asset_list = _character_update_with_error_logging(
        character, section, character.assets_build_list_from_esi
    )
    logger.info("%s: Recreating asset tree for %s assets", character, len(asset_list))
    # TODO: Add update section logging for assets_create_parents
    character.assets.all().delete()
    assets_create_parents.apply_async(
        kwargs={"character_pk": character.pk, "asset_list": asset_list},
        priority=DEFAULT_TASK_PRIORITY,
    )


@shared_task(**TASK_ESI_KWARGS)
def assets_create_parents(character_pk: int, asset_list: dict, round: int = 1) -> None:
    """creates the parent assets from given asset_list

    Parent assets are assets attached directly to a Location object (e.g. station)

    This task will recursively call itself until all possible parent assets
    from the asset list have been created.
    Then call another task to create child assets.
    """
    character = Character.objects.get(pk=character_pk)
    logger.info("%s: Creating parent assets - pass %s", character, round)

    # for debug
    # character._store_list_to_disk(asset_list, f"parent_asset_list_{round}")

    new_assets = list()
    with transaction.atomic():
        location_ids = set(Location.objects.values_list("id", flat=True))
        parent_asset_ids = {
            item_id
            for item_id, asset_info in asset_list.items()
            if asset_info.get("location_id")
            and asset_info["location_id"] in location_ids
        }
        for item_id in parent_asset_ids:
            item = asset_list[item_id]
            new_assets.append(
                CharacterAsset(
                    character=character,
                    item_id=item_id,
                    location_id=item["location_id"],
                    eve_type_id=item.get("type_id"),
                    name=item.get("name"),
                    is_blueprint_copy=item.get("is_blueprint_copy"),
                    is_singleton=item.get("is_singleton"),
                    location_flag=item.get("location_flag"),
                    quantity=item.get("quantity"),
                )
            )
            asset_list.pop(item_id)
            if len(new_assets) >= MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS:
                break

        logger.info("%s: Writing %s parent assets", character, len(new_assets))
        # TODO: `ignore_conflicts=True` needed as workaround to compensate for
        # occasional duplicate FK constraint errors. Needs to be investigated
        CharacterAsset.objects.bulk_create(
            new_assets,
            batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
            ignore_conflicts=True,
        )

    if len(parent_asset_ids) > len(new_assets):
        # there are more parent assets to create
        assets_create_parents.apply_async(
            kwargs={
                "character_pk": character.pk,
                "asset_list": asset_list,
                "round": round + 1,
            },
            priority=DEFAULT_TASK_PRIORITY,
        )
    else:
        # all parent assets created
        if asset_list:
            assets_create_children.apply_async(
                kwargs={"character_pk": character.pk, "asset_list": asset_list},
                priority=DEFAULT_TASK_PRIORITY,
            )
        else:
            _log_character_update_success(character, Character.UPDATE_SECTION_ASSETS)


@shared_task(**TASK_ESI_KWARGS)
def assets_create_children(character_pk: int, asset_list: dict, round: int = 1) -> None:
    """Created child assets from given asset list

    Child assets are assets located within other assets (aka containers)

    This task will recursively call itself until all possible assets from the
    asset list are included into the asset tree
    """
    character = Character.objects.get(pk=character_pk)
    logger.info("%s: Creating child assets - pass %s", character, round)

    # for debug
    # character._store_list_to_disk(asset_list, f"child_asset_list_{round}")

    new_assets = list()
    with transaction.atomic():
        parent_asset_ids = set(character.assets.values_list("item_id", flat=True))
        child_asset_ids = {
            item_id
            for item_id, item in asset_list.items()
            if item.get("location_id") and item["location_id"] in parent_asset_ids
        }
        for item_id in child_asset_ids:
            item = asset_list[item_id]
            new_assets.append(
                CharacterAsset(
                    character=character,
                    item_id=item_id,
                    parent=character.assets.get(item_id=item["location_id"]),
                    eve_type_id=item.get("type_id"),
                    name=item.get("name"),
                    is_blueprint_copy=item.get("is_blueprint_copy"),
                    is_singleton=item.get("is_singleton"),
                    location_flag=item.get("location_flag"),
                    quantity=item.get("quantity"),
                )
            )
            asset_list.pop(item_id)
            if len(new_assets) >= MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS:
                break

        if new_assets:
            logger.info("%s: Writing %s child assets", character, len(new_assets))
            # TODO: `ignore_conflicts=True` needed as workaround to compensate for
            # occasional duplicate FK constraint errors. Needs to be investigated
            CharacterAsset.objects.bulk_create(
                new_assets,
                batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE,
                ignore_conflicts=True,
            )

    if new_assets and asset_list:
        # there are more child assets to create
        assets_create_children.apply_async(
            kwargs={
                "character_pk": character.pk,
                "asset_list": asset_list,
                "round": round + 1,
            },
            priority=DEFAULT_TASK_PRIORITY,
        )
    else:
        _log_character_update_success(character, Character.UPDATE_SECTION_ASSETS)
        if len(asset_list) > 0:
            logger.warning(
                "%s: Failed to add %s assets to the tree: %s",
                character,
                len(asset_list),
                asset_list.keys(),
            )


# Special tasks for updating mail section


@shared_task(**TASK_ESI_KWARGS)
def update_character_mails(character_pk: int) -> None:
    """Main task for updating mails of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_MAILS
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    character.update_status_set.filter(section=section).delete()
    chain(
        update_character_mailing_lists.si(character.pk),
        update_character_mail_labels.si(character.pk),
        update_character_mail_headers.si(character.pk),
        update_character_mail_bodies.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_mailing_lists(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mailing_lists
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_labels(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_labels
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_headers(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_headers
    )


@shared_task(**TASK_ESI_KWARGS)
def update_mail_body_esi(character_pk: int, mail_pk: int):
    """Task for updating the body of a mail from ESI"""
    character = Character.objects.get(pk=character_pk)
    mail = CharacterMail.objects.get(pk=mail_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_MAILS, character.update_mail_body, mail
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_mail_bodies(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    mails_without_body_qs = character.mails.filter(body="")
    mails_without_body_count = mails_without_body_qs.count()

    if mails_without_body_count > 0:
        logger.info("%s: Loading %s mailbodies", character, mails_without_body_count)
        for mail in mails_without_body_qs:
            update_mail_body_esi.apply_async(
                kwargs={"character_pk": character.pk, "mail_pk": mail.pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    # the last task in the chain logs success (if any)
    _log_character_update_success(character, Character.UPDATE_SECTION_MAILS)


# special tasks for updating contacts


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contacts(character_pk: int) -> None:
    """Main task for updating contacts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_CONTACTS
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_contact_labels.si(character.pk),
        update_character_contacts_2.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_contact_labels(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTACTS, character.update_contact_labels
    )


@shared_task(**TASK_ESI_KWARGS)
def update_character_contacts_2(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTACTS, character.update_contacts
    )


# special tasks for updating contracts


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts(character_pk: int) -> None:
    """Main task for updating contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_CONTRACTS
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_contract_headers.si(character.pk),
        update_character_contracts_items.si(character.pk),
        update_character_contracts_bids.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_contract_headers(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character, Character.UPDATE_SECTION_CONTRACTS, character.update_contract_headers
    )


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts_items(character_pk: int) -> None:
    """Update items for all contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    contract_pks = set(
        character.contracts.filter(
            contract_type__in=[
                CharacterContract.TYPE_ITEM_EXCHANGE,
                CharacterContract.TYPE_AUCTION,
            ],
            items__isnull=True,
        ).values_list("pk", flat=True)
    )
    if len(contract_pks) > 0:
        logger.info(
            "%s: Starting updating items for %s contracts", character, len(contract_pks)
        )
        for contract_pk in contract_pks:
            update_contract_items_esi.apply_async(
                kwargs={"character_pk": character.pk, "contract_pk": contract_pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    else:
        logger.info("%s: No items to update", character)


@shared_task(**TASK_ESI_KWARGS)
def update_contract_items_esi(character_pk: int, contract_pk: int):
    """Task for updating the items of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_items(contract)


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_contracts_bids(character_pk: int) -> None:
    """Update bids for all contracts of a character"""
    character = Character.objects.get(pk=character_pk)
    contract_pks = set(
        character.contracts.filter(
            contract_type__in=[CharacterContract.TYPE_AUCTION],
            status=CharacterContract.STATUS_OUTSTANDING,
        ).values_list("pk", flat=True)
    )
    if len(contract_pks) > 0:
        logger.info(
            "%s: Starting updating bids for %s contracts", character, len(contract_pks)
        )
        for contract_pk in contract_pks:
            update_contract_bids_esi.apply_async(
                kwargs={"character_pk": character.pk, "contract_pk": contract_pk},
                priority=DEFAULT_TASK_PRIORITY,
            )

    else:
        logger.info("%s: No bids to update", character)


@shared_task(**TASK_ESI_KWARGS)
def update_contract_bids_esi(character_pk: int, contract_pk: int):
    """Task for updating the bids of a contract from ESI"""
    character = Character.objects.get(pk=character_pk)
    contract = CharacterContract.objects.get(pk=contract_pk)
    character.update_contract_bids(contract)


# special tasks for updating wallet


@shared_task(**TASK_DEFAULT_KWARGS)
def update_character_wallet_journal(character_pk: int) -> None:
    """Main task for updating wallet journal of a character"""
    character = Character.objects.get(pk=character_pk)
    section = Character.UPDATE_SECTION_WALLET_JOURNAL
    character.update_status_set.filter(section=section).delete()
    logger.info("%s: Updating %s", character, Character.section_display_name(section))
    chain(
        update_character_wallet_journal_entries.si(character.pk),
        update_unresolved_eve_entities.si(character.pk, section, last_in_chain=True),
    ).apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(**TASK_ESI_KWARGS)
def update_character_wallet_journal_entries(character_pk: int) -> None:
    character = Character.objects.get(pk=character_pk)
    _character_update_with_error_logging(
        character,
        Character.UPDATE_SECTION_WALLET_JOURNAL,
        character.update_wallet_journal,
    )


# Tasks for other objects


@shared_task(**TASK_ESI_KWARGS)
def update_market_prices():
    """Update market prices from ESI"""
    EveMarketPrice.objects.update_from_esi(
        minutes_until_stale=MEMBERAUDIT_UPDATE_STALE_RING_2
    )


@shared_task(
    **{**TASK_ESI_KWARGS},
    **{
        "bind": True,
        "base": QueueOnce,
        "once": {"keys": ["id"], "graceful": True},
        "max_retries": None,
    },
)
def update_structure_esi(self, id: int, token_pk: int):
    """Updates a structure object from ESI
    and retries later if the ESI error limit for structures has been reached
    """
    try:
        token = Token.objects.get(pk=token_pk)
    except Token.DoesNotExist:
        raise Token.DoesNotExist(
            f"Location #{id}: Requested token with pk {token_pk} does not exist"
        )

    error_status = esi_errors.get()
    if error_status and error_status.is_valid and error_status.is_exceeded:
        logger.warning(
            "Location #%s: About to reach ESI error rate limit. Defering task.", id
        )
        raise self.retry(countdown=error_status.reset + random.randint(1, 20))
    else:
        Location.objects.structure_update_or_create_esi(id, token)
