import logging

from config_manager.ConfigComponents import ConfigComponent, Lines, Sources


class ConfigManager:
    def __init__(self, sources_config_path: str = "config/sources.json", logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.sources = Sources(config_path=sources_config_path, logger=self.logger)
        self.lines = Lines(config_path=sources_config_path, logger=self.logger)
        #self.model = Model(config_path=sources_config_path, logger=self.logger)
        self.logger.info("ConfigManager initialised")

    def update_all_from_config(self) -> None:
        """Reload every ConfigComponent attribute from its backing file."""
        for attr_name, attr_val in vars(self).items():
            if isinstance(attr_val, ConfigComponent):
                try:
                    attr_val.load()
                except Exception as e:
                    self.logger.error(f"Error reloading {attr_name}: {e}")
