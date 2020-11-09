import datetime as dt
import humanize

from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction, models
from django.db.models import Count, F, Max, Q, Sum
from django.http import (
    JsonResponse,
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseForbidden,
)
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.timesince import timeuntil
from django.utils.html import format_html
from django.utils.timezone import now
from django.utils.translation import gettext_lazy, gettext

from esi.decorators import token_required

from allianceauth.authentication.models import CharacterOwnership, User
from allianceauth.eveonline.models import EveCharacter
from allianceauth.services.hooks import get_extension_logger

from . import tasks, __title__
from .constants import EVE_CATEGORY_ID_SHIP
from .decorators import fetch_character_if_allowed
from .helpers import eve_solar_system_to_html
from .models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterContractItem,
    CharacterMail,
    Doctrine,
    Location,
)
from .utils import (
    add_no_wrap_html,
    create_link_html,
    create_fa_button_html,
    LoggerAddTag,
    messages_plus,
    yesno_str,
)

from .app_settings import MEMBERAUDIT_APP_NAME

# module constants
MY_DATETIME_FORMAT = "Y-M-d H:i"
DATETIME_FORMAT = "%Y-%b-%d %H:%M"
MAIL_LABEL_ID_ALL_MAILS = 0
MAP_SKILL_LEVEL_ARABIC_TO_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
NO_DOCTRINE_NAME = gettext_lazy("(No Doctrine)")
DEFAULT_ICON_SIZE = 32
CHARACTER_VIEWER_DEFAULT_TAB = "mail"

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def create_img_html(src: str, classes: list = None, size: int = None) -> str:
    classes_str = format_html('class="{}"', (" ".join(classes)) if classes else "")
    size_html = format_html('width="{}" height="{}"', size, size) if size else ""
    return format_html('<img {} {} src="{}">', classes_str, size_html, src)


def create_icon_plus_name_html(
    icon_url, name, size: int = DEFAULT_ICON_SIZE, avatar=False, url=None
) -> str:
    """create HTML to display an icon next to a name. Can also be a link."""
    return format_html(
        "{}&nbsp;&nbsp;&nbsp;{}",
        create_img_html(
            icon_url, classes=["ra-avatar", "img-circle"] if avatar else [], size=size
        ),
        create_link_html(url, name, new_window=False) if url else name,
    )


def create_main_organization_html(main_character) -> str:
    return format_html(
        "{}{}",
        main_character.corporation_name,
        f" [{main_character.alliance_ticker}]" if main_character.alliance_name else "",
    )


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    unregistered_count = Character.objects.unregistered_characters_of_user_count(
        request.user
    )
    new_context = {
        **{
            "app_title": MEMBERAUDIT_APP_NAME,
            "unregistered_count": unregistered_count,
            "MY_DATETIME_FORMAT": MY_DATETIME_FORMAT,
        },
        **context,
    }
    return new_context


@login_required
@permission_required("memberaudit.basic_access")
def index(request):
    return redirect("memberaudit:launcher")


#############################
# Section: Characters


