"""
views for character_finder actions
"""

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from memberaudit.helpers import eve_solar_system_to_html
from memberaudit.models import Character
from memberaudit.utils import create_fa_button_html, yesno_str
from memberaudit.views.definitions import add_common_context, create_icon_plus_name_html


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
        user_profile = character.character_ownership.user.profile
        try:
            main_html = create_icon_plus_name_html(
                user_profile.main_character.portrait_url(),
                user_profile.main_character.character_name,
                avatar=True,
            )

        except AttributeError:
            main_html = ""

        text = format_html(
            "{}&nbsp;{}",
            mark_safe('&nbsp;<i class="fas fa-crown" title="Main character">')
            if character.is_main
            else "",
            mark_safe('&nbsp;<i class="far fa-eye" title="Shared character">')
            if character.is_shared
            else "",
        )
        character_html = create_icon_plus_name_html(
            auth_character.portrait_url(),
            auth_character.character_name,
            avatar=True,
            url=character_viewer_url,
            text=text,
        )

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
                "main_str": yesno_str(character.is_main),
            }
        )
    return JsonResponse(character_list, safe=False)
