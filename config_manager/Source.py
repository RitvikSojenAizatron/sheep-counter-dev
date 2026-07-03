# Source.py

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

from config_manager.Line import LineDict, LineManager

SNAPSHOTS_DIR = Path("temp/snapshots")
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class SourceValidationError(Exception):
    """Raised when the Source object fails validation checks."""

    pass


class Source:
    """
    Holds all information about a source (camera stream)
    """

    def __init__(
        self,
        name: str,
        ip_address: str,
        source_type: str,  # USB, FILE, RTSP
        id: Optional[str] = None,  # change to object id
        active: bool = False,
        description: Optional[str] = None,
        captured_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        line_dict: Optional[LineDict] = None,
        resolution_width: Optional[int] = None,
        resolution_height: Optional[int] = None,
        window_id: Optional[
            str
        ] = None,  # not used. Was gonna be for if we had more than one tiled window
    ):
        self.id = id or f"src-{uuid.uuid4()}"
        self.name = name
        self.ip_address = ip_address
        self.source_type = source_type
        self.active = active
        self.description = description
        self.captured_at = captured_at
        self.updated_at = updated_at
        self.resolution_width = resolution_width
        self.resolution_height = resolution_height
        self.lineManager = LineManager(line_dict)
        self.window_id = window_id
        self.make_assertions_and_set_defaults()

    def set_bin_id(self, bin_id: int) -> None:
        self.bin_id = bin_id

    def make_assertions_and_set_defaults(self) -> None:
        """
        Validates the input data and sets default values where needed.
        RaisesSourceValidationError on invalid inputs.
        """
        # Name must be provided
        if not self.name:
            raise SourceValidationError("Source 'name' must not be empty or None.")

        # Check source_type is valid
        if self.source_type not in {"RTSP", "USB"}:
            raise SourceValidationError(
                f"Invalid source_type '{self.source_type}'. Must be one of: RTSP, USB."
            )

        # Validate IP address for source type
        if not self.check_ip_adress():
            raise SourceValidationError(
                f"IP address '{self.ip_address}' is not valid for source type '{self.source_type}'."
            )

        # Ensure active is boolean
        if not isinstance(self.active, bool):
            self.active = False

        # Set defaults
        self.description = self.description or "No metadata provided"
        self.captured_at = self.captured_at or 0.0
        self.updated_at = self.updated_at or 0.0
        self.window_id = self.window_id or 1
        # self.bin_id = None

    # TODO: either add prefix if not there, or wys error
    def check_ip_adress(self) -> bool:
        """
        Ensures IP addresses match source_type
        """
        if self.source_type == "USB":
            return self.ip_address.startswith("v4l2://")
        if self.source_type == "RTSP":
            return self.ip_address.startswith("rtsp://")
        return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Source":
        if data.get("name") is None:
            raise Exception("Provide a source Name")
        attrs = data.get("attributes", {})
        return cls(
            id=data["id"],
            name=data["name"],
            updated_at=data.get("updated_at"),
            ip_address=attrs.get("ip_address"),
            source_type=attrs.get("source_type"),
            active=attrs.get("active"),
            description=attrs.get("description"),
            captured_at=attrs.get("captured_at"),
            line_dict=attrs.get("line_dict"),
            resolution_width=attrs.get("resolution_width"),
            resolution_height=attrs.get("resolution_height"),
        )

    def to_dict(self) -> Dict[str, Any]:
        # print(f"Source:to_dict: : {vars(self).items()}")
        attributes_dict = {
            key: value
            for key, value in vars(self).items()
            if not key.startswith("_")
            and not key.startswith("id")
            and not key.startswith("name")
            and not key.startswith("updated_at")
            and not key.startswith("lineManager")
        }
        attributes_dict["line_dict"] = self.lineManager.to_dict()
        # print("attributes_dict")
        # print(attributes_dict)
        return {
            "id": self.id,
            "name": self.name,
            "updated_at": self.updated_at,
            "attributes": attributes_dict,
        }

    @staticmethod
    def _resolve_capture_uri(ip_address: str, source_type: str):
        if source_type == "USB":
            return int(ip_address.replace("v4l2:///dev/video", ""))
        elif source_type == "FILE":
            return ip_address.replace("file://", "")
        return ip_address

    @staticmethod
    def probe_source(
        ip_address: str,
        source_type: str,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Probes a camera source: checks connectivity, captures a snapshot frame,
        and reads the native resolution.

        Returns:
            dict with keys: connectable (bool), width (int), height (int), snapshot_path (str|None)
        """
        cap_uri = Source._resolve_capture_uri(ip_address, source_type)
        cap = cv2.VideoCapture(cap_uri)

        if not cap.isOpened():
            cap.release()
            return {
                "connectable": False,
                "width": None,
                "height": None,
                "snapshot_path": None,
            }

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        snapshot_path = None
        if source_id:
            ret, frame = cap.read()
            if ret:
                snapshot_path = str(SNAPSHOTS_DIR / f"{source_id}.jpg")
                cv2.imwrite(snapshot_path, frame)

        cap.release()
        return {
            "connectable": True,
            "width": width,
            "height": height,
            "snapshot_path": snapshot_path,
        }

    def check_connectable(self) -> bool:
        """Checks if the source can be connected to."""
        result = Source.probe_source(self.ip_address, self.source_type)
        return result["connectable"]

    def probe_and_update(self) -> Dict[str, Any]:
        """
        Probes the source, saves a snapshot, and updates resolution attributes.
        Returns the probe result dict.
        """
        result = Source.probe_source(self.ip_address, self.source_type, self.id)
        if result["connectable"]:
            self.resolution_width = result["width"]
            self.resolution_height = result["height"]
        return result
