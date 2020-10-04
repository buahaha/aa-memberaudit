from django.urls import path
from . import views


app_name = "memberaudit"

urlpatterns = [
    path("", views.index, name="index"),
    path("launcher", views.launcher, name="launcher"),
    path(
        "character_viewer/<int:character_pk>/",
        views.character_viewer,
        name="character_viewer",
    ),
    path("add_character", views.add_character, name="add_character"),
    path(
        "remove_character/<int:character_pk>/",
        views.remove_character,
        name="remove_character",
    ),
    path(
        "share_character/<int:character_pk>/",
        views.share_character,
        name="share_character",
    ),
    path(
        "unshare_character/<int:character_pk>/",
        views.unshare_character,
        name="unshare_character",
    ),
    path(
        "character_location_data/<int:character_pk>/",
        views.character_location_data,
        name="character_location_data",
    ),
    path(
        "character_jump_clones_data/<int:character_pk>/",
        views.character_jump_clones_data,
        name="character_jump_clones_data",
    ),
    path(
        "character_mail_headers_data/<int:character_pk>/",
        views.character_mail_headers_data,
        name="character_mail_headers_data",
    ),
    path(
        "character_mail_data/<int:character_pk>/<int:mail_pk>/",
        views.character_mail_data,
        name="character_mail_data",
    ),
    path(
        "character_skills_data/<int:character_pk>/",
        views.character_skills_data,
        name="character_skills_data",
    ),
    path(
        "character_wallet_journal_data/<int:character_pk>/",
        views.character_wallet_journal_data,
        name="character_wallet_journal_data",
    ),
    path("reports", views.reports, name="reports"),
    path(
        "compliance_report_data",
        views.compliance_report_data,
        name="compliance_report_data",
    ),
    path("character_finder", views.character_finder, name="character_finder"),
    path(
        "character_finder_data",
        views.character_finder_data,
        name="character_finder_data",
    ),
]
