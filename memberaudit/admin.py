from django.contrib import admin
from django.utils.html import format_html

from allianceauth.authentication.admin import user_main_organization

from .models import Character, CharacterSyncStatus
from .tasks import update_character as task_update_character


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
    model = CharacterSyncStatus

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
        errors_count = obj.sync_status_set.filter(sync_ok=False).count()
        ok_count = obj.sync_status_set.filter(sync_ok=True).count()
        if errors_count > 0:
            return False
        elif ok_count == len(CharacterSyncStatus.TOPIC_CHOICES):
            return True
        else:
            return None

    def _last_update_at(self, obj):
        latest_obj = obj.sync_status_set.latest("updated_at")
        return latest_obj.updated_at

    _last_update_ok.boolean = True

    actions = ("update_character",)

    def update_character(self, request, queryset):
        for obj in queryset:
            task_update_character.delay(character_pk=obj.pk, has_priority=True)
            self.message_user(request, f"Started updateting character: {obj}. ")

    update_character.short_description = "Update selected characters from EVE server"

    inlines = (SyncStatusAdminInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
