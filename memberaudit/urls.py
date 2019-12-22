from django.urls import path
from . import views


app_name = 'memberaudit'

urlpatterns = [
    path('', views.index, name='index'),
    path('registration', views.registration, name='registration'),
    path('add_owner', views.add_owner, name='add_owner')
]