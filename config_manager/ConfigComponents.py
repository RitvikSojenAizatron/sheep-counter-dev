import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_manager.Line import Line, LineManager
from config_manager.Source import Source, SourceValidationError


class ConfigLoadError(Exception):
    """Raised when there is an error loading config from a JSON file."""
    pass


class ConfigComponent:
    """Base class for a user-configurable pipeline component backed by a local JSON file."""

    def __init__(self, config_path: str, logger: Optional[logging.Logger] = None):
        self._config_path = Path(config_path)
        self.logger = logger or logging.getLogger(__name__)
        self.updated_at: float = 0

    def _load(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            return {}
        with open(self._config_path, "r") as f:
            return json.load(f)

    def _save(self, data: Dict[str, Any]) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(data, f, indent=2)

    def to_pretty_dict(self) -> str:
        return json.dumps(self.to_dict(), indent=4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            key: value
            for key, value in vars(self).items()
            if not key.startswith("_") and key != "logger"
        }

    def load(self) -> None:
        """Reload state from the JSON file. Subclasses override this."""
        raise NotImplementedError


class Sources(ConfigComponent):
    """Manages the active and inactive source list, backed by a local JSON file."""

    def __init__(self, config_path: str, logger: Optional[logging.Logger] = None):
        super().__init__(config_path=config_path, logger=logger)
        self.active_sources: List[Source] = []
        self.inactive_sources: List[Source] = []
        self.load()

    def load(self) -> None:
        """Reload source list from the JSON file."""
        try:
            self.active_sources = []
            self.inactive_sources = []

            data = self._load()
            if not data:
                return

            self.updated_at = data.get("updated_at", 0.0)
            for source_dict in data.get("sources", []):
                if source_dict["attributes"].get("active"):
                    self.active_sources.append(Source.from_dict(source_dict))
                else:
                    self.inactive_sources.append(Source.from_dict(source_dict))

        except SourceValidationError as e:
            raise ConfigLoadError(f"Error loading sources; SourceValidationError: {e}")
        except Exception as e:
            raise ConfigLoadError(f"Error loading sources from '{self._config_path}': {e}")

    def refresh_source_lists(self) -> None:
        for i in reversed(range(len(self.active_sources))):
            source = self.active_sources[i]
            if not source.active:
                self.inactive_sources.append(self.active_sources.pop(i))
        for i in reversed(range(len(self.inactive_sources))):
            source = self.inactive_sources[i]
            if source.active:
                self.active_sources.append(self.inactive_sources.pop(i))

    def inactivate_sources(self, source_names: List[str]) -> None:
        for source_name in source_names:
            source = self.get_source(source_name)
            if source is None:
                self.logger.info(f"Source '{source_name}' not found.")
                return
            source.active = False
        self.refresh_source_lists()

    def get_source(self, source_name: str) -> Optional[Source]:
        for source in self.active_sources:
            if source.name == source_name:
                return source
        for source in self.inactive_sources:
            if source.name == source_name:
                return source
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "active_sources": [s.to_dict() for s in self.active_sources],
            "inactive_sources": [s.to_dict() for s in self.inactive_sources],
        }


class Lines(ConfigComponent):
    """Manages lines across all sources, backed by a local JSON file."""

    def __init__(self, config_path: str, logger: Optional[logging.Logger] = None):
        super().__init__(config_path=config_path, logger=logger)
        self.line_manager: LineManager = LineManager()
        self.load()

    def load(self) -> None:
        """Reload lines by aggregating line_dict entries from every source in sources.json."""
        try:
            data = self._load()
            self.updated_at = data.get("updated_at", 0.0)
            combined: dict = {}
            for source in data.get("sources", []):
                combined.update(source.get("attributes", {}).get("line_dict", {}))
            self.line_manager = LineManager(combined)
        except Exception as e:
            raise ConfigLoadError(f"Error loading lines from '{self._config_path}': {e}")

    def get_line(self, line_id: str) -> Optional[Line]:
        for line in self.line_manager.line_list:
            if line.id == line_id:
                return line
        return None

    def get_line_by_name(self, name: str) -> Optional[Line]:
        for line in self.line_manager.line_list:
            if line.name == name:
                return line
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"line_dict": self.line_manager.to_dict()}
