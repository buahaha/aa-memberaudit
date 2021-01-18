from copy import deepcopy
from math import floor

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Avg, Count, F, ExpressionWrapper, Max, Min

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.services.hooks import get_extension_logger

from .. import __title__
from ..utils import LoggerAddTag, ObjectCacheMixin


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class CharacterManager(ObjectCacheMixin, models.Manager):
    def unregistered_characters_of_user_count(self, user: User) -> int:
        return CharacterOwnership.objects.filter(
            user=user, memberaudit_character__isnull=True
        ).count()

    def user_has_access(self, user: User) -> models.QuerySet:
        """Returns list of characters the given user has permission
        to access via character viewer
        """
        if user.has_perm("memberaudit.view_everything") and user.has_perm(
            "memberaudit.characters_access"
        ):
            qs = self.all()
        else:
            qs = self.select_related(
                "character_ownership__user",
            ).filter(character_ownership__user=user)
            if (
                user.has_perm("memberaudit.characters_access")
                and user.has_perm("memberaudit.view_same_alliance")
                and user.profile.main_character.alliance_id
            ):
                qs = qs | self.select_related(
                    "character_ownership__user__profile__main_character"
                ).filter(
                    character_ownership__user__profile__main_character__alliance_id=user.profile.main_character.alliance_id
                )
            elif user.has_perm("memberaudit.characters_access") and user.has_perm(
                "memberaudit.view_same_corporation"
            ):
                qs = qs | self.select_related(
                    "character_ownership__user__profile__main_character"
                ).filter(
                    character_ownership__user__profile__main_character__corporation_id=user.profile.main_character.corporation_id
                )

            if user.has_perm("memberaudit.view_shared_characters"):
                qs = qs | self.filter(is_shared=True)

        return qs


class CharacterUpdateStatusManager(models.Manager):
    def statistics(self) -> dict:
        """returns detailed statistics about the last update run and the app"""
        from ..models import (
            Character,
            CharacterAsset,
            CharacterMail,
            CharacterContract,
            CharacterContact,
            SkillSet,
            SkillSetGroup,
        )
        from .. import app_settings
        from django.conf import settings as auth_settings

        def root_task_id_or_none(obj):
            try:
                return obj.root_task_id
            except AttributeError:
                return None

        all_characters_count = Character.objects.count()

        settings = {
            name: value
            for name, value in vars(app_settings).items()
            if name.startswith("MEMBERAUDIT_")
        }
        schedule = deepcopy(auth_settings.CELERYBEAT_SCHEDULE)
        for name, details in schedule.items():
            for k, v in details.items():
                if k == "schedule":
                    schedule[name][k] = str(v)

        settings["CELERYBEAT_SCHEDULE"] = schedule

        qs_base = self.filter(
            is_success=True,
            started_at__isnull=False,
            finished_at__isnull=False,
        ).exclude(root_task_id="", parent_task_id="")
        root_task_ids = {
            ring: root_task_id_or_none(
                qs_base.filter(section__in=Character.sections_in_ring(ring))
                .order_by("-finished_at")
                .first()
            )
            for ring in range(1, 4)
        }
        duration_expression = ExpressionWrapper(
            F("finished_at") - F("started_at"),
            output_field=models.fields.DurationField(),
        )
        qs_base = qs_base.filter(root_task_id__in=root_task_ids.values()).annotate(
            duration=duration_expression
        )
        update_stats = dict()
        if self.count() > 0:
            # per ring
            for ring in range(1, 4):
                sections = Character.sections_in_ring(ring)

                # calc totals
                qs = qs_base.filter(section__in=sections)
                try:
                    first = qs.order_by("started_at").first()
                    last = qs.order_by("finished_at").last()
                    started_at = first.started_at
                    finshed_at = last.finished_at
                    duration = round((finshed_at - started_at).total_seconds(), 1)
                except (KeyError, AttributeError):
                    first = None
                    last = None
                    duration = None
                    started_at = None
                    finshed_at = None

                available_time = (
                    settings[f"MEMBERAUDIT_UPDATE_STALE_RING_{ring}"]
                    - settings["MEMBERAUDIT_UPDATE_STALE_OFFSET"]
                ) * 60
                throughput = (
                    floor(all_characters_count / duration * 3600) if duration else None
                )
                within_boundaries = duration < available_time if duration else None
                update_stats[f"ring_{ring}"] = {
                    "total": {
                        "duration": duration,
                        "started_at": started_at,
                        "finshed_at": finshed_at,
                        "root_task_id": root_task_ids.get(ring),
                        "throughput_est": throughput,
                        "available_time": available_time,
                        "within_available_time": within_boundaries,
                    },
                    "max": {},
                    "sections": {},
                }

                # add longest running section w/ character
                obj = qs.order_by("-duration").first()
                update_stats[f"ring_{ring}"]["max"] = self._info_from_obj(obj)

                # add first and last section
                update_stats[f"ring_{ring}"]["first"] = self._info_from_obj(first)
                update_stats[f"ring_{ring}"]["last"] = self._info_from_obj(last)

                # calc section stats
                for section in sections:
                    try:
                        section_max = round(
                            qs_base.filter(section=section)
                            .aggregate(Max("duration"))["duration__max"]
                            .total_seconds(),
                            1,
                        )
                        section_avg = round(
                            qs_base.filter(section=section)
                            .aggregate(Avg("duration"))["duration__avg"]
                            .total_seconds(),
                            1,
                        )
                        section_min = round(
                            qs_base.filter(section=section)
                            .aggregate(Min("duration"))["duration__min"]
                            .total_seconds(),
                            1,
                        )
                    except (KeyError, AttributeError):
                        section_max = (None,)
                        section_avg = None
                        section_min = None

                    update_stats[f"ring_{ring}"]["sections"].update(
                        {
                            str(section): {
                                "max": section_max,
                                "avg": section_avg,
                                "min": section_min,
                            }
                        }
                    )

                ring_characters_count = (
                    Character.objects.filter(update_status_set__in=qs)
                    .annotate(num_sections=Count("update_status_set__section"))
                    .filter(num_sections=len(sections))
                    .count()
                )
                update_stats[f"ring_{ring}"]["total"][
                    "characters_count"
                ] = ring_characters_count
                update_stats[f"ring_{ring}"]["total"]["completed"] = (
                    ring_characters_count == all_characters_count
                )

        return {
            "app_totals": {
                "users_count": User.objects.filter(
                    character_ownerships__memberaudit_character__isnull=False
                )
                .distinct()
                .count(),
                "all_characters_count": all_characters_count,
                "skill_set_groups_count": SkillSetGroup.objects.count(),
                "skill_sets_count": SkillSet.objects.count(),
                "assets_count": CharacterAsset.objects.count(),
                "mails_count": CharacterMail.objects.count(),
                "contacts_count": CharacterContact.objects.count(),
                "contracts_count": CharacterContract.objects.count(),
            },
            "settings": settings,
            "update_statistics": update_stats,
        }

    @staticmethod
    def _info_from_obj(obj) -> dict:
        try:
            section_name = str(obj.section)
            character_name = str(obj.character)
            duration = round(obj.duration.total_seconds(), 1)
        except (KeyError, AttributeError):
            section_name = None
            character_name = None
            duration = None

        return {
            "section": section_name,
            "character": character_name,
            "duration": duration,
        }
