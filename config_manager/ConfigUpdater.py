import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config_manager.Line import Line, LineDict
from config_manager.Source import Source


class ConfigUpdateError(Exception):
    """Raised when there is an error during one of these method calls."""
    pass


class ConfigUpdater:
    """
    Manages source and line config updates, persisting to a local JSON file.
    """

    DEFAULT_CONFIG_PATH = "config/sources.json"

    def __init__(
        self,
        config_path: Optional[str] = None,
        config_manager=None,
    ):
        self._config_path = Path(config_path or self.DEFAULT_CONFIG_PATH)
        self._config_manager = config_manager
        self.logger = logging.getLogger(__name__)

    # --- JSON I/O ---

    def _load(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            return {"updated_at": 0.0, "sources": []}
        with open(self._config_path, "r") as f:
            return json.load(f)

    def _save(self, data: Dict[str, Any]) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(data, f, indent=2)

    def _refresh(self) -> None:
        """Reload the ConfigManager's sources from the JSON file after a write."""
        if self._config_manager is None:
            return
        sources = getattr(self._config_manager, "sources", None)
        if sources and hasattr(sources, "load"):
            sources.load()

    # --- Source helpers ---

    def _source_exists(self, source_id: str) -> bool:
        return any(s["id"] == source_id for s in self._load()["sources"])

    def _source_name_taken(self, name: str) -> bool:
        return any(s["name"] == name for s in self._load()["sources"])

    def _source_active(self, source_id: str) -> bool:
        for s in self._load()["sources"]:
            if s["id"] == source_id:
                return s["attributes"].get("active", False)
        return False

    # --- Point normalisation ---

    def _get_source_resolution(self, camera_id: str):
        for s in self._load()["sources"]:
            if s["id"] == camera_id:
                attrs = s.get("attributes", {})
                return attrs.get("resolution_width"), attrs.get("resolution_height")
        return None, None

    @staticmethod
    def _normalize_points(point_list, width: Optional[int], height: Optional[int]):
        """Divide pixel coordinates by source resolution to produce [0, 1] values.
        If resolution is unknown, returns the list unchanged (assumes already normalized)."""
        if not width or not height:
            return list(point_list)
        return [(x / width, y / height) for x, y in point_list]

    @staticmethod
    def _clip_normalized_points(point_list):
        """Clips all points to the normalized [0, 1] range."""
        return [(max(0.0, min(1.0, x)), max(0.0, min(1.0, y))) for x, y in point_list]

    # --- Sources ---

    def add_source(
        self,
        name: str,
        ip_address: str,
        source_type: str = "RTSP",
        active: bool = True,
        description: Optional[str] = None,
        line_dict: Optional[LineDict] = None,
        resolution_width: Optional[int] = None,
        resolution_height: Optional[int] = None,
    ):
        if self._source_name_taken(name):
            self.logger.warning(f"Source addition unsuccessful: '{name}' already exists.")
            raise ConfigUpdateError(
                f"Error: Source '{name}' already exists, please enter a unique name."
            )

        timestamp = time.time()
        try:
            source = Source(
                name=name,
                ip_address=ip_address,
                source_type=source_type,
                active=active,
                description=description,
                captured_at=timestamp,
                updated_at=timestamp,
                line_dict=line_dict,
                resolution_width=resolution_width,
                resolution_height=resolution_height,
            )
            data = self._load()
            data["updated_at"] = timestamp
            data["sources"].append(source.to_dict())
            self._save(data)
            self.logger.info(f"Source '{name}' added.")
            self._refresh()
            return {
                "id": source.id,
                "name": source.name,
                "title_index": source.window_id,
                "enabled": source.active,
                "ipAddress": source.ip_address,
                "lastFrameTimestamp": source.captured_at,
                "effectiveFPS": 0,
                "online": True,
            }
        except Exception as e:
            self.logger.error(f"Error adding source '{name}': {e}")
            raise ConfigUpdateError(f"Error adding source '{name}': {e}")

    def delete_source(self, id: str):
        if not self._source_exists(id):
            self.logger.warning(f"Source delete unsuccessful: '{id}' not found.")
            raise ConfigUpdateError(f"Error: Source '{id}' not found.")

        try:
            data = self._load()
            data["updated_at"] = time.time()
            data["sources"] = [s for s in data["sources"] if s["id"] != id]
            self._save(data)
            self.logger.info(f"Source '{id}' deleted.")
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error deleting source '{id}': {e}")
            raise ConfigUpdateError(f"Error deleting source '{id}': {e}")

    def edit_source(
        self,
        id: str,
        name: str,
        ip_address: str,
        active: bool,
        source_type: str = "RTSP",
        description: Optional[str] = None,
        line_dict: Optional[LineDict] = None,
        resolution_width: Optional[int] = None,
        resolution_height: Optional[int] = None,
    ):
        if not self._source_exists(id):
            self.logger.warning(f"Source edit unsuccessful: '{id}' not found.")
            raise ConfigUpdateError(f"Error: Source '{id}' not found.")

        timestamp = time.time()
        try:
            data = self._load()
            data["updated_at"] = timestamp
            for s in data["sources"]:
                if s["id"] == id:
                    s["name"] = name
                    s["updated_at"] = timestamp
                    s["attributes"]["ip_address"] = ip_address
                    s["attributes"]["source_type"] = source_type
                    s["attributes"]["active"] = active
                    s["attributes"]["description"] = description or "No metadata provided"
                    if resolution_width is not None:
                        s["attributes"]["resolution_width"] = resolution_width
                    if resolution_height is not None:
                        s["attributes"]["resolution_height"] = resolution_height
                    break
            self._save(data)
            self.logger.info(f"Source '{id}' updated.")
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error editing source '{id}': {e}")
            raise ConfigUpdateError(f"Error editing source '{id}': {e}")

    def activate_source(self, id: str):
        if not self._source_exists(id):
            self.logger.warning(f"Source activation unsuccessful: '{id}' not found.")
            raise ConfigUpdateError(f"Source activation unsuccessful: '{id}' not found.")
        if self._source_active(id):
            self.logger.warning(f"Source '{id}' already active.")
            return

        try:
            data = self._load()
            data["updated_at"] = time.time()
            for s in data["sources"]:
                if s["id"] == id:
                    s["attributes"]["active"] = True
                    break
            self._save(data)
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error activating source '{id}': {e}")
            raise ConfigUpdateError(f"Error activating source '{id}': {e}")

    def deactivate_source(self, id: str):
        if not self._source_exists(id):
            self.logger.warning(f"Source deactivation unsuccessful: '{id}' not found.")
            raise ConfigUpdateError(f"Source deactivation unsuccessful: '{id}' not found.")
        if not self._source_active(id):
            self.logger.warning(f"Source '{id}' already inactive.")
            return

        try:
            data = self._load()
            data["updated_at"] = time.time()
            for s in data["sources"]:
                if s["id"] == id:
                    s["attributes"]["active"] = False
                    break
            self._save(data)
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error deactivating source '{id}': {e}")
            raise ConfigUpdateError(f"Error deactivating source '{id}': {e}")

    # --- Lines ---

    def add_line(self, line_mutation: Dict[str, Any]):
        camera_id = line_mutation["cameraId"]
        width = line_mutation.get("resolution_width")
        height = line_mutation.get("resolution_height")
        if width is None or height is None:
            width, height = self._get_source_resolution(camera_id)

        raw_points = [(float(p["x"]), float(p["y"])) for p in line_mutation["points"]]
        point_list = self._clip_normalized_points(
            self._normalize_points(raw_points, width, height)
        )

        line = Line(
            name=line_mutation["name"],
            point_list=point_list,
            crossing_direction=line_mutation.get("crossing_direction"),
        )

        try:
            data = self._load()
            data["updated_at"] = time.time()
            for s in data["sources"]:
                if s["id"] == camera_id:
                    s["attributes"].setdefault("line_dict", {})
                    s["attributes"]["line_dict"][line.id] = line.to_dict()[line.id]
                    break
            self._save(data)
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error adding line to source '{camera_id}': {e}")
            raise ConfigUpdateError(f"Error adding line to source '{camera_id}': {e}")

    def delete_line(self, camera_id: str, line_id: str):
        if not self._source_exists(camera_id):
            raise ConfigUpdateError(f"Source '{camera_id}' not found.")

        try:
            data = self._load()
            data["updated_at"] = time.time()
            for s in data["sources"]:
                if s["id"] == camera_id:
                    s["attributes"].get("line_dict", {}).pop(line_id, None)
                    break
            self._save(data)
            self.logger.info(f"Line '{line_id}' deleted from source '{camera_id}'.")
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error deleting line '{line_id}': {e}")
            raise ConfigUpdateError(f"Error deleting line '{line_id}': {e}")

    def edit_line(self, camera_id: str, line_id: str, line_mutation: Dict[str, Any]):
        if not self._source_exists(camera_id):
            raise ConfigUpdateError(f"Source '{camera_id}' not found.")

        width = line_mutation.get("resolution_width")
        height = line_mutation.get("resolution_height")
        if width is None or height is None:
            width, height = self._get_source_resolution(camera_id)

        raw_points = [(float(p["x"]), float(p["y"])) for p in line_mutation["points"]]
        point_list = self._clip_normalized_points(
            self._normalize_points(raw_points, width, height)
        )

        line = Line(
            name=line_mutation["name"],
            point_list=point_list,
            crossing_direction=line_mutation.get("crossing_direction"),
            id=line_id,
        )

        try:
            data = self._load()
            data["updated_at"] = time.time()
            for s in data["sources"]:
                if s["id"] == camera_id:
                    s["attributes"].setdefault("line_dict", {})
                    s["attributes"]["line_dict"][line_id] = line.to_dict()[line_id]
                    break
            self._save(data)
            self.logger.info(f"Line '{line_id}' updated in source '{camera_id}'.")
            self._refresh()
        except Exception as e:
            self.logger.error(f"Error editing line '{line_id}': {e}")
            raise ConfigUpdateError(f"Error editing line '{line_id}': {e}")
