from django.contrib import admin


from django.contrib.admin.options import csrf_protect_m
from django.utils.html import format_html

from eveuniverse.models import EveType

import re

from .constants import EVE_CATEGORY_ID_SKILL
from .models import (
    Character,
    CharacterUpdateStatus,
    Doctrine,
    DoctrineShip,
    DoctrineShipSkill,
    Location,
    Settings,
)
from . import tasks


class UpdateStatusOkFilter(admin.SimpleListFilter):
    title = "Update Status OK"
    parameter_name = "update_status_ok"

    def lookups(self, request, model_admin):
        return (("Errors", "Has errors"),)

    def queryset(self, request, queryset):
        if self.value() == "Errors":
            return Character.objects.filter(
                update_status_set__is_success=False
            ).distinct()
        else:
            return Character.objects.all()


class SyncStatusAdminInline(admin.TabularInline):
    model = CharacterUpdateStatus
    fields = ("section", "is_success", "error_message")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("authentication/css/admin.css",)}

    list_display = (
        "_character_pic",
        "_character",
        "_main",
        "_state",
        "_organization",
        "created_at",
        "_last_update_at",
        "_last_update_ok",
        "_missing_updates",
    )
    list_display_links = (
        "_character_pic",
        "_character",
    )
    list_filter = (
        UpdateStatusOkFilter,
        "created_at",
        "character_ownership__user__profile__state",
    )
    list_select_related = (
        "character_ownership",
        "character_ownership__user",
        "character_ownership__user__profile__main_character",
        "character_ownership__character",
    )
    ordering = ("-created_at",)
    search_fields = [
        "character_ownership__character__character_name",
        "character_ownership__user__username",
    ]

    def _character_pic(self, obj):
        character = obj.character_ownership.character
        return format_html(
            '<img src="{}" class="img-circle">', character.portrait_url(size=32)
        )

    _character_pic.short_description = ""

    def _character(self, obj):
        return obj.character_ownership.character

    _character.admin_order_field = "character_ownership__character"

    def _main(self, obj):
        try:
            return obj.character_ownership.user.profile.main_character
        except AttributeError:
            return None

    _main.admin_order_field = "character_ownership__user__profile__main_character"

    def _state(self, obj):
        return obj.character_ownership.user.profile.state

    _main.admin_order_field = "character_ownership__user__profile__state__name"

    def _organization(self, obj):
        try:
            main = obj.character_ownership.user.profile.main_character
            return "{}{}".format(
                main.corporation_name,
                f" [{main.alliance_ticker}]" if main.alliance_ticker else "",
            )
        except AttributeError:
            return None

    def _last_update_ok(self, obj):
        return obj.is_update_status_ok()

    def _last_update_at(self, obj):
        latest_obj = obj.update_status_set.latest("updated_at")
        return latest_obj.updated_at

    _last_update_ok.boolean = True

    def _missing_updates(self, obj):
        existing = set(obj.update_status_set.values_list("section", flat=True))
        all_sections = {x[0] for x in Character.UPDATE_SECTION_CHOICES}
        missing = all_sections.difference(existing)
        if missing:
            return sorted([Character.section_display_name(x) for x in missing])

        return None

    actions = [
        "update_character",
        "update_assets",
        "update_location",
        "update_online_status",
    ]

    def update_character(self, request, queryset):
        for obj in queryset:
            tasks.update_character.delay(character_pk=obj.pk, force_update=True)
            self.message_user(request, f"Started updating character: {obj}. ")

    update_character.short_description = "Update selected characters from EVE server"

    def update_assets(self, request, queryset):
        for obj in queryset:
            tasks.update_character_assets.delay(character_pk=obj.pk)
            self.message_user(
                request, f"Started updating assets for character: {obj}. "
            )

    update_assets.short_description = (
        "Update assets for selected characters from EVE server"
    )

    def update_location(self, request, queryset):
        section = Character.UPDATE_SECTION_LOCATION
        for obj in queryset:
            tasks.update_character_section.delay(character_pk=obj.pk, section=section)
            self.message_user(
                request,
                f"Started updating {Character.section_display_name(section)} for character: {obj}. ",
            )

    update_location.short_description = (
        f"Update {Character.section_display_name(Character.UPDATE_SECTION_LOCATION)} "
        "for selected characters from EVE server"
    )

    def update_online_status(self, request, queryset):
        section = Character.UPDATE_SECTION_ONLINE_STATUS
        for obj in queryset:
            tasks.update_character_section.delay(character_pk=obj.pk, section=section)
            self.message_user(
                request,
                f"Started updating {Character.section_display_name(section)} for character: {obj}. ",
            )

    update_online_status.short_description = (
        "Update "
        f"{Character.section_display_name(Character.UPDATE_SECTION_ONLINE_STATUS)} "
        "for selected characters from EVE server"
    )

    inlines = (SyncStatusAdminInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("id", "_name", "_type", "_group", "_solar_system", "updated_at")
    list_filter = (
        (
            "eve_solar_system__eve_constellation__eve_region",
            admin.RelatedOnlyFieldListFilter,
        ),
        ("eve_solar_system", admin.RelatedOnlyFieldListFilter),
        ("eve_type__eve_group", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ["name"]
    list_select_related = (
        "eve_solar_system",
        "eve_solar_system__eve_constellation__eve_region",
        "eve_type",
        "eve_type__eve_group",
    )

    def _name(self, obj):
        return obj.name_plus

    _name.admin_order_field = "name"

    def _solar_system(self, obj):
        return obj.eve_solar_system.name if obj.eve_solar_system else None

    _solar_system.admin_order_field = "eve_solar_system__name"

    def _type(self, obj):
        return obj.eve_type.name if obj.eve_type else None

    _type.admin_order_field = "eve_type__name"

    def _group(self, obj):
        return obj.eve_type.eve_group.name if obj.eve_type else None

    _group.admin_order_field = "eve_type__eve_group__name"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Doctrine)
class DoctrineAdmin(admin.ModelAdmin):
    list_display = ("name", "_ships", "is_active")
    ordering = ["name"]
    filter_horizontal = ("ships",)

    def _ships(self, obj):
        return [x.name for x in obj.ships.all().order_by("name")]


class DoctrineMinimumSkillAdminInline(admin.TabularInline):
    model = DoctrineShipSkill

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "eve_type":
            kwargs["queryset"] = (
                EveType.objects.select_related("eve_group__eve_category")
                .filter(eve_group__eve_category=EVE_CATEGORY_ID_SKILL)
                .order_by("name")
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(DoctrineShip)
class DoctrineShipAdmin(admin.ModelAdmin):
    list_display = ("name", "ship_type", "_skills", "_doctrines", "is_visible")
    ordering = ["name"]

    def _skills(self, obj):
        return [
            f"{x.eve_type.name} {x.level}"
            for x in obj.skills.all().order_by("eve_type__name")
        ]

    def _doctrines(self, obj) -> list:
        doctrines = [f"{x.name}" for x in obj.doctrines.all().order_by("name")]
        return doctrines if doctrines else None

    inlines = (DoctrineMinimumSkillAdminInline,)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "ship_type":
            kwargs["queryset"] = (
                EveType.objects.select_related("eve_group__eve_category")
                .filter(eve_group__eve_category=6)
                .order_by("name")
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class SingletonAdmin(admin.ModelAdmin):
    class Meta:
        abstract = True

    def has_add_permission(self, request):
        if self.model.objects.all().count() == 0:
            return True
        return False

    def has_change_permission(self, request, obj=None):
        if self.model.objects.all().count() == 1:
            return True
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def add_view(self, request, form_url="", extra_context=None):
        template_response = super(SingletonAdmin, self).add_view(
            request, form_url=form_url, extra_context=extra_context
        )
        # POST request won't have html response
        if request.method == "GET":
            # removing Save and add another button: with regex
            template_response.content = re.sub(
                "<input.*?_addanother.*?(/>|>)", "", template_response.rendered_content
            )
        return template_response

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        instance = self.model.objects.first()
        return self.changeform_view(
            request=request,
            object_id=str(instance.id) if instance else None,
            extra_context=extra_context,
        )


@admin.register(Settings)
class SettingsAdmin(SingletonAdmin):
    pass
