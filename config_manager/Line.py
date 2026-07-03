import os
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import TypedDict

sys.path.append(os.getcwd())

Point = Tuple[float, float]
Vector = List[Point]


class LineConfig(TypedDict):
    name: str
    point_list: Vector
    crossing_direction: Vector


LineDict = Dict[str, LineConfig]


class Line:
    """Represents a line segment used for line-crossing detection."""

    def __init__(
        self,
        name: str,
        point_list: Vector,
        crossing_direction: Optional[Vector] = None,
        id: Optional[str] = None,
    ):
        self.id = id or f"line-{uuid.uuid4()}"
        self.name = name
        self.point_list = point_list
        self.crossing_direction: Vector = crossing_direction or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            self.id: {
                "name": self.name,
                "point_list": self.point_list,
                "crossing_direction": self.crossing_direction,
            }
        }

    @classmethod
    def from_dict(cls, id: str, data: Dict[str, Any]) -> "Line":
        return cls(
            id=id,
            name=data["name"],
            point_list=data["point_list"],
            crossing_direction=data.get("crossing_direction"),
        )


class LineManager:
    def __init__(self, line_dict: Optional[LineDict] = None):
        self.line_list: List[Line] = []
        if line_dict:
            self._load_from_dict(line_dict)

    def _load_from_dict(self, line_dict: LineDict) -> None:
        for line_id, info in line_dict.items():
            self.line_list.append(Line.from_dict(line_id, info))

    def to_dict(self) -> LineDict:
        result: LineDict = {}
        for line in self.line_list:
            result.update(line.to_dict())
        return result
