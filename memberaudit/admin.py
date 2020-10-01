from django.contrib import admin

from .models import Character
from .tasks import update_character as task_update_character


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("_main", "_character", "_last_update_ok", "_last_update_at")

    def _main(self, obj):
        return obj.character_ownership.user.profile.main_character

    def _character(self, obj):
        return obj.character_ownership.character

    def _last_update_ok(self, obj):
        return not obj.sync_status_set.filter(sync_ok=False).exists()

    def _last_update_at(self, obj):
        latest_obj = obj.sync_status_set.latest("updated_at")
        return latest_obj.updated_at

    _last_update_ok.boolean = True

    actions = ("update_character",)

    def update_character(self, request, queryset):
        for obj in queryset:
            task_update_character.delay(character_pk=obj.pk, has_priority=True)
            self.message_user(request, f"Started updateding character: {obj}. ")

    update_character.short_description = "Update selected characters from EVE server"
