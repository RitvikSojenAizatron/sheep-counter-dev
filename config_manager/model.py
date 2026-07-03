class Model:
    def __init__(
        self,
        name: str,
        min_confidence: float,
        frame_buffer_size: int
    ):
        self.name = name
        self.frame_buffer_size = frame_buffer_size
        self.min_confidence = min_confidence

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "min_confidence": self.min_confidence,
            "frame_buffer_size": self.frame_buffer_size
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "Model":
        return cls(
            id=str(doc.get("_id", "")),
            name=doc["name"],
            pgie_config_path=doc["pgie_config_path"],
            active=doc.get("active", False),
            device_licensed=doc.get("device_licensed", False),
            available_labels=doc.get("available_labels", []),
            min_confidence=float(doc.get("min_confidence", 0.25)),
        )


class ModelManager(ConfigComponent):
    """Read cache over the Models collection.

    Loads the active model document from MongoDB and resolves its full label
    vocabulary from the labels file on disk at each config refresh.

    class_ids are never stored in MongoDB — they are always derived from the
    labels file, guaranteeing consistency with what the model actually outputs.
    """

    def __init__(self, mongo_client, logger=None):
        super().__init__(mongo_client=mongo_client, logger=logger)
        self.active_model: Optional[Model] = None
        self._all_labels: Dict[int, str] = {}   # {class_id: label} from file
        self._label_to_id: Dict[str, int] = {}  # inverse index, all labels

    def update_from_config(self) -> None:
        try:
            doc = self.mongo_client.find_one("Models", {"active": True})
        except Exception as e:
            raise MongoUpdateError(f"Error reading Models collection: {e}")

        if doc is None:
            self.logger.warning("No active model found in Models collection.")
            self.active_model = None
            self._all_labels = {}
            self._label_to_id = {}
            return

        self.active_model = Model.from_dict(doc)

        try:
            self._all_labels = LabelFileReader.from_pgie_config(
                self.active_model.pgie_config_path
            )
        except (OSError, ValueError) as e:
            raise MongoUpdateError(
                f"Failed to read labels for model '{self.active_model.name}': {e}"
            )

        self._label_to_id = {label: cid for cid, label in self._all_labels.items()}

        stale = [
            label for label in self.active_model.available_labels
            if label not in self._label_to_id
        ]
        if stale:
            self.logger.warning(
                "Model '%s': available_labels contains entries not found in the labels "
                "file and will be ignored: %s",
                self.active_model.name,
                stale,
            )

    @property
    def all_labels(self) -> List[str]:
        """Every label the model knows about, in class_id order."""
        return [self._all_labels[cid] for cid in sorted(self._all_labels)]

    @property
    def available_labels(self) -> List[str]:
        """Developer-whitelisted labels available to users for detector configuration."""
        if self.active_model is None:
            return []
        return [l for l in self.active_model.available_labels if l in self._label_to_id]

    @property
    def is_licensed(self) -> bool:
        return self.active_model is not None and self.active_model.device_licensed

    def class_id_map_for(self, labels: List[str]) -> Dict[str, int]:
        """{label: class_id} for each label in the given list that exists in the labels file."""
        return {label: self._label_to_id[label] for label in labels if label in self._label_to_id}

    def is_valid_label(self, label: str) -> bool:
        """True if label exists in the active model's labels file."""
        return label in self._label_to_id

    def is_available_label(self, label: str) -> bool:
        """True if label is in the developer-whitelisted available_labels."""
        return self.active_model is not None and label in self.active_model.available_labels

    def write_active_pgie_config(self, output_path: str) -> None:
        """Write a copy of the active model's pgie config with user-tuned
        min_confidence substituted in. The original file is not modified.
        Called by pipeline_app.py before constructing the Pipeline.
        """
        if self.active_model is None:
            raise RuntimeError("No active model — cannot write pgie config.")

        overrides = {
            "pre-cluster-threshold": str(self.active_model.min_confidence),
        }

        with open(self.active_model.pgie_config_path, "r") as f:
            lines = f.readlines()

        out_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("[") or "=" not in stripped:
                out_lines.append(line)
                continue
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in overrides:
                out_lines.append(f"{key}={overrides[key]}\n")
            else:
                out_lines.append(line)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.writelines(out_lines)

        self.logger.info(
            "Wrote active pgie config to %s (min_confidence=%.2f)",
            output_path,
            self.active_model.min_confidence,
        )