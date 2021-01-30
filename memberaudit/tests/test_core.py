from unittest.mock import Mock, patch

from allianceauth.eveonline.evelinks import dotlan, evewho

from .testdata.esi_client_stub import load_test_data
from .testdata.load_entities import load_entities
from .testdata.load_eveuniverse import load_eveuniverse
from .testdata.load_locations import load_locations
from .testdata.esi_client_stub import esi_test_data
from ..core.xml_converter import eve_xml_to_html
from ..core.asset_tree import AssetNode, RootNode
from ..models import CharacterAsset
from . import create_memberaudit_character
from ..utils import NoSocketsTestCase


MODULE_PATH = "memberaudit.core.xml_converter"


class TestHTMLConversion(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        load_eveuniverse()
        load_entities()
        cls.maxDiff = None

    def test_convert_eve_xml_alliance(self):
        """can convert an alliance link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="An Alliance"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("An Alliance")) != -1)

    def test_convert_eve_xml_character(self):
        """can convert a character link in CCP XML to HTML"""
        result = eve_xml_to_html(
            load_test_data()
            .get("Mail")
            .get("get_characters_character_id_mail_mail_id")
            .get("2")
            .get("body")
        )
        self.assertTrue(result.find(evewho.character_url(1001)) != -1)

    def test_convert_eve_xml_corporation(self):
        """can convert a corporation link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="A Corporation"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.alliance_url("A Corporation")) != -1)

    def test_convert_eve_xml_solar_system(self):
        """can convert a solar system link in CCP XML to HTML"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="Polaris"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Mail")
                .get("get_characters_character_id_mail_mail_id")
                .get("2")
                .get("body")
            )
            self.assertTrue(result.find(dotlan.solar_system_url("Polaris")) != -1)

    def test_convert_bio_1(self):
        """can convert a bio includes lots of non-ASCII characters and handle the u-bug"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="An Alliance"),
        ):
            result = eve_xml_to_html(
                load_test_data()
                .get("Character")
                .get("get_characters_character_id")
                .get("1002")
                .get("description")
            )
            self.assertIn(
                "Zuverlässigkeit, Eigeninitiative, Hilfsbereitschaft, Teamfähigkeit",
                result,
            )
            self.assertNotEqual(result[:2], "u'")

    def test_convert_bio_2(self):
        """can convert a bio that resulted in a syntax error (#77)"""
        with patch(
            "eveuniverse.models.EveEntity.objects.resolve_name",
            Mock(return_value="An Alliance"),
        ):
            try:
                result = eve_xml_to_html(
                    load_test_data()
                    .get("Character")
                    .get("get_characters_character_id")
                    .get("1003")
                    .get("description")
                )
            except Exception as ex:
                self.fail(f"Unexpected exception was raised: {ex}")

            self.assertNotEqual(result[:2], "u'")


