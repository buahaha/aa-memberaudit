from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count, Q, F
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
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
from .decorators import fetch_character_if_allowed
from .models import Character
from .utils import (
    messages_plus,
    LoggerAddTag,
    create_link_html,
    DATETIME_FORMAT,
    create_fa_button_html,
)


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def create_img_html(src: str, classes: list) -> str:
    classes_str = 'class="{}"'.format(" ".join(classes)) if classes else ""
    return f'<img {classes_str}src="{str(src)}">'


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    unregistered_count = Character.objects.unregistered_characters_of_user_count(
        request.user
    )
    registered_characters = list(
        Character.objects.select_related(
            "character_ownership", "character_ownership__character"
        )
        .filter(character_ownership__user=request.user)
        .order_by("character_ownership__character__character_name")
        .values("pk", name=F("character_ownership__character__character_name"))
    )
    new_context = {
        **{
            "app_title": __title__,
            "unregistered_count": unregistered_count,
            "registered_characters": registered_characters,
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
def launcher(request):
    owned_chars_query = (
        CharacterOwnership.objects.filter(user=request.user)
        .select_related("character")
        .order_by("character__character_name")
    )
    has_registered_chars = owned_chars_query.count() > 0

    characters = list()
    unregistered_chars = 0
    for character_ownership in owned_chars_query:

        is_registered = hasattr(character_ownership, "memberaudit_owner")
        if not is_registered:
            unregistered_chars += 1

        character_pk = character_ownership.memberaudit_owner.pk if is_registered else 0
        characters.append(
            {
                "portrait_url": character_ownership.character.portrait_url,
                "name": character_ownership.character.character_name,
                "is_registered": is_registered,
                "pk": character_ownership.character.pk,
                "character_id": character_ownership.character.character_id,
                "character_pk": character_pk,
            }
        )

    context = {
        "page_title": "My Characters",
        "characters": characters,
        "has_registered_chars": has_registered_chars,
        "unregistered_chars": unregistered_chars,
    }

    """
    if has_registered_chars:
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
def add_owner(request, token):
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    try:
        character_ownership = CharacterOwnership.objects.get(
            user=request.user, character=token_char
        )
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

        tasks.update_character.delay(character_pk=character.pk, user_pk=request.user.pk)
        messages_plus.success(
            request,
            format_html(
                "<strong>{}</strong> has been registered and sync for this character "
                "has started. "
                "Syncing can take a while and "
                "you will receive a notification once sync has completed.",
                character.character_ownership.character,
            ),
        )

    return redirect("memberaudit:launcher")


@cache_page(30)
@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_location_data(
    request, character_pk: int, character: Character
) -> HttpResponse:
    try:
        solar_system, _ = character.fetch_location()
    except HTTPError:
        logger.warning("Network error", exc_info=True)
        html = '<p class="text-danger">Network error</p>'
    except Exception as ex:
        logger.warning(f"Unexpected error: {ex}", exc_info=True)
        html = '<p class="text-danger">Unexpected error</p>'
    else:
        if solar_system.is_high_sec:
            color = "green"
        elif solar_system.is_low_sec:
            color = "orange"
        else:
            color = "red"

        html = format_html(
            '{} <span style="color: {}">{}</span> / {}',
            create_link_html(
                dotlan.solar_system_url(solar_system.name), solar_system.name
            ),
            color,
            round(solar_system.security_status, 1),
            solar_system.eve_constellation.eve_region.name,
        )

    return HttpResponse(html)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed(
    "character_ownership__character",
    "details",
)
def character_main(request, character_pk: int, character: Character):
    corporation_history = list()
    for entry in (
        character.corporation_history.exclude(is_deleted=True)
        .select_related("corporation")
        .order_by("start_date")
    ):
        if len(corporation_history) > 0:
            corporation_history[-1]["end_date"] = entry.start_date

        corporation_history.append(
            {
                "corporation_html": create_link_html(
                    dotlan.corporation_url(entry.corporation.name),
                    entry.corporation.name,
                ),
                "start_date": entry.start_date,
                "end_date": now(),
            }
        )

    try:
        character_details = character.details
    except ObjectDoesNotExist:
        character_details = None

    auth_character = character.character_ownership.character
    context = {
        "page_title": auth_character.character_name,
        "character": character,
        "auth_character": auth_character,
        "character_details": character_details,
        "corporation_history": reversed(corporation_history),
    }
    return render(
        request,
        "memberaudit/character_main.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_mails_data(request, character_pk: int, character: Character):
    mails_data = list()
    try:
        for mail in character.mails.select_related(
            "from_entity", "from_mailing_list", "from_mailing_list"
        ).all():
            mails_data.append(
                {
                    "mail_id": mail.mail_id,
                    "labels": list(mail.labels.values_list("label_id", flat=True)),
                    "from": mail.from_entity.name,
                    "to": list(
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
                }
            )
    except ObjectDoesNotExist:
        pass

    return JsonResponse(mails_data, safe=False)


@login_required
@permission_required("memberaudit.basic_access")
@fetch_character_if_allowed()
def character_skills_data(request, character_pk: int, character: Character):
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
def character_wallet_journal_data(request, character_pk: int, character: Character):
    wallet_data = list()
    try:
        for row in character.wallet_journal.select_related(
            "first_party", "second_party"
        ).all():
            first_party = row.first_party.name if row.first_party else "-"
            second_party = row.second_party.name if row.second_party else "-"
            wallet_data.append(
                {
                    "date": row.date.strftime(DATETIME_FORMAT),
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
@permission_required("memberaudit.unrestricted_access")
def reports(request):
    context = {
        "page_title": "Reports",
    }
    return render(
        request,
        "memberaudit/reports.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.unrestricted_access")
def compliance_report_data(request):
    member_users = (
        User.objects.filter(profile__state__name="Member")
        .annotate(total_chars=Count("character_ownerships"))
        .annotate(
            unregistered_chars=Count(
                "character_ownerships",
                filter=Q(character_ownerships__memberaudit_owner=None),
            )
        )
        .select_related()
    )

    # .annotate(registered_chars=Count('character_ownerships__memberaudit_owner'))

    user_data = list()
    for user in member_users:
        if user.profile.main_character:
            portrait_html = create_img_html(
                user.profile.main_character.portrait_url(), ["ra-avatar", "img-circle"]
            )
            main_character = user.profile.main_character
            user_data.append(
                {
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
@permission_required("memberaudit.unrestricted_access")
def character_finder(request):
    context = {
        "page_title": "Character Finder",
    }
    return render(
        request,
        "memberaudit/character_finder.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.unrestricted_access")
def character_finder_data(request):
    character_list = list()
    for character in Character.objects.all():
        auth_character = character.character_ownership.character
        user_profile = character.character_ownership.user.profile
        portrait_html = create_img_html(
            auth_character.portrait_url(), ["ra-avatar", "img-circle"]
        )
        actions_html = create_fa_button_html(
            url=reverse("memberaudit:character_main", args=[character.pk]),
            fa_code="fas fa-search",
            button_type="primary",
        )
        alliance = auth_character.alliance_name if auth_character.alliance_name else "-"
        character_list.append(
            {
                "portrait": portrait_html,
                "character": auth_character.character_name,
                "corporation": auth_character.corporation_name,
                "alliance": alliance,
                "main": user_profile.main_character.character_name,
                "state": user_profile.state.name,
                "actions": actions_html,
            }
        )
    return JsonResponse(character_list, safe=False)
