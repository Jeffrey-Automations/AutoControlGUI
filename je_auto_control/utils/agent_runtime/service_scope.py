"""Derive same-user service ownership from reviewed printable ASCII service keys."""
import hashlib
from pathlib import Path

from .service_status import ServiceFailure, ServiceQueryError


def service_scope(service_key: str) -> str:
    """Normalize only the supported ASCII case rules, never guess Unicode SCM aliases."""
    if (type(service_key) is not str or not 1 <= len(service_key) <= 256
            or any(not " " <= char <= "~" or char in "/\\" for char in service_key)):
        raise ServiceQueryError(ServiceFailure.UNSUPPORTED)
    return hashlib.sha256(b"local-scm-ascii-v1\0" + service_key.lower().encode("ascii")).hexdigest()


def service_resource(service_key: str, lock_root: Path | None = None) -> Path:
    """Share a lock across profiles/databases of this OS user, not external SCM clients."""
    root = lock_root if lock_root is not None else Path.home() / ".je_auto_control" / "service_ownership"
    return root / (service_scope(service_key) + ".lock")
