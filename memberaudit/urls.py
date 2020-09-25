from django.urls import path
from . import views


app_name = "memberaudit"

urlpatterns = [
    path("", views.index, name="index"),
    path("launcher", views.launcher, name="launcher"),
    path("add_owner", views.add_owner, name="add_owner"),
    path("compliance_report", views.compliance_report, name="compliance_report"),
    path(
        "compliance_report_data",
        views.compliance_report_data,
        name="compliance_report_data",
    ),
]