@login_required
@permission_required("memberaudit.basic_access")
def launcher(request) -> HttpResponse:
    owned_chars_query = (
        CharacterOwnership.objects.filter(user=request.user)
        .select_related(
            "character",
            "memberaudit_character",
            "memberaudit_character__wallet_balance",
            "memberaudit_character__skillpoints",
            "memberaudit_character__unread_mail_count",
        )
        .order_by()
    )
    has_auth_characters = owned_chars_query.count() > 0
    auth_characters = list()
    unregistered_chars = list()
    for character_ownership in owned_chars_query:
        eve_character = character_ownership.character
        try:
            character = character_ownership.memberaudit_character
        except AttributeError:
            unregistered_chars.append(eve_character.character_name)
        else:
            auth_characters.append(
                {
                    "character_id": eve_character.character_id,
                    "character_name": eve_character.character_name,
                    "character": character,
                    "alliance_id": eve_character.alliance_id,
                    "alliance_name": eve_character.alliance_name,
                    "corporation_id": eve_character.corporation_id,
                    "corporation_name": eve_character.corporation_name,
                }
            )

    unregistered_chars = sorted(unregistered_chars)

    try:
        main_character_id = request.user.profile.main_character.character_id
    except AttributeError:
        main_character_id = None

    context = {
        "page_title": "My Characters",
        "auth_characters": auth_characters,
        "has_auth_characters": has_auth_characters,
        "unregistered_chars": unregistered_chars,
        "has_registered_characters": len(auth_characters) > 0,
        "main_character_id": main_character_id,
    }

    """
    if has_auth_characters:
        messages_plus.warning(
            request,
            format_html(
                "Please register all your characters. "
                "You currently have <strong>{}</strong> unregistered characters.",
                unregistered_chars,
            ),
        )
    """
    return render(
        request,
        "memberaudit/launcher.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@token_required(scopes=Character.get_esi_scopes())
def add_character(request, token) -> HttpResponse:
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    try:
        character_ownership = CharacterOwnership.objects.select_related(
            "character"
        ).get(user=request.user, character=token_char)
    except CharacterOwnership.DoesNotExist:
        messages_plus.error(
            request,
            format_html(
                "You can register your main or alt characters."
                "However, character <strong>{}</strong> is neither. ",
                token_char.character_name,
            ),
        )
    else:
        with transaction.atomic():
            character, _ = Character.objects.update_or_create(
                character_ownership=character_ownership
            )

        tasks.update_character.delay(character_pk=character.pk)
        messages_plus.success(
            request,
            format_html(
                "<strong>{}</strong> has been registered. "
                "Note that it can take a minute until all character data is visible.",
                character.character_ownership.character,
            ),
        )

    return redirect("memberaudit:launcher")


@login_required
@permission_required("memberaudit.basic_access")
def remove_character(request, character_pk: int) -> HttpResponse:
    try:
        character = Character.objects.select_related(
            "character_ownership__user", "character_ownership__character"
        ).get(pk=character_pk)
    except Character.DoesNotExist:
        return HttpResponseNotFound(f"Character with pk {character_pk} not found")

    character_name = character.character_ownership.character.character_name
    if character.character_ownership.user == request.user:
        character.delete()
        messages_plus.success(
            request,
            format_html(
                "Removed character <strong>{}</strong> as requested.", character_name
            ),
        )
    else:
        return HttpResponseForbidden(
            f"No permission to remove Character with pk {character_pk}"
        )

    return redirect("memberaudit:launcher")


@login_required
@permission_required("memberaudit.basic_access")
def share_character(request, character_pk: int) -> HttpResponse:
    try:
        character = Character.objects.select_related(
            "character_ownership__user", "character_ownership__character"
        ).get(pk=character_pk)
    except Character.DoesNotExist:
        return HttpResponseNotFound(f"Character with pk {character_pk} not found")

    if character.character_ownership.user == request.user:
        character.is_shared = True
        character.save()
    else:
        return HttpResponseForbidden(
            f"No permission to remove Character with pk {character_pk}"
        )

    return redirect("memberaudit:launcher")


@login_required
@permission_required("memberaudit.basic_access")
def unshare_character(request, character_pk: int) -> HttpResponse:
    try:
        character = Character.objects.select_related(
            "character_ownership__user", "character_ownership__character"
        ).get(pk=character_pk)
    except Character.DoesNotExist:
        return HttpResponseNotFound(f"Character with pk {character_pk} not found")

    if character.character_ownership.user == request.user:
        character.is_shared = False
        character.save()
    else:
        return HttpResponseForbidden(
            f"No permission to remove Character with pk {character_pk}"
        )

    return redirect("memberaudit:launcher")


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed(
    "details",
    "wallet_balance",
    "skillpoints",
    "character_ownership__user__profile__main_character",
    "location__location",
    "location__eve_solar_system",
    "location__eve_solar_system__eve_constellation__eve_region",
    "online_status",
)
def character_viewer(request, character_pk: int, character: Character) -> HttpResponse:
    """main view for showing a character with all details

    Args:
    - character_pk: PK for character to be shown

    GET Params:
    - tab: ID of tab to be shown  (optional)
    """
    # character details
    try:
        character_details = character.details
    except ObjectDoesNotExist:
        character_details = None

    # main character
    auth_character = character.character_ownership.character
    try:
        main_character = character.character_ownership.user.profile.main_character
        main = f"[{main_character.corporation_ticker}] {main_character.character_name}"
    except AttributeError:
        main_character = None
        main = "-"

    # mailing lists
    mailing_lists = list(
        character.mailing_lists.annotate(
            unread_count=Count(
                "charactermailrecipient",
                filter=Q(charactermailrecipient__mail__is_read=False),
            )
        ).values("list_id", "name", "unread_count")
    )

    # mail labels
    mail_labels = list(
        character.mail_labels.values(
            "label_id", "name", unread_count_2=F("unread_count")
        )
    )

    total_unread_count = sum(
        [obj["unread_count_2"] for obj in mail_labels if obj["unread_count_2"]]
    )
    total_unread_count += sum(
        [obj["unread_count"] for obj in mailing_lists if obj["unread_count"]]
    )

    mail_labels.append(
        {
            "label_id": MAIL_LABEL_ID_ALL_MAILS,
            "name": "All Mails",
            "unread_count_2": total_unread_count,
        }
    )

    # registered characters
    registered_characters = list(
        Character.objects.select_related(
            "character_ownership", "character_ownership__character"
        )
        .filter(character_ownership__user=character.character_ownership.user)
        .order_by("character_ownership__character__character_name")
        .values(
            "pk",
            "is_shared",
            name=F("character_ownership__character__character_name"),
            character_id=F("character_ownership__character__character_id"),
        )
    )

    # assets total value
    character_assets_total = (
        character.assets.exclude(is_blueprint_copy=True)
        .aggregate(
            total=Sum(
                F("quantity") * F("eve_type__market_price__average_price"),
                output_field=models.FloatField(),
            )
        )
        .get("total")
    )

    # implants
    try:
        has_implants = character.implants.count() > 0
    except ObjectDoesNotExist:
        has_implants = False

    # last updates
    try:
        last_updates = {
            obj["section"]: obj["updated_at"]
            for obj in character.update_status_set.filter(is_success=True).values(
                "section", "updated_at"
            )
        }
    except ObjectDoesNotExist:
        last_updates = None

    show_tab = request.GET.get("tab", "")
    context = {
        "page_title": "Character Sheet",
        "character": character,
        "auth_character": auth_character,
        "character_details": character_details,
        "mail_labels": mail_labels,
        "mailing_lists": mailing_lists,
        "main": main,
        "main_character_id": main_character.character_id if main_character else None,
        "registered_characters": registered_characters,
        "show_tab": show_tab,
        "last_updates": last_updates,
        "character_assets_total": character_assets_total,
        "has_implants": has_implants,
    }
    return render(
        request,
        "memberaudit/character_viewer.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_assets_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        asset_qs = (
            character.assets.annotate_pricing()
            .select_related(
                "eve_type",
                "eve_type__eve_group",
                "eve_type__eve_group__eve_category",
                "location",
                "location__eve_solar_system__eve_constellation__eve_region",
            )
            .filter(location__isnull=False)
        )

    except ObjectDoesNotExist:
        return HttpResponseNotFound()

    assets_with_children_ids = set(
        character.assets.filter(children__isnull=False).values_list(
            "item_id", flat=True
        )
    )

    location_counts = {
        obj["id"]: obj["items_count"]
        for obj in (
            Location.objects.filter(characterasset__character=character)
            .annotate(items_count=Count("characterasset"))
            .values("id", "items_count")
        )
    }

    for asset in asset_qs:
        if asset.location.eve_solar_system:
            region = asset.location.eve_solar_system.eve_constellation.eve_region.name
            solar_system = asset.location.eve_solar_system.name
        else:
            region = ""
            solar_system = ""

        is_ship = yesno_str(
            asset.eve_type.eve_group.eve_category_id == EVE_CATEGORY_ID_SHIP
        )

        if asset.item_id in assets_with_children_ids:
            ajax_children_url = reverse(
                "memberaudit:character_asset_container",
                args=[character.pk, asset.pk],
            )
            actions_html = (
                '<button type="button" class="btn btn-default btn-sm" '
                'data-toggle="modal" data-target="#modalCharacterAssetContainer" '
                f"data-ajax_children_url={ajax_children_url}>"
                '<i class="fas fa-search"></i></button>'
            )
        else:
            actions_html = ""

        location_name = (
            f"{asset.location.name_plus} ({location_counts.get(asset.location_id, 0)})"
        )
        name_html = create_icon_plus_name_html(
            asset.eve_type.icon_url(DEFAULT_ICON_SIZE), asset.name_display
        )

        data.append(
            {
                "item_id": asset.item_id,
                "location": location_name,
                "name": {
                    "display": name_html,
                    "sort": asset.name_display,
                },
                "quantity": asset.quantity if not asset.is_singleton else "",
                "group": asset.group_display,
                "volume": asset.eve_type.volume,
                "price": asset.price,
                "total": asset.total,
                "actions": actions_html,
                "region": region,
                "solar_system": solar_system,
                "is_ship": is_ship,
            }
        )

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_asset_container(
    request, character_pk: int, character: Character, parent_asset_pk: int
) -> JsonResponse:
    try:
        parent_asset = character.assets.select_related("location").get(
            pk=parent_asset_pk
        )
    except CharacterAsset.DoesNotExist:
        error_msg = (
            f"Asset with pk {parent_asset_pk} not found for character {character}"
        )
        logger.warning(error_msg)
        context = {
            "error": error_msg,
        }
    else:
        context = {
            "character": character,
            "parent_asset": parent_asset,
        }
    return render(
        request,
        "memberaudit/modals/character_viewer/asset_container_content.html",
        context,
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_asset_container_data(
    request, character_pk: int, character: Character, parent_asset_pk: int
) -> JsonResponse:
    data = list()
    try:
        parent_asset = character.assets.get(pk=parent_asset_pk)
    except CharacterAsset.DoesNotExist:
        error_msg = (
            f"Asset with pk {parent_asset_pk} not found for character {character}"
        )
        logger.warning(error_msg)
        return HttpResponseNotFound(error_msg)

    try:
        assets_qs = parent_asset.children.annotate_pricing().select_related(
            "eve_type",
            "eve_type__eve_group",
            "eve_type__eve_group__eve_category",
        )
    except ObjectDoesNotExist:
        return HttpResponseNotFound()

    for asset in assets_qs:
        name_html = create_icon_plus_name_html(
            asset.eve_type.icon_url(DEFAULT_ICON_SIZE), asset.name_display
        )
        data.append(
            {
                "item_id": asset.item_id,
                "name": {
                    "display": name_html,
                    "sort": asset.name_display,
                },
                "quantity": asset.quantity if not asset.is_singleton else "",
                "group": asset.group_display,
                "volume": asset.eve_type.volume,
                "price": asset.price,
                "total": asset.total,
            }
        )

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_contacts_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        for contact in character.contacts.select_related("eve_entity").all():
            is_watched = contact.is_watched is True
            is_blocked = contact.is_blocked is True
            name = contact.eve_entity.name
            name_html = create_icon_plus_name_html(
                contact.eve_entity.icon_url(DEFAULT_ICON_SIZE), name, avatar=True
            )
            data.append(
                {
                    "id": contact.eve_entity_id,
                    "name": {"display": name_html, "sort": name},
                    "standing": contact.standing,
                    "type": contact.eve_entity.get_category_display().title(),
                    "is_watched": is_watched,
                    "is_blocked": is_blocked,
                    "is_watched_str": yesno_str(is_watched),
                    "is_blocked_str": yesno_str(is_blocked),
                    "level": contact.standing_level.title(),
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_contracts_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        for contract in character.contracts.select_related("issuer", "assignee").all():
            if now() < contract.date_expired:
                time_left = timeuntil(contract.date_expired, now())
            else:
                time_left = "expired"

            ajax_contract_detail = reverse(
                "memberaudit:character_contract_details",
                args=[character.pk, contract.pk],
            )

            actions_html = (
                '<button type="button" class="btn btn-primary" '
                'data-toggle="modal" data-target="#modalCharacterContract" '
                f"data-ajax_contract_detail={ajax_contract_detail}>"
                '<i class="fas fa-search"></i></button>'
            )
            data.append(
                {
                    "contract_id": contract.contract_id,
                    "summary": contract.summary(),
                    "type": contract.get_contract_type_display().title(),
                    "from": contract.issuer.name,
                    "to": contract.assignee.name if contract.assignee else "(None)",
                    "status": contract.get_status_display(),
                    "date_issued": contract.date_issued.isoformat(),
                    "time_left": time_left,
                    "info": contract.title,
                    "actions": actions_html,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_contract_details(
    request, character_pk: int, character: Character, contract_pk: int
) -> HttpResponse:
    error_msg = None
    try:
        contract = (
            character.contracts.select_related(
                "issuer", "start_location", "end_location", "assignee"
            )
            .prefetch_related("bids")
            .get(pk=contract_pk)
        )
    except CharacterContract.DoesNotExist:
        error_msg = (
            f"Contract with pk {contract_pk} not found for character {character}"
        )
        logger.warning(error_msg)
        context = {
            "error": error_msg,
            "character": character,
        }
    else:
        try:
            has_items_included = contract.items.filter(is_included=True).exists()
            has_items_requested = contract.items.filter(is_included=False).exists()
        except ObjectDoesNotExist:
            has_items_included = False
            has_items_requested = False

        try:
            current_bid = (
                contract.bids.all().aggregate(Max("amount")).get("amount__max")
            )
            bids_count = contract.bids.count()
        except ObjectDoesNotExist:
            current_bid = None
            bids_count = None

        context = {
            "character": character,
            "contract": contract,
            "contract_summary": contract.summary(),
            "MY_DATETIME_FORMAT": MY_DATETIME_FORMAT,
            "has_items_included": has_items_included,
            "has_items_requested": has_items_requested,
            "current_bid": current_bid,
            "bids_count": bids_count,
        }
    return render(
        request,
        "memberaudit/modals/character_viewer/contract_content.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_contract_items_included_data(
    request, character_pk: int, character: Character, contract_pk: int
) -> JsonResponse:
    return _character_contract_items_data(
        request=request,
        character_pk=character_pk,
        character=character,
        contract_pk=contract_pk,
        is_included=True,
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_contract_items_requested_data(
    request, character_pk: int, character: Character, contract_pk: int
) -> JsonResponse:
    return _character_contract_items_data(
        request=request,
        character_pk=character_pk,
        character=character,
        contract_pk=contract_pk,
        is_included=False,
    )


def _character_contract_items_data(
    request,
    character_pk: int,
    character: Character,
    contract_pk: int,
    is_included: bool,
) -> JsonResponse:
    data = list()
    try:
        contract = character.contracts.prefetch_related("items").get(pk=contract_pk)
    except CharacterAsset.DoesNotExist:
        error_msg = (
            f"Contract with pk {contract_pk} not found for character {character}"
        )
        logger.warning(error_msg)
        return HttpResponseNotFound(error_msg)

    try:
        items_qs = (
            contract.items.annotate_pricing()
            .filter(is_included=is_included)
            .select_related(
                "eve_type",
                "eve_type__eve_group",
                "eve_type__eve_group__eve_category",
            )
        )
    except ObjectDoesNotExist:
        items_qs = CharacterContractItem.objects.none()

    for item in items_qs:
        name = item.eve_type.name
        if item.is_bpo:
            name += " [BPC]"

        name_html = create_icon_plus_name_html(
            item.eve_type.icon_url(DEFAULT_ICON_SIZE), name
        )
        data.append(
            {
                "id": item.record_id,
                "name": {
                    "display": name_html,
                    "sort": name,
                },
                "quantity": item.quantity if not item.is_singleton else "",
                "group": item.eve_type.eve_group.name,
                "category": item.eve_type.eve_group.eve_category.name,
                "price": item.price,
                "total": item.total,
                "is_bpo": item.is_bpo,
            }
        )

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_doctrines_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    def create_data_row(doctrine_name) -> dict:
        url = (
            ship_check.ship.ship_type.icon_url(DEFAULT_ICON_SIZE)
            if ship_check.ship.ship_type
            else ""
        )
        ship_icon = f'<img width="24" heigh="24" src="{url}"/>'
        return {
            "ship_check_id": ship_check.id,
            "doctrine": doctrine_name,
            "ship": ship_icon + "&nbsp;&nbsp;" + ship_check.ship.name,
            "ship_name": ship_check.ship.name,
            "can_fly": can_fly,
            "can_fly_str": yesno_str(can_fly),
            "insufficient_skills": ", ".join(insufficient_skills_2)
            if insufficient_skills_2
            else "-",
        }

    data = list()
    try:
        for ship_check in character.doctrine_ships.filter(ship__is_visible=True):
            insufficient_skills_1 = sorted(
                ship_check.insufficient_skills.values("eve_type__name", "level"),
                key=lambda k: k["eve_type__name"].lower(),
            )
            insufficient_skills_2 = [
                obj["eve_type__name"]
                + "&nbsp;"
                + MAP_SKILL_LEVEL_ARABIC_TO_ROMAN[obj["level"]]
                for obj in insufficient_skills_1
            ]
            can_fly = not bool(insufficient_skills_2)
            if not ship_check.ship.doctrines.exists():
                data.append(create_data_row(NO_DOCTRINE_NAME))
            else:
                for doctrine in ship_check.ship.doctrines.all():
                    doctrine_name = (
                        doctrine.name
                        if doctrine.is_active
                        else doctrine.name + " [Not active]"
                    )
                    data.append(create_data_row(doctrine_name))

    except ObjectDoesNotExist:
        pass

    data = sorted(data, key=lambda k: (k["doctrine"].lower(), k["ship_name"].lower()))
    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_corporation_history(
    request, character_pk: int, character: Character
) -> HttpResponse:
    corporation_history = list()
    try:
        corporation_history_qs = (
            character.corporation_history.exclude(is_deleted=True)
            .select_related("corporation")
            .order_by("start_date")
        )
    except ObjectDoesNotExist:
        pass

    else:
        for entry in corporation_history_qs:
            if len(corporation_history) > 0:
                corporation_history[-1]["end_date"] = entry.start_date
                corporation_history[-1]["is_last"] = False

            corporation_history.append(
                {
                    "id": entry.pk,
                    "corporation_name": entry.corporation.name,
                    "start_date": entry.start_date,
                    "end_date": now(),
                    "is_last": True,
                }
            )

    context = {
        "corporation_history": reversed(corporation_history),
        "has_corporation_history": len(corporation_history) > 0,
    }
    return render(
        request,
        "memberaudit/partials/character_viewer/tabs/corporation_history_2.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_implants_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        for implant in character.implants.select_related("eve_type").prefetch_related(
            "eve_type__dogma_attributes"
        ):
            implant_html = create_icon_plus_name_html(
                implant.eve_type.icon_url(DEFAULT_ICON_SIZE), implant.eve_type.name
            )
            try:
                slot_num = int(
                    implant.eve_type.dogma_attributes.get(
                        eve_dogma_attribute_id=331
                    ).value
                )
            except (ObjectDoesNotExist, AttributeError):
                slot_num = 0

            data.append(
                {
                    "id": implant.pk,
                    "implant": {"display": implant_html, "sort": slot_num},
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_loyalty_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        for entry in character.loyalty_entries.select_related("corporation"):
            corporation_html = create_icon_plus_name_html(
                entry.corporation.icon_url(DEFAULT_ICON_SIZE), entry.corporation.name
            )
            data.append(
                {
                    "id": entry.pk,
                    "corporation": {
                        "display": corporation_html,
                        "sort": entry.corporation.name,
                    },
                    "loyalty_points": entry.loyalty_points,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_jump_clones_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    data = list()
    try:
        for jump_clone in (
            character.jump_clones.select_related(
                "location",
                "location__eve_solar_system",
                "location__eve_solar_system__eve_constellation__eve_region",
            )
            .prefetch_related("implants")
            .all()
        ):
            if not jump_clone.location.is_empty:
                eve_solar_system = jump_clone.location.eve_solar_system
                solar_system = eve_solar_system_to_html(
                    eve_solar_system, show_region=False
                )
                region = eve_solar_system.eve_constellation.eve_region.name
            else:
                solar_system = "-"
                region = "-"

            implants_data = list()
            for obj in jump_clone.implants.select_related("eve_type").prefetch_related(
                "eve_type__dogma_attributes"
            ):
                try:
                    slot_num = int(
                        obj.eve_type.dogma_attributes.get(
                            eve_dogma_attribute_id=331
                        ).value
                    )
                except (ObjectDoesNotExist, AttributeError):
                    slot_num = 0

                implants_data.append(
                    {
                        "name": obj.eve_type.name,
                        "icon_url": obj.eve_type.icon_url(DEFAULT_ICON_SIZE),
                        "slot_num": slot_num,
                    }
                )
            if implants_data:
                implants = "<br>".join(
                    create_icon_plus_name_html(
                        x["icon_url"], add_no_wrap_html(x["name"]), size=24
                    )
                    for x in sorted(implants_data, key=lambda k: k["slot_num"])
                )
            else:
                implants = "(none)"

            data.append(
                {
                    "id": jump_clone.pk,
                    "region": region,
                    "solar_system": solar_system,
                    "location": jump_clone.location.name_plus,
                    "implants": implants,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


def _character_mail_headers_data(request, character, mail_headers_qs) -> JsonResponse:
    mails_data = list()
    try:
        for mail in mail_headers_qs.select_related(
            "from_entity", "from_mailing_list"
        ).prefetch_related("recipients"):
            mail_ajax_url = reverse(
                "memberaudit:character_mail_data", args=[character.pk, mail.pk]
            )

            actions_html = (
                '<button type="button" class="btn btn-primary" '
                'data-toggle="modal" data-target="#modalCharacterMail" '
                f"data-ajax_mail_body={mail_ajax_url}>"
                '<i class="fas fa-search"></i></button>'
            )

            from_name = (
                mail.from_mailing_list.name
                if mail.from_mailing_list
                else mail.from_entity.name
            )
            mails_data.append(
                {
                    "mail_id": mail.mail_id,
                    "from": from_name,
                    "to": ", ".join(
                        sorted(
                            [
                                str(obj)
                                for obj in mail.recipients.select_related(
                                    "eve_entity", "mailing_list"
                                )
                            ]
                        )
                    ),
                    "subject": mail.subject,
                    "sent": mail.timestamp.isoformat(),
                    "action": actions_html,
                    "is_read": mail.is_read,
                    "is_unread_str": yesno_str(mail.is_read is False),
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(mails_data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_mail_headers_by_label_data(
    request, character_pk: int, character: Character, label_id: int
) -> JsonResponse:
    if label_id == MAIL_LABEL_ID_ALL_MAILS:
        mail_headers_qs = character.mails.all()
    else:
        mail_headers_qs = character.mails.filter(labels__label_id=label_id)

    return _character_mail_headers_data(request, character, mail_headers_qs)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_mail_headers_by_list_data(
    request, character_pk: int, character: Character, list_id: int
) -> JsonResponse:
    mail_headers_qs = character.mails.filter(recipients__mailing_list__list_id=list_id)
    return _character_mail_headers_data(request, character, mail_headers_qs)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_mail_data(
    request, character_pk: int, character: Character, mail_pk: int
) -> JsonResponse:
    try:
        mail = character.mails.get(pk=mail_pk)
    except CharacterMail.DoesNotExist:
        error_msg = f"Mail with pk {mail_pk} not found for character {character}"
        logger.warning(error_msg)
        return HttpResponseNotFound(error_msg)

    data = {
        "mail_id": mail.mail_id,
        "labels": list(mail.labels.values_list("label_id", flat=True)),
        "from": mail.from_entity.name,
        "to": ", ".join(
            sorted(
                [
                    str(obj)
                    for obj in mail.recipients.select_related(
                        "eve_entity", "mailing_list"
                    )
                ]
            )
        ),
        "subject": mail.subject,
        "sent": mail.timestamp.isoformat(),
        "body": mail.body_html if mail.body != "" else "(no data yet)",
    }
    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_skillqueue_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    data = list()
    try:
        for row in character.skillqueue.select_related("eve_type").filter(
            character_id=character_pk
        ):
            level_roman = MAP_SKILL_LEVEL_ARABIC_TO_ROMAN[row.finished_level]
            skill_str = f"{row.eve_type.name}&nbsp;{level_roman}"
            if row.is_active:
                skill_str += " [ACTIVE]"

            if row.finish_date:
                finish_date_humanized = humanize.naturaltime(
                    dt.datetime.now()
                    + dt.timedelta(
                        seconds=(
                            row.finish_date.timestamp() - dt.datetime.now().timestamp()
                        )
                    )
                )
                finish_date_str = (
                    f"{row.finish_date.strftime(DATETIME_FORMAT)} "
                    f"({finish_date_humanized})"
                )
                finish_date_sort = row.finish_date.isoformat()
            else:
                finish_date_str = gettext("(training not active)")
                finish_date_sort = None

            data.append(
                {
                    "position": row.queue_position + 1,
                    "skill": skill_str,
                    "finished": {
                        "display": finish_date_str,
                        "sort": finish_date_sort,
                    },
                    "is_active": row.is_active,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_skills_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    skills_data = list()
    try:
        for skill in character.skills.select_related(
            "eve_type", "eve_type__eve_group"
        ).filter(active_skill_level__gte=1):
            level_str = MAP_SKILL_LEVEL_ARABIC_TO_ROMAN[skill.active_skill_level]
            skill_name = f"{skill.eve_type.name} {level_str}"
            skills_data.append(
                {
                    "group": skill.eve_type.eve_group.name,
                    "skill": skill.eve_type.name,
                    "skill_name": skill_name,
                    "level": skill.active_skill_level,
                    "level_str": level_str,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(skills_data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_wallet_journal_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    wallet_data = list()
    try:
        for row in character.wallet_journal.select_related(
            "first_party", "second_party"
        ).all():
            first_party = row.first_party.name if row.first_party else "-"
            second_party = row.second_party.name if row.second_party else "-"
            wallet_data.append(
                {
                    "date": row.date.isoformat(),
                    "ref_type": row.ref_type.replace("_", " ").title(),
                    "first_party": first_party,
                    "second_party": second_party,
                    "amount": row.amount,
                    "balance": row.balance,
                    "description": row.description,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(wallet_data, safe=False)


#############################
# Section: Character Finder


@login_required
@permission_required("memberaudit.finder_access")
def character_finder(request) -> HttpResponse:
    context = {
        "page_title": "Character Finder",
    }
    return render(
        request,
        "memberaudit/character_finder.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.finder_access")
def character_finder_data(request) -> JsonResponse:
    character_list = list()
    for character in (
        Character.objects.user_has_access(user=request.user)
        .select_related(
            "character_ownership__character",
            "character_ownership__user",
            "character_ownership__user__profile__main_character",
            "character_ownership__user__profile__state",
        )
        .prefetch_related(
            "location",
            "location__eve_solar_system",
            "location__eve_solar_system__eve_constellation__eve_region",
        )
    ):
        auth_character = character.character_ownership.character
        character_viewer_url = reverse(
            "memberaudit:character_viewer", args=[character.pk]
        )
        actions_html = create_fa_button_html(
            url=character_viewer_url,
            fa_code="fas fa-search",
            button_type="primary",
        )
        alliance_name = (
            auth_character.alliance_name if auth_character.alliance_name else ""
        )
        character_organization = format_html(
            "{}<br><em>{}</em>", auth_character.corporation_name, alliance_name
        )
        character_html = create_icon_plus_name_html(
            auth_character.portrait_url(),
            auth_character.character_name,
            avatar=True,
            url=character_viewer_url,
        )
        user_profile = character.character_ownership.user.profile
        try:
            main_html = create_icon_plus_name_html(
                user_profile.main_character.portrait_url(),
                user_profile.main_character.character_name,
                avatar=True,
            )

        except AttributeError:
            main_html = ""

        try:
            location_name = (
                character.location.location.name if character.location.location else ""
            )
            solar_system_html = eve_solar_system_to_html(
                character.location.eve_solar_system
            )
            location_html = format_html("{}<br>{}", location_name, solar_system_html)
            solar_system_name = character.location.eve_solar_system.name
            region_name = (
                character.location.eve_solar_system.eve_constellation.eve_region.name
            )
        except ObjectDoesNotExist:
            location_html = ""
            solar_system_name = ""
            region_name = ""

        character_list.append(
            {
                "character_pk": character.pk,
                "character": {
                    "display": character_html,
                    "sort": auth_character.character_name,
                },
                "character_organization": character_organization,
                "main": main_html,
                "state_name": user_profile.state.name,
                "location": location_html,
                "actions": actions_html,
                "corporation_name": auth_character.corporation_name,
                "alliance_name": alliance_name,
                "solar_system_name": solar_system_name,
                "region_name": region_name,
            }
        )
    return JsonResponse(character_list, safe=False)


#############################
# Section: Reports


def _report_user_qs(request):
    if request.user.has_perm("memberaudit.view_everything"):
        users_qs = User.objects.all()
    else:
        users_qs = User.objects.none()
        if (
            request.user.has_perm("memberaudit.view_same_alliance")
            and request.user.profile.main_character.alliance_id
        ):
            users_qs = User.objects.select_related("profile__main_character").filter(
                profile__main_character__alliance_id=request.user.profile.main_character.alliance_id
            )
        elif request.user.has_perm("memberaudit.view_same_corporation"):
            users_qs = User.objects.select_related("profile__main_character").filter(
                profile__main_character__corporation_id=request.user.profile.main_character.corporation_id
            )

    return users_qs


@login_required
@permission_required("memberaudit.reports_access")
def reports(request) -> HttpResponse:
    context = {
        "page_title": "Reports",
    }
    return render(
        request,
        "memberaudit/reports.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.reports_access")
def compliance_report_data(request) -> JsonResponse:
    users_qs = _report_user_qs(request)

    member_users = (
        users_qs.filter(profile__state__name="Member")
        .annotate(total_chars=Count("character_ownerships"))
        .annotate(
            unregistered_chars=Count(
                "character_ownerships",
                filter=Q(character_ownerships__memberaudit_character=None),
            )
        )
        .select_related("profile__main_character")
    )

    user_data = list()
    for user in member_users:
        try:
            main_character = user.profile.main_character
        except AttributeError:
            continue

        main_html = create_icon_plus_name_html(
            main_character.portrait_url(),
            main_character.character_name,
            avatar=True,
        )
        organization_html = create_main_organization_html(main_character)
        user_data.append(
            {
                "user_pk": user.pk,
                "main": {
                    "display": main_html,
                    "sort": main_character.character_name,
                },
                "organization": {
                    "display": organization_html,
                    "sort": main_character.corporation_name,
                },
                "corporation_name": main_character.corporation_name,
                "alliance_name": main_character.alliance_name,
                "total_chars": user.total_chars,
                "unregistered_chars": user.unregistered_chars,
                "is_compliant": user.unregistered_chars == 0,
                "compliance_str": "yes" if user.unregistered_chars == 0 else "no",
            }
        )

    return JsonResponse(user_data, safe=False)


@login_required
@permission_required("memberaudit.reports_access")
def doctrines_report_data(request) -> JsonResponse:
    def create_data_row(doctrine) -> dict:
        user = character.character_ownership.user
        auth_character = character.character_ownership.character
        main_character = user.profile.main_character
        main_html = create_icon_plus_name_html(
            user.profile.main_character.portrait_url(),
            main_character.character_name,
            avatar=True,
        )
        main_corporation = main_character.corporation_name
        main_alliance = (
            main_character.alliance_name if main_character.alliance_name else ""
        )
        organization_html = format_html(
            "{}{}",
            main_corporation,
            f" [{main_character.alliance_ticker}]"
            if main_character.alliance_name
            else "",
        )
        character_viewer_url = "{}?tab=doctrines".format(
            reverse("memberaudit:character_viewer", args=[character.pk])
        )
        character_html = create_icon_plus_name_html(
            auth_character.portrait_url(),
            auth_character.character_name,
            avatar=True,
            url=character_viewer_url,
        )
        doctrine_pk = doctrine.pk if doctrine else 0
        can_fly = [
            create_icon_plus_name_html(
                obj.ship.ship_type.icon_url(DEFAULT_ICON_SIZE)
                if obj.ship.ship_type
                else "",
                obj.ship.name,
            )
            for obj in doctrine_ship_qs
        ]
        can_fly_html = (
            "<br>".join(can_fly)
            if can_fly
            else '<i class="fas fa-times boolean-icon-false"></i>'
        )
        return {
            "id": f"{doctrine_pk}_{character.pk}",
            "doctrine": doctrine.name if doctrine else NO_DOCTRINE_NAME,
            "main": main_character.character_name,
            "main_html": main_html,
            "organization_html": organization_html,
            "corporation": main_corporation,
            "alliance": main_alliance,
            "character": character.character_ownership.character.character_name,
            "character_html": character_html,
            "can_fly": can_fly_html,
            "can_fly_str": yesno_str(bool(can_fly)),
        }

    users_qs = _report_user_qs(request)
    data = list()

    character_qs = (
        Character.objects.select_related("character_ownership__user")
        .select_related(
            "character_ownership__user",
            "character_ownership__user__profile__main_character",
            "character_ownership__character",
        )
        .prefetch_related("doctrine_ships")
        .filter(character_ownership__user__in=users_qs)
    )

    my_select_related = "ship", "ship__ship_type"
    for doctrine in Doctrine.objects.all():
        for character in character_qs:
            doctrine_ship_qs = (
                character.doctrine_ships.select_related(*my_select_related)
                .filter(ship__doctrines=doctrine, insufficient_skills__isnull=True)
                .order_by("ship__name")
            )
            data.append(create_data_row(doctrine))

    for character in character_qs:
        if (
            character.doctrine_ships.select_related(*my_select_related)
            .filter(ship__doctrines__isnull=True)
            .exists()
        ):
            doctrine_ship_qs = character.doctrine_ships.filter(
                ship__doctrines__isnull=True, insufficient_skills__isnull=True
            ).order_by("ship__name")
            data.append(create_data_row(None))

    return JsonResponse(data, safe=False)
