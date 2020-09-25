from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required

from allianceauth.authentication.models import CharacterOwnership, User
from allianceauth.eveonline.models import EveCharacter
from esi.decorators import token_required

from .models import *
from .utils import messages_plus
from . import tasks, __title__


@login_required
@permission_required("memberaudit.basic_access")
def index(request):
    return redirect("memberaudit:registration")


@login_required
@permission_required("memberaudit.basic_access")
def registration(request):

    owned_chars_query = CharacterOwnership.objects.filter(user=request.user).order_by(
        "character__character_name"
    )

    has_registered_chars = owned_chars_query.count() > 0

    characters = list()
    unregistered_chars = 0
    for owned_char in owned_chars_query:

        is_registered = hasattr(owned_char, "memberaudit_owner")
        if not is_registered:
            unregistered_chars += 1

        characters.append(
            {
                "portrait_url": owned_char.character.portrait_url,
                "name": owned_char.character.character_name,
                "is_registered": is_registered,
                "pk": owned_char.character.pk,
            }
        )

    context = {
        "app_title": __title__,
        "characters": characters,
        "has_registered_chars": has_registered_chars,
        "unregistered_chars": unregistered_chars,
    }

    return render(request, "memberaudit/register.html", context)


@login_required
@permission_required("memberaudit.basic_access")
@token_required(scopes=Owner.get_esi_scopes())
def add_owner(request, token):
    token_char = EveCharacter.objects.get(character_id=token.character_id)

    success = True
    try:
        owned_char = CharacterOwnership.objects.get(
            user=request.user, character=token_char
        )
    except CharacterOwnership.DoesNotExist:
        messages_plus.error(
            request,
            "You can register your main or alt characters."
            + "However, character <strong>{}</strong> is neither. ".format(
                token_char.character_name
            ),
        )
        success = False

    with transaction.atomic():
        owner, created = Owner.objects.update_or_create(character=owned_char)

    tasks.sync_owner.delay(owner_pk=owner.pk, force_sync=True)
    messages_plus.success(
        request, "<strong>{}</strong> has been registered ".format(owner)
    )

    return redirect("memberaudit:index")


@login_required
@permission_required("memberaudit.basic_access")
def compliance_report(request):
    context = {"app_title": __title__}

    return render(request, "memberaudit/compliance_report.html", context)


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
