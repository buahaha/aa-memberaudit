from django.contrib import admin
from django.utils.html import format_html

from eveuniverse.models import EveType

from allianceauth.authentication.admin import user_main_organization

from .constants import EVE_CATEGORY_ID_SKILL
from .models import (
    Character,
    CharacterUpdateStatus,
    Doctrine,
    DoctrineShip,
    DoctrineShipSkill,
    Location,
)
from . import tasks


class UpdateStatusOkFilter(admin.SimpleListFilter):
    title = "Update Status OK"
    parameter_name = "update_status_ok"

    def lookups(self, request, model_admin):
        return (("Errors", "Has errors"),)

    def queryset(self, request, queryset):
        if self.value() == "Errors":
            return Character.objects.filter(sync_status_set__sync_ok=False).distinct()
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
        return obj.character_ownership.user.profile.main_character

    _main.admin_order_field = "character_ownership__user__profile__main_character"

    def _state(self, obj):
        return obj.character_ownership.user.profile.state

    _main.admin_order_field = "character_ownership__user__profile__state__name"

    def _organization(self, obj):
        return user_main_organization(obj.character_ownership.user)

    def _last_update_ok(self, obj):
        return obj.is_update_status_ok()

    def _last_update_at(self, obj):
        latest_obj = obj.update_status_set.latest("updated_at")
        return latest_obj.updated_at

    _last_update_ok.boolean = True

    actions = ("update_character", "update_assets")

    def update_character(self, request, queryset):
        for obj in queryset:
            tasks.update_character.delay(character_pk=obj.pk)
            self.message_user(request, f"Started updateting character: {obj}. ")

    update_character.short_description = "Update selected characters from EVE server"

    def update_assets(self, request, queryset):
        for obj in queryset:
            tasks.update_character_assets.delay(character_pk=obj.pk)
            self.message_user(
                request, f"Started updateting assets for character: {obj}. "
            )

    update_assets.short_description = (
        "Update assets for selected characters from EVE server"
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
        if db_field.name == "skill":
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
            f"{x.skill.name} {x.level}"
            for x in obj.skills.all().order_by("skill__name")
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
