# coding=utf-8

"""
views for reports actions
"""

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html

from eveuniverse.core import eveimageserver

from memberaudit.models import Character, SkillSetGroup, accessible_users
from memberaudit.utils import yesno_str
from memberaudit.views.definitions import (
    DEFAULT_ICON_SIZE,
    SKILL_SET_DEFAULT_ICON_TYPE_ID,
    UNGROUPED_SKILL_SET,
    add_common_context,
    create_icon_plus_name_html,
    create_main_organization_html,
)


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
    users_and_character_counts = (
        accessible_users(request.user)
        .annotate(total_chars=Count("character_ownerships__character", distinct=True))
        .annotate(
            unregistered_chars=Count(
                "character_ownerships",
                filter=Q(character_ownerships__memberaudit_character=None),
                distinct=True,
            )
        )
        .select_related("profile__main_character")
    )

    user_data = list()
    for user in users_and_character_counts:
        if user.profile.main_character:
            main_character = user.profile.main_character
            main_name = main_character.character_name
            main_html = create_icon_plus_name_html(
                main_character.portrait_url(),
                main_character.character_name,
                avatar=True,
            )
            corporation_name = main_character.corporation_name
            organization_html = create_main_organization_html(main_character)
            alliance_name = (
                main_character.alliance_name if main_character.alliance_name else ""
            )

            is_compliant = user.unregistered_chars == 0
        else:
            main_html = main_name = user.username
            alliance_name = organization_html = corporation_name = ""
            is_compliant = False

        is_registered = user.unregistered_chars < user.total_chars

        user_data.append(
            {
                "id": user.pk,
                "main": {
                    "display": main_html,
                    "sort": main_name,
                },
                "organization": {
                    "display": organization_html,
                    "sort": corporation_name,
                },
                "corporation_name": corporation_name,
                "alliance_name": alliance_name,
                "total_chars": user.total_chars,
                "unregistered_chars": user.unregistered_chars,
                "is_registered": is_registered,
                "registered_str": yesno_str(is_registered),
                "is_compliant": is_compliant,
                "compliance_str": yesno_str(is_compliant),
            }
        )

    return JsonResponse(user_data, safe=False)


@login_required
@permission_required("memberaudit.reports_access")
def skill_sets_report_data(request) -> JsonResponse:
    def create_data_row(group) -> dict:
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
        character_viewer_url = "{}?tab=skill_sets".format(
            reverse("memberaudit:character_viewer", args=[character.pk])
        )
        character_html = create_icon_plus_name_html(
            auth_character.portrait_url(),
            auth_character.character_name,
            avatar=True,
            url=character_viewer_url,
        )
        group_pk = group.pk if group else 0
        has_required = [
            create_icon_plus_name_html(
                obj.skill_set.ship_type.icon_url(DEFAULT_ICON_SIZE)
                if obj.skill_set.ship_type
                else eveimageserver.type_icon_url(
                    SKILL_SET_DEFAULT_ICON_TYPE_ID, size=DEFAULT_ICON_SIZE
                ),
                obj.skill_set.name,
            )
            for obj in skill_set_qs
        ]
        has_required_html = (
            "<br>".join(has_required)
            if has_required
            else '<i class="fas fa-times boolean-icon-false"></i>'
        )
        return {
            "id": f"{group_pk}_{character.pk}",
            "group": group.name_plus if group else UNGROUPED_SKILL_SET,
            "main": main_character.character_name,
            "main_html": main_html,
            "organization_html": organization_html,
            "corporation": main_corporation,
            "alliance": main_alliance,
            "character": character.character_ownership.character.character_name,
            "character_html": character_html,
            "has_required": has_required_html,
            "has_required_str": yesno_str(bool(has_required)),
            "is_doctrine_str": yesno_str(group.is_doctrine if group else False),
        }

    data = list()

    character_qs = (
        Character.objects.select_related("character_ownership__user")
        .select_related(
            "character_ownership__user",
            "character_ownership__user__profile__main_character",
            "character_ownership__character",
        )
        .prefetch_related("skill_set_checks")
        .filter(character_ownership__user__in=list(accessible_users(request.user)))
    )

    my_select_related = "skill_set", "skill_set__ship_type"
    for group in SkillSetGroup.objects.all():
        for character in character_qs:
            skill_set_qs = (
                character.skill_set_checks.select_related(*my_select_related)
                .filter(skill_set__groups=group, failed_required_skills__isnull=True)
                .order_by("skill_set__name")
            )
            data.append(create_data_row(group))

    for character in character_qs:
        if (
            character.skill_set_checks.select_related(*my_select_related)
            .filter(skill_set__groups__isnull=True)
            .exists()
        ):
            skill_set_qs = character.skill_set_checks.filter(
                skill_set__groups__isnull=True, failed_required_skills__isnull=True
            ).order_by("skill_set__name")
            data.append(create_data_row(None))

    return JsonResponse(data, safe=False)
