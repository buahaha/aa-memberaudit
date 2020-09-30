from django.test import TestCase

from eveuniverse.tools.testdata import create_testdata, ModelSpec

from . import eveuniverse_test_data_filename


class CreateEveUniverseTestData(TestCase):
    def test_create_testdata(self):
        testdata_spec = {
            "EveAncestry": ModelSpec(ids=[11], include_children=False),
            "EveBloodline": ModelSpec(ids=[1], include_children=False),
            "EveFaction": ModelSpec(ids=[500001], include_children=False),
            "EveRace": ModelSpec(ids=[1], include_children=False),
            "EveSolarSystem": ModelSpec(
                ids=[30000142, 30004984, 30001161], include_children=False
            ),
            "EveType": ModelSpec(ids=[24311, 24312], include_children=False),
        }
        create_testdata(testdata_spec, eveuniverse_test_data_filename())
