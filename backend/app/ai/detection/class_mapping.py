"""YOLO class name -> damage_types.code mapping.

The authoritative mapping ships as model_config.json next to the weights in
MinIO (TechStack §4). This module provides the default mapping for models
trained on the public road-damage dataset (model v1) and a normaliser used
as fallback when a config omits a class.
"""

# Class names as they appear in the v1 training run (data.yaml) -> CDC codes
DEFAULT_CLASS_TO_CODE: dict[str, str] = {
    "pothole": "POTHOLE",
    "Alligator": "ALLIGATOR_CRACK",
    "Longitudinal-Crack": "LONGITUDINAL_CRACK",
    "Lateral-Crack": "LATERAL_CRACK",
    "Edge Cracking": "EDGE_CRACKING",
    "Ravelling": "RAVELLING",
    "Rutting": "RUTTING",
    "Striping": "STRIPING",
}


def normalise(name: str) -> str:
    """Fallback normalisation: 'Edge Cracking' -> 'EDGE_CRACKING'."""
    return name.strip().replace("-", "_").replace(" ", "_").upper()


def resolve_code(class_name: str, config_mapping: dict[str, str] | None) -> str:
    """Resolve a YOLO class name to a damage_types.code.

    Priority: model_config.json mapping > built-in default > normalisation.
    """
    if config_mapping and class_name in config_mapping:
        return config_mapping[class_name]
    if class_name in DEFAULT_CLASS_TO_CODE:
        return DEFAULT_CLASS_TO_CODE[class_name]
    return normalise(class_name)
