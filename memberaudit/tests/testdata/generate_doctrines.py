# flake8: noqa
"""This scripts generates test doctrines complete with ships and skills"""

from datetime import timedelta
import inspect
import json
import os
import sys

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
myauth_dir = (
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(currentdir))))
    + "/myauth"
)
sys.path.insert(0, myauth_dir)


import django
from django.db import transaction
from django.apps import apps
from django.utils.timezone import now

# init and setup django project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myauth.settings.local")
django.setup()

if not apps.is_installed("memberaudit"):
    raise RuntimeError("The app memberaudit is not installed")

from eveuniverse.models import EveType
from memberaudit.models import Doctrine, DoctrineShip, DoctrineShipSkill


def get_or_create_esi_or_none(EveModel, id) -> object:
    obj, _ = EveModel.objects.get_or_create_esi(id=id)
    return obj


print("Generating test doctrines...")


doctrine, _ = Doctrine.objects.get_or_create(
    name="Test Doctrine Subcaps",
    defaults={"description": "Generated doctrine for testing"},
)
doctrine.ships.clear()
machariel, _ = DoctrineShip.objects.get_or_create(
    name="Machariel", defaults={"ship_type": get_or_create_esi_or_none(EveType, 17738)}
)
doctrine.ships.add(machariel)
DoctrineShipSkill.objects.get_or_create(
    ship=machariel,
    eve_type=get_or_create_esi_or_none(EveType, 3336),  # Gallente Battleship
    defaults={"level": 3},
)
DoctrineShipSkill.objects.get_or_create(
    ship=machariel,
    eve_type=get_or_create_esi_or_none(EveType, 3337),  # Minmatar Battleship
    defaults={"level": 3},
)
DoctrineShipSkill.objects.get_or_create(
    ship=machariel,
    eve_type=get_or_create_esi_or_none(
        EveType, 12209
    ),  # Large Autocannon Specialization
    defaults={"level": 3},
)
guardian, _ = DoctrineShip.objects.get_or_create(
    name="Guardian", defaults={"ship_type": get_or_create_esi_or_none(EveType, 11987)}
)
doctrine.ships.add(guardian)
DoctrineShipSkill.objects.get_or_create(
    ship=guardian,
    eve_type=get_or_create_esi_or_none(EveType, 12096),  # Logistics Cruisers
    defaults={"level": 5},
)
DoctrineShipSkill.objects.get_or_create(
    ship=guardian,
    eve_type=get_or_create_esi_or_none(EveType, 3335),  # Amarr Cruiser
    defaults={"level": 5},
)
DoctrineShipSkill.objects.get_or_create(
    ship=guardian,
    eve_type=get_or_create_esi_or_none(EveType, 16069),  # Remote Armor Repair Systems
    defaults={"level": 3},
)
DoctrineShipSkill.objects.get_or_create(
    ship=guardian,
    eve_type=get_or_create_esi_or_none(EveType, 16069),  # Capacitor Emission Systems
    defaults={"level": 3},
)

doctrine, _ = Doctrine.objects.get_or_create(
    name="Test Doctrine Caps",
    defaults={"description": "Generated doctrine for testing"},
)
doctrine.ships.clear()
archon, _ = DoctrineShip.objects.get_or_create(
    name="Archon", defaults={"ship_type": get_or_create_esi_or_none(EveType, 23757)}
)
doctrine.ships.add(archon)
DoctrineShipSkill.objects.get_or_create(
    ship=archon,
    eve_type=get_or_create_esi_or_none(EveType, 24311),  # Amarr Carrier
    defaults={"level": 3},
)
DoctrineShipSkill.objects.get_or_create(
    ship=archon,
    eve_type=get_or_create_esi_or_none(EveType, 20533),  # Capital Ships
    defaults={"level": 3},
)
DoctrineShipSkill.objects.get_or_create(
    ship=archon,
    eve_type=get_or_create_esi_or_none(EveType, 21611),  # Jump Drive Calibration
    defaults={"level": 5},
)

print("Completed.")
