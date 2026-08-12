from __future__ import annotations

import uuid
from typing import TypeGuard


def is_valid_execution_id(value: object) -> TypeGuard[str]:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return uuid.UUID(hex=value).hex == value
    except ValueError:
        return False
