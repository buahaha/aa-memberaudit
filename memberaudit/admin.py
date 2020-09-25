from django.contrib import admin

from .models import *
from .tasks import sync_owner


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ("character", "last_sync", "last_sync_ok")

    def last_sync_ok(self, obj):
        return obj.last_error is None

    last_sync_ok.boolean = True

    actions = ("update_character",)

    def update_character(self, request, queryset):

        for obj in queryset:
            sync_owner.delay(obj.pk)
            text = "Started syncing data for: {}. ".format(obj)
            text += "You will receive a notification once it is completed."

            self.message_user(request, text)

    update_character.short_description = "Sync character with EVE server"


@admin.register(Mail)
class MailAdmin(admin.ModelAdmin):
    list_display = ("mail_id", "owner", "from_entity", "from_mailing_list", "subject")
    list_filter = ("owner",)


@admin.register(MailLabels)
class MailLabelsAdmin(admin.ModelAdmin):
    pass


@admin.register(MailRecipient)
class MailRecipientAdmin(admin.ModelAdmin):
    pass


@admin.register(EveEntity)
class EveEntityAdmin(admin.ModelAdmin):
    pass


@admin.register(MailingList)
class MailingListAdmin(admin.ModelAdmin):
    pass
