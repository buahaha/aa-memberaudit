import datetime as dt
import humanize

from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count, Q, F, Max
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
from django.views.decorators.cache import cache_page

from bravado.exception import HTTPError
from esi.decorators import token_required

from allianceauth.authentication.models import CharacterOwnership, User
from allianceauth.eveonline.models import EveCharacter
from allianceauth.eveonline.evelinks import dotlan
from allianceauth.services.hooks import get_extension_logger

from . import tasks, __title__
from .constants import EVE_CATEGORY_ID_SHIP
from .decorators import fetch_character_if_allowed
from .helpers import eve_solar_system_to_html
from .models import (
    Character,
    CharacterAsset,
    CharacterContract,
    CharacterMail,
    Location,
)
from .utils import (
    messages_plus,
    LoggerAddTag,
    create_link_html,
    DATETIME_FORMAT,
    create_fa_button_html,
    yesno_str,
)


logger = LoggerAddTag(get_extension_logger(__name__), __title__)
MY_DATETIME_FORMAT = "Y-M-d H:i"


def create_img_html(src: str, classes: list) -> str:
    classes_str = 'class="{}"'.format(" ".join(classes)) if classes else ""
    return f'<img {classes_str}src="{str(src)}">'


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    unregistered_count = Character.objects.unregistered_characters_of_user_count(
        request.user
    )
    new_context = {
        **{
            "app_title": __title__,
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
            character = None
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

    context = {
        "page_title": "My Characters",
        "auth_characters": auth_characters,
        "has_auth_characters": has_auth_characters,
        "unregistered_chars": unregistered_chars,
        "has_registered_characters": len(auth_characters) > 0,
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


def _character_location_to_html(character: Character, category: str) -> str:
    """fetches current character location
    and returns either as solar system or location in HTML
    """
    try:
        solar_system, location = character.fetch_location()
    except HTTPError:
        logger.warning("Network error", exc_info=True)
        html = '<p class="text-danger">Network error</p>'
    except Exception as ex:
        logger.warning(f"Unexpected error: {ex}", exc_info=True)
        html = '<p class="text-danger">Unexpected error</p>'
    else:
        if category == "solar_system":
            html = eve_solar_system_to_html(solar_system)
        elif location:
            html = location.name
        else:
            html = "-"

    return html


@cache_page(30)
@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_solar_system_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    return HttpResponse(_character_location_to_html(character, "solar_system"))


@cache_page(30)
@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_location_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    return HttpResponse(_character_location_to_html(character, "location"))


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed(
    "details",
    "wallet_balance",
    "skillpoints",
    "character_ownership__user__profile__main_character",
)
def character_viewer(request, character_pk: int, character: Character):
    corporation_history = list()
    for entry in (
        character.corporation_history.exclude(is_deleted=True)
        .select_related("corporation")
        .order_by("start_date")
    ):
        if len(corporation_history) > 0:
            corporation_history[-1]["end_date"] = entry.start_date
            corporation_history[-1]["is_last"] = False

        corporation_history.append(
            {
                "corporation_html": create_link_html(
                    dotlan.corporation_url(entry.corporation.name),
                    entry.corporation.name,
                ),
                "start_date": entry.start_date,
                "end_date": now(),
                "is_last": True,
            }
        )

    try:
        character_details = character.details
    except ObjectDoesNotExist:
        character_details = None

    auth_character = character.character_ownership.character
    if character.character_ownership.user.profile.main_character:
        main_character = character.character_ownership.user.profile.main_character
        main = f"[{main_character.corporation_ticker}] {main_character.character_name}"
    else:
        main = "-"

    # skill queue
    skill_queue = list()

    map_skillevel_arabic_to_roman = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}

    for row in (
        character.skillqueue.select_related("skill")
        .filter(character_id=character_pk)
        .order_by("queue_position")
    ):
        is_currently_trained_skill = False
        if row.is_active:
            is_currently_trained_skill = True

        finish_date_humanized = None
        if row.finish_date:
            finish_date_humanized = humanize.naturaltime(
                dt.datetime.now()
                + dt.timedelta(
                    seconds=(
                        row.finish_date.timestamp() - dt.datetime.now().timestamp()
                    )
                )
            )

        skill_queue.append(
            {
                "finish_date": row.finish_date,
                "finish_date_humanized": finish_date_humanized,
                "finished_level": map_skillevel_arabic_to_roman[row.finished_level],
                "skill": row.skill.name,
                "is_currently_trained_skill": is_currently_trained_skill,
            }
        )

    registered_characters = list(
        Character.objects.select_related(
            "character_ownership", "character_ownership__character"
        )
        .filter(character_ownership__user=character.character_ownership.user)
        .order_by("character_ownership__character__character_name")
        .values(
            "pk",
            name=F("character_ownership__character__character_name"),
            character_id=F("character_ownership__character__character_id"),
        )
    )

    context = {
        "page_title": "Character Sheet",
        "character": character,
        "auth_character": auth_character,
        "character_details": character_details,
        "corporation_history": reversed(corporation_history),
        "skill_queue": skill_queue,
        "main": main,
        "registered_characters": registered_characters,
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
        asset_qs = character.assets.select_related(
            "eve_type",
            "eve_type__eve_group",
            "eve_type__eve_group__eve_category",
            "location",
            "location__eve_solar_system__eve_constellation__eve_region",
        ).filter(location__isnull=False)

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

        data.append(
            {
                "item_id": asset.item_id,
                "location": location_name,
                "icon": create_img_html(asset.eve_type.icon_url(32), []),
                "name": asset.name_display,
                "quantity": asset.quantity if not asset.is_singleton else "",
                "group": asset.group_display,
                "volume": asset.eve_type.volume,
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
    return render(request, "memberaudit/character_asset_container.html", context)


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
        assets_qs = parent_asset.children.select_related(
            "eve_type", "eve_type__eve_group", "eve_type__eve_group__eve_category"
        )
    except ObjectDoesNotExist:
        return HttpResponseNotFound()

    for asset in assets_qs:
        data.append(
            {
                "item_id": asset.item_id,
                "icon": create_img_html(asset.eve_type.icon_url(32), []),
                "name": asset.name_display,
                "quantity": asset.quantity if not asset.is_singleton else "",
                "group": asset.group_display,
                "volume": asset.eve_type.volume,
            }
        )

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
            .prefetch_related("items", "bids")
            .get(pk=contract_pk)
        )
    except CharacterContract.DoesNotExist:
        error_msg = (
            f"Contract with pk {contract_pk} not found for character {character}"
        )
        logger.warning(error_msg)
        context = {
            "error": error_msg,
        }
    else:
        items_included = None
        items_requested = None
        if contract.contract_type in [
            CharacterContract.TYPE_ITEM_EXCHANGE,
            CharacterContract.TYPE_AUCTION,
        ]:
            try:
                items_qs = contract.items.select_related(
                    "eve_type",
                    "eve_type__eve_group",
                    "eve_type__eve_group__eve_category",
                ).values(
                    "quantity",
                    "eve_type_id",
                    name=F("eve_type__name"),
                    group=F("eve_type__eve_group__name"),
                    category=F("eve_type__eve_group__eve_category__name"),
                )
                items_included = items_qs.filter(is_included=True)
                items_requested = items_qs.filter(is_included=False)
            except ObjectDoesNotExist:
                pass

        current_bid = None
        bids_count = None
        if contract.contract_type == CharacterContract.TYPE_AUCTION:
            try:
                current_bid = (
                    contract.bids.all().aggregate(Max("amount")).get("amount__max")
                )
                bids_count = contract.bids.count()
            except ObjectDoesNotExist:
                pass

        context = {
            "contract": contract,
            "contract_summary": contract.summary(),
            "MY_DATETIME_FORMAT": MY_DATETIME_FORMAT,
            "items_included": items_included,
            "items_requested": items_requested,
            "current_bid": current_bid,
            "bids_count": bids_count,
        }
    return render(
        request,
        "memberaudit/character_contract_details.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_jump_clones_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    data = list()
    try:
        for jump_clone in character.jump_clones.select_related(
            "location",
            "location__eve_solar_system",
            "location__eve_solar_system__eve_constellation__eve_region",
        ).all():
            if not jump_clone.location.is_empty:
                eve_solar_system = jump_clone.location.eve_solar_system
                solar_system = eve_solar_system_to_html(
                    eve_solar_system, show_region=False
                )
                region = eve_solar_system.eve_constellation.eve_region.name
            else:
                solar_system = "-"
                region = "-"

            implants = "<br>".join(
                sorted(
                    [
                        obj.eve_type.name
                        for obj in jump_clone.implants.select_related("eve_type")
                    ]
                )
            )
            if not implants:
                implants = "(none)"

            data.append(
                {
                    "jump_clone_id": jump_clone.jump_clone_id,
                    "region": region,
                    "solar_system": solar_system,
                    "location": jump_clone.location.name_plus,
                    "implants": implants,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_mail_headers_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    mails_data = list()
    try:
        for mail in character.mails.select_related(
            "from_entity", "from_mailing_list", "from_mailing_list"
        ).all():
            mail_ajax_url = reverse(
                "memberaudit:character_mail_data", args=[character.pk, mail.pk]
            )

            actions_html = (
                '<button type="button" class="btn btn-primary" '
                'data-toggle="modal" data-target="#modalCharacterMail" '
                f"data-ajax_mail_body={mail_ajax_url}>"
                '<i class="fas fa-search"></i></button>'
            )

            mails_data.append(
                {
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
                    "sent": mail.timestamp.strftime(DATETIME_FORMAT),
                    "action": actions_html,
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(mails_data, safe=False)


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
def character_skills_data(
    request, character_pk: int, character: Character
) -> JsonResponse:
    skills_data = list()
    try:
        for skill in character.skills.select_related(
            "eve_type", "eve_type__eve_group"
        ).all():
            skills_data.append(
                {
                    "group": skill.eve_type.eve_group.name,
                    "skill": skill.eve_type.name,
                    "level": skill.trained_skill_level,
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
# Section: Analysis


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
    if request.user.has_perm("memberaudit.view_everyhing"):
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
        if user.profile.main_character:
            portrait_html = create_img_html(
                user.profile.main_character.portrait_url(), ["ra-avatar", "img-circle"]
            )
            main_character = user.profile.main_character
            user_data.append(
                {
                    "user_pk": user.pk,
                    "portrait": portrait_html,
                    "name": user.username,
                    "main": main_character.character_name,
                    "corporation": main_character.corporation_name,
                    "alliance": main_character.alliance_name,
                    "total_chars": user.total_chars,
                    "unregistered_chars": user.unregistered_chars,
                    "is_compliant": user.unregistered_chars == 0,
                    "compliance_str": "yes" if user.unregistered_chars == 0 else "no",
                }
            )

    return JsonResponse(user_data, safe=False)


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
    for character in Character.objects.user_has_access(
        user=request.user
    ).select_related(
        "character_ownership__character",
        "character_ownership__user",
        "character_ownership__user__profile__main_character",
        "character_ownership__user__profile__state",
    ):
        auth_character = character.character_ownership.character
        user_profile = character.character_ownership.user.profile
        portrait_html = create_img_html(
            auth_character.portrait_url(), ["ra-avatar", "img-circle"]
        )
        character_viewer_url = reverse(
            "memberaudit:character_viewer", args=[character.pk]
        )
        actions_html = create_fa_button_html(
            url=character_viewer_url,
            fa_code="fas fa-search",
            button_type="primary",
        )
        alliance_name = (
            auth_character.alliance_name if auth_character.alliance_name else "-"
        )
        character_link = create_link_html(
            character_viewer_url, auth_character.character_name, new_window=False
        )
        character_list.append(
            {
                "character_pk": character.pk,
                "portrait": portrait_html,
                "character_name": character_link,
                "corporation_name": auth_character.corporation_name,
                "alliance_name": alliance_name,
                "main_name": user_profile.main_character.character_name,
                "state_name": user_profile.state.name,
                "actions": actions_html,
            }
        )
    return JsonResponse(character_list, safe=False)
