from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import List, Type, Dict

from dacite import from_dict, DaciteError

from allianceauth.services.hooks import get_extension_logger

from .. import __title__
from ..app_settings import MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
from ..models.sections import CharacterAsset
from ..utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@dataclass
class BaseNode:
    """Abstract node"""

    _children: Dict[int, "AssetNode"] = field(default_factory=dict, init=False)

    @property
    def is_root(self) -> bool:
        raise NotImplementedError()

    @property
    def children(self) -> Dict[int, "AssetNode"]:
        return self._children

    @property
    def has_children(self) -> bool:
        return bool(self.children)

    def add_node(self, node: "AssetNode") -> None:
        self._children[node.item_id] = node
        if not self.is_root:
            node.location_id = self.location_id

    def add_nodes(self, nodes: List["AssetNode"]) -> None:
        for node in nodes:
            self.add_node(node)

    def asdict(self) -> dict:
        return asdict(self)

    def size(self) -> int:
        """returns the size of this node as count of this node and all its children"""
        node_count = 1
        for node in self.children.values():
            node_count += node.size()
        return node_count

    def pretty_print(self, tab=0) -> None:
        output = self.item_id if not self.is_root else "root"
        print(f"{'  ' * tab}{output}")
        for node in self.children.values():
            node.pretty_print(tab + 1)

    def create_children_for_character(self, character):
        if self.has_children:
            if not self.is_root:
                parent = character.assets.get(item_id=self.item_id)
            else:
                parent = None
            new_assets = [
                node.to_character_asset(character, parent)
                for node in self.children.values()
            ]
            CharacterAsset.objects.bulk_create(
                new_assets, batch_size=MEMBERAUDIT_BULK_METHODS_BATCH_SIZE
            )
            for node in self.children.values():
                if node.has_children:
                    node.create_children_for_character(character)

    @classmethod
    def from_dict(cls, data: dict) -> Type["BaseNode"]:
        try:
            return from_dict(data_class=cls, data=data)
        except DaciteError as ex:
            logger.error("Failed to convert dict to %s", type(cls), exc_info=True)
            raise ex


@dataclass
class RootNode(BaseNode):
    """Special node defining the root of an asset tree"""

    @property
    def is_root(self) -> bool:
        return True

    @staticmethod
    def from_esi_data(assets_flat: dict) -> "RootNode":
        root = RootNode()
        location_ids = {
            x["location_id"]
            for x in assets_flat.values()
            if "location_id" in x and x["location_id"] not in assets_flat
        }
        node_id_map = {}
        parent_asset_ids = {
            item_id
            for item_id, asset_info in assets_flat.items()
            if asset_info.get("location_id")
            and asset_info["location_id"] in location_ids
        }
        for item_id in parent_asset_ids:
            item = assets_flat[item_id]
            node = AssetNode.from_esi_data(item)
            root.add_node(node)
            node_id_map[item_id] = node
            assets_flat.pop(item_id)

        while assets_flat:
            parent_asset_ids = {
                item_id
                for item_id, asset_info in assets_flat.items()
                if asset_info.get("location_id")
                and asset_info["location_id"] in node_id_map.keys()
            }
            if not parent_asset_ids:
                break
            for item_id in parent_asset_ids:
                item = assets_flat[item_id]
                location_id = item.get("location_id")
                parent_node = node_id_map[location_id]
                node = AssetNode.from_esi_data(item)
                parent_node.add_node(node)
                node_id_map[item_id] = node
                assets_flat.pop(item_id)

        if assets_flat:
            logger.warning("Orphaned assets: %s", assets_flat.keys())
        return root


@dataclass
class AssetNode(BaseNode):
    """Asset within an asset tree"""

    class LocationType(Enum):
        STATION = "station"
        SOLAR_SYSTEM = "solar_system"
        ITEM = "item"
        OTHER = "other"

    item_id: int
    location_id: int
    location_flag: str
    location_type: LocationType
    name: str
    quantity: int
    type_id: int
    is_blueprint_copy: bool
    is_singleton: bool

    def __post_init__(self):
        if not self.location_flag:
            self.location_flag = ""
        if not self.name or self.name == "None":
            self.name = ""
        self.location_type = self.LocationType(self.location_type)

    @property
    def is_root(self) -> bool:
        return False

    def to_character_asset(
        self, character, parent: CharacterAsset = None
    ) -> CharacterAsset:
        return CharacterAsset(
            character=character,
            item_id=self.item_id,
            location_id=self.location_id,
            eve_type_id=self.type_id,
            name=self.name,
            is_blueprint_copy=self.is_blueprint_copy,
            is_singleton=self.is_singleton,
            location_flag=self.location_flag,
            quantity=self.quantity,
            parent=parent,
        )

    @classmethod
    def from_esi_data(cls, item: dict) -> "AssetNode":
        return cls(
            item_id=item.get("item_id"),
            type_id=item.get("type_id"),
            name=item.get("name", ""),
            is_blueprint_copy=item.get("is_blueprint_copy"),
            is_singleton=item.get("is_singleton"),
            location_id=item.get("location_id"),
            location_flag=item.get("location_flag", ""),
            location_type=item.get("location_type"),
            quantity=item.get("quantity"),
        )
