import json
import logging
from enum import Enum

from graphiti_core.nodes import EpisodeType

logger = logging.getLogger(__name__)

MAX_DATA_SIZE = 10_000


class DataType(str, Enum):
    MESSAGE = "message"
    TEXT = "text"
    JSON = "json"


def normalize_episode_type(data_type: str | None) -> EpisodeType:
    try:
        return EpisodeType(data_type or DataType.TEXT.value)
    except ValueError:
        return EpisodeType.text


def normalize_episode_body(data: str, data_type: str | None) -> str:
    if len(data) > MAX_DATA_SIZE:
        raise ValueError(
            f"Data exceeds maximum size of {MAX_DATA_SIZE} characters. "
            "Please chunk large documents before ingestion."
        )

    try:
        normalized_type = DataType(data_type or DataType.TEXT.value)
    except ValueError:
        normalized_type = DataType.TEXT
    if normalized_type is DataType.JSON:
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON payload received; falling back to raw text")
            return data
        return _json_to_natural_language(parsed)

    return data


def _json_to_natural_language(obj: object, prefix: str = "") -> str:
    lines: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                nested = _json_to_natural_language(value, full_key)
                if nested:
                    lines.append(nested)
            else:
                lines.append(f"{full_key} is {value}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            full_key = f"{prefix}[{index}]" if prefix else f"item[{index}]"
            if isinstance(item, (dict, list)):
                nested = _json_to_natural_language(item, full_key)
                if nested:
                    lines.append(nested)
            else:
                lines.append(f"{full_key} is {item}")
    elif prefix:
        lines.append(f"{prefix} is {obj}")

    return ". ".join(line for line in lines if line)
