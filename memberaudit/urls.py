from django.urls import path
from . import views


app_name = "memberaudit"

urlpatterns = [
    path("", views.index, name="index"),
    path("launcher", views.launcher, name="launcher"),
    path("character_main", views.character_main, name="character_main"),
    path(
        "activate_character/<int:character_id>/",
        views.activate_character,
        name="activate_character",
    ),
    path("add_owner", views.add_owner, name="add_owner"),
    path(
        "character_location_data",
        views.character_location_data,
        name="character_location_data",
    ),
    path(
        "character_skills_data/<int:character_id>/",
        views.character_skills_data,
        name="character_skills_data",
    ),
    path("compliance_report", views.compliance_report, name="compliance_report"),
    path(
        "compliance_report_data",
        views.compliance_report_data,
        name="compliance_report_data",
    ),
]
