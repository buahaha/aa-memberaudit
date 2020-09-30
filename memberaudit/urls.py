from django.urls import path
from . import views


app_name = "memberaudit"

urlpatterns = [
    path("", views.index, name="index"),
    path("launcher", views.launcher, name="launcher"),
    path(
        "character_main/<int:character_pk>/",
        views.character_main,
        name="character_main",
    ),
    path("add_owner", views.add_owner, name="add_owner"),
    path(
        "character_location_data/<int:character_pk>/",
        views.character_location_data,
        name="character_location_data",
    ),
    path(
        "character_mails_data/<int:character_pk>/",
        views.character_mails_data,
        name="character_mails_data",
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
