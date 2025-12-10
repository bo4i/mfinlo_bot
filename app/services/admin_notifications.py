import json
import logging

from app.db.models import Request

logger = logging.getLogger(__name__)


def load_admin_message_map(request: Request) -> dict[int, int]:
    if not request.admin_message_map:
        return {}
    try:
        data = json.loads(request.admin_message_map)
        return {int(key): int(value) for key, value in data.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось прочитать admin_message_map для заявки %s: %s", request.id, exc)
        return {}


def save_admin_message_map(request: Request, mapping: dict[int, int]) -> None:
    try:
        request.admin_message_map = json.dumps(mapping)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось сохранить admin_message_map для заявки %s: %s", request.id, exc)