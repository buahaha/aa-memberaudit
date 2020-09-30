from django.utils.translation import ugettext_lazy as _

from allianceauth.services.hooks import MenuItemHook, UrlHook
from allianceauth import hooks

from . import urls
from .models import Character


class MemberauditMenuItem(MenuItemHook):
    """ This class ensures only authorized users will see the menu entry """

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _("My Characters"),
            "far fa-address-card fa-fw fa-fw",
            "memberaudit:index",
            navactive=["memberaudit:index"],
        )

    def render(self, request):
        if request.user.has_perm("memberaudit.basic_access"):
            app_count = Character.objects.unregistered_characters_of_user_count(
                request.user
            )
            self.count = app_count if app_count and app_count > 0 else None
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return MemberauditMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "memberaudit", r"^memberaudit/")


class MemberauditMenuItem2(MenuItemHook):
    """ This class ensures only authorized users will see the menu entry """

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _("Analysis"),
            "fas fa-chart-bar fa-fw",
            "memberaudit:character_finder",
            navactive=["memberaudit:character_finder"],
        )

    def render(self, request):
        if request.user.has_perm("memberaudit.unrestricted_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu_2():
    return MemberauditMenuItem2()
