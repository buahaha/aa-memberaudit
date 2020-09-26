from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponse, Http404, HttpResponseForbidden
from django.shortcuts import render, redirect
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
from .models import Owner
from .utils import messages_plus, LoggerAddTag, create_link_html, DATETIME_FORMAT


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def add_common_context(request, context: dict) -> dict:
    """adds the common context used by all view"""
    unregistered_count = Owner.objects.unregistered_characters_of_user_count(
        request.user
    )
    new_context = {
        **{"app_title": __title__, "unregistered_count": unregistered_count},
        **context,
    }
    return new_context


@login_required
@permission_required("memberaudit.basic_access")
def index(request):
    return redirect("memberaudit:launcher")


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

        owner_pk = character_ownership.memberaudit_owner.pk if is_registered else 0
        characters.append(
            {
                "portrait_url": character_ownership.character.portrait_url,
                "name": character_ownership.character.character_name,
                "is_registered": is_registered,
                "pk": character_ownership.character.pk,
                "character_id": character_ownership.character.character_id,
                "owner_pk": owner_pk,
            }
        )

    context = {
        "page_title": "Launcher",
        "characters": characters,
        "has_registered_chars": has_registered_chars,
        "unregistered_chars": unregistered_chars,
    }

    return render(
        request, "memberaudit/launcher.html", add_common_context(request, context)
    )


@login_required
@permission_required("memberaudit.basic_access")
@token_required(scopes=Owner.get_esi_scopes())
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
            owner, _ = Owner.objects.update_or_create(
                character_ownership=character_ownership
            )

        tasks.sync_owner.delay(owner_pk=owner.pk, force_sync=True)
        messages_plus.success(
            request,
            format_html(
                "<strong>{}</strong> has been registered and sync for this character "
                "has started. "
                "Syncing can take a while and "
                "you will receive a notification once sync has completed.",
                owner.character_ownership.character,
            ),
        )

    return redirect("memberaudit:index")


@login_required
@permission_required("memberaudit.basic_access")
def activate_character(request, owner_pk: int):
    request.session["owner_pk"] = int(owner_pk)
    return redirect("memberaudit:character_main")


@login_required
@permission_required("memberaudit.basic_access")
def character_main(request):
    owner_pk = request.session.get("owner_pk")
    try:
        owner = Owner.objects.select_related(
            "character_ownership",
            "character_ownership__character",
            "owner_characters_detail",
            # "corporationhistory_set"
        ).get(pk=owner_pk)
    except Owner.DoesNotExist:
        raise Http404()

    if not owner.user_can_access(request.user):
        return HttpResponseForbidden()

    try:
        wallet_balance = owner.walletbalance.amount
    except ObjectDoesNotExist:
        wallet_balance = "(no data)"

    corporation_history = list()
    for entry in owner.corporationhistory_set.exclude(is_deleted=True).order_by(
        "start_date"
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

    context = {
        "page_title": "Character",
        "owner_pk": owner.pk,
        "character": owner.character_ownership.character,
        "character_details": owner.owner_characters_detail,
        "wallet_balance": wallet_balance,
        "corporation_history": reversed(corporation_history),
    }
    return render(
        request, "memberaudit/character_main.html", add_common_context(request, context)
    )


@login_required
@permission_required("memberaudit.basic_access")
def character_skills_data(request, owner_pk: int):
    try:
        owner = Owner.objects.select_related("skills").get(pk=owner_pk)
    except Owner.DoesNotExist:
        raise Http404()

    if not owner.user_can_access(request.user):
        return HttpResponseForbidden()

    skills_data = list()
    try:
        for skill in owner.skills.skill_set.all():
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
def character_wallet_journal_data(request, owner_pk: int):
    try:
        owner = Owner.objects.select_related("skills").get(pk=owner_pk)
    except Owner.DoesNotExist:
        raise Http404()

    if not owner.user_can_access(request.user):
        return HttpResponseForbidden()

    wallet_data = list()
    try:
        for row in owner.walletjournalentry_set.all():
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


@login_required
@permission_required("memberaudit.basic_access")
def compliance_report(request):
    context = {
        "page_title": "Compliance Report",
    }
    return render(
        request,
        "memberaudit/compliance_report.html",
        add_common_context(request, context),
    )


@login_required
@permission_required("memberaudit.basic_access")
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
            portrait_html = '<img class="ra-avatar img-circle" src="{}">'.format(
                user.profile.main_character.portrait_url()
            )
            user_data.append(
                {
                    "portrait": portrait_html,
                    "name": user.username,
                    "main": user.profile.main_character.character_name,
                    "corporation": user.profile.main_character.corporation_name,
                    "alliance": user.profile.main_character.alliance_name,
                    "total_chars": user.total_chars,
                    "unregistered_chars": user.unregistered_chars,
                    "is_compliant": user.unregistered_chars == 0,
                    "compliance_str": "yes" if user.unregistered_chars == 0 else "no",
                }
            )

    return JsonResponse(user_data, safe=False)


@cache_page(30)
@login_required
@permission_required("memberaudit.basic_access")
def character_location_data(request) -> HttpResponse:
    owner_pk = request.GET.get("owner_pk")
    try:
        owner = Owner.objects.select_related("character_ownership").get(pk=owner_pk)
    except Owner.DoesNotExist:
        html = '<p class="text-danger">Character not registered</p>'
    else:
        if not owner.user_can_access(request.user):
            html = '<p class="text-danger">Permission denied</p>'
        else:
            try:
                solar_system, _ = owner.fetch_location()
            except HTTPError:
                logger.warning("Network error", exc_info=True)
                html = '<p class="text-danger">Network error</p>'
            except Exception:
                logger.warning("Unexpected error", exc_info=True)
                html = '<p class="text-danger">Unexpected error</p>'
            else:
                html = format_html(
                    "{} {} / {}",
                    solar_system.name,
                    round(solar_system.security_status, 1),
                    solar_system.eve_constellation.eve_region.name,
                )

    return HttpResponse(html)