class TestAssetNode(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.maxDiff = None
        load_eveuniverse()
        load_entities()
        load_locations()
        cls.assets_flat = {
            row["item_id"]: row
            for row in esi_test_data["Assets"]["get_characters_character_id_assets"][
                "1001"
            ]
        }
        for item in esi_test_data["Assets"][
            "post_characters_character_id_assets_names"
        ]["1001"]:
            cls.assets_flat[item["item_id"]]["name"] = item["name"]

    def test_should_create_new_node(self):
        # when
        obj = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        # then
        self.assertIsInstance(obj, AssetNode)

    def test_should_identify_root(self):
        # given
        asset = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        root = RootNode()
        # when/then
        self.assertTrue(root.is_root)
        self.assertFalse(asset.is_root)

    def test_should_add_single_node(self):
        # given
        parent = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        child_1 = AssetNode(
            item_id=2,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="",
            quantity=3,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        # when
        parent.add_node(child_1)
        # then
        self.assertEqual(parent.children, {2: child_1})
        self.assertEqual(child_1.location_id, 60003760)

    def test_should_add_multiple_nodes(self):
        # given
        parent = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        child_1 = AssetNode(
            item_id=2,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=3,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        child_2 = AssetNode(
            item_id=3,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        # when
        parent.add_nodes([child_1, child_2])
        # then
        self.assertEqual(parent.children, {2: child_1, 3: child_2})

    def test_should_identify_children(self):
        # given
        parent = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        child = AssetNode(
            item_id=2,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=3,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        # when
        parent.add_node(child)
        # then
        self.assertTrue(parent.has_children)
        self.assertFalse(child.has_children)

    def test_should_serialize_and_deserialize_to_dict(self):
        # given
        tree_1 = RootNode()
        parent = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        child_1 = AssetNode(
            item_id=2,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=3,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        child_2 = AssetNode(
            item_id=3,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        tree_1.add_node(parent)
        parent.add_nodes([child_1, child_2])
        # when
        d = tree_1.asdict()
        tree_2 = RootNode.from_dict(d)
        # then
        self.assertEqual(tree_1, tree_2)

    def test_should_count_tree_size(self):
        # given
        parent = AssetNode(
            item_id=1,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Shooter",
            quantity=1,
            type_id=603,
            is_blueprint_copy=False,
            is_singleton=True,
        )
        child_1 = AssetNode(
            item_id=2,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=3,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        child_2 = AssetNode(
            item_id=3,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
            is_blueprint_copy=False,
            is_singleton=False,
        )
        parent.add_node(child_1)
        child_1.add_node(child_2)
        # when
        result = parent.size()
        # then
        self.assertEqual(result, 3)

    def test_should_create_tree_from_esi_data(self):
        # given
        asset_1 = AssetNode(
            is_blueprint_copy=True,
            is_singleton=True,
            item_id=1100000000001,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Parent Item 1",
            quantity=1,
            type_id=20185,
        )
        asset_2 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000002,
            location_id=1100000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 2",
            quantity=1,
            type_id=19540,
        )
        asset_3 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000003,
            location_id=1100000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 3",
            quantity=1,
            type_id=23,
        )
        asset_4 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000004,
            location_id=1100000000003,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 4",
            quantity=1,
            type_id=19553,
        )
        asset_5 = AssetNode(
            is_blueprint_copy=True,
            is_singleton=True,
            item_id=1100000000005,
            location_id=1000000000001,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.OTHER,
            name="Parent Item 2",
            quantity=1,
            type_id=20185,
        )
        asset_6 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000006,
            location_id=1100000000005,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 6",
            quantity=1,
            type_id=19540,
        )
        asset_7 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000007,
            location_id=30000142,
            location_flag="???",
            location_type=AssetNode.LocationType.SOLAR_SYSTEM,
            name="",
            quantity=1,
            type_id=19540,
        )
        asset_8 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000008,
            location_id=1000000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
        )
        tree_1 = RootNode()
        tree_1.add_nodes([asset_8, asset_1, asset_5, asset_7])
        asset_1.add_nodes([asset_2, asset_3])
        asset_3.add_node(asset_4)
        asset_5.add_node(asset_6)
        # when
        tree_2 = RootNode.from_esi_data(self.assets_flat)
        # then
        self.assertEqual(tree_1, tree_2)

    def test_should_create_asset_node_from_esi_data_1(self):
        # given
        asset_4 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000004,
            location_id=1100000000003,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 4",
            quantity=1,
            type_id=19553,
        )
        esi_data = self.assets_flat[1100000000004]
        # when
        asset_created = AssetNode.from_esi_data(esi_data)
        # then
        self.assertEqual(asset_created, asset_4)

    def test_should_create_asset_node_from_esi_data_2(self):
        # given
        asset_8 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000008,
            location_id=1000000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
        )
        esi_data = self.assets_flat[1100000000008]
        # when
        asset_created = AssetNode.from_esi_data(esi_data)
        # then
        self.assertEqual(asset_created, asset_8)

    def test_should_save_asset_tree_to_disk(self):
        # given
        character = create_memberaudit_character(1001)
        tree = RootNode()
        asset_1 = AssetNode(
            is_blueprint_copy=True,
            is_singleton=True,
            item_id=1100000000001,
            location_id=60003760,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.STATION,
            name="Parent Item 1",
            quantity=1,
            type_id=20185,
        )
        asset_2 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000002,
            location_id=1100000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 2",
            quantity=1,
            type_id=19540,
        )
        asset_3 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000003,
            location_id=1100000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 3",
            quantity=1,
            type_id=23,
        )
        asset_4 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000004,
            location_id=1100000000003,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 4",
            quantity=1,
            type_id=19553,
        )
        asset_5 = AssetNode(
            is_blueprint_copy=True,
            is_singleton=True,
            item_id=1100000000005,
            location_id=1000000000001,
            location_flag="Hangar",
            location_type=AssetNode.LocationType.OTHER,
            name="Parent Item 2",
            quantity=1,
            type_id=20185,
        )
        asset_6 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000006,
            location_id=1100000000005,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="Leaf Item 6",
            quantity=1,
            type_id=19540,
        )
        asset_7 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000007,
            location_id=30000142,
            location_flag="???",
            location_type=AssetNode.LocationType.SOLAR_SYSTEM,
            name="",
            quantity=1,
            type_id=19540,
        )
        asset_8 = AssetNode(
            is_blueprint_copy=False,
            is_singleton=True,
            item_id=1100000000008,
            location_id=1000000000001,
            location_flag="???",
            location_type=AssetNode.LocationType.ITEM,
            name="",
            quantity=1,
            type_id=19540,
        )
        tree.add_nodes([asset_8, asset_1, asset_5, asset_7])
        asset_1.add_nodes([asset_2, asset_3])
        asset_3.add_node(asset_4)
        asset_5.add_node(asset_6)
        # when
        tree.create_children_for_character(character)
        # then
        result_item_ids = set(CharacterAsset.objects.values_list("item_id", flat=True))
        self.assertSetEqual(
            result_item_ids,
            {
                1100000000001,
                1100000000002,
                1100000000003,
                1100000000004,
                1100000000005,
                1100000000006,
                1100000000007,
                1100000000008,
            },
        )
        obj_1 = character.assets.get(item_id=1100000000001)
        obj_2 = character.assets.get(item_id=1100000000002)
        obj_3 = character.assets.get(item_id=1100000000003)
        obj_4 = character.assets.get(item_id=1100000000004)
        obj_5 = character.assets.get(item_id=1100000000005)
        obj_5 = character.assets.get(item_id=1100000000005)
        obj_6 = character.assets.get(item_id=1100000000006)
        # obj_7 = character.assets.get(item_id=1100000000007)
        # obj_8 = character.assets.get(item_id=1100000000008)
        self.assertEqual(obj_2.parent, obj_1)
        self.assertEqual(obj_3.parent, obj_1)
        self.assertEqual(obj_4.parent, obj_3)
        self.assertEqual(obj_6.parent, obj_5)
