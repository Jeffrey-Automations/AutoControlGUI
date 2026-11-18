"""Check pinned executable bytes through the same bounded resolver view as semantic data."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac

from .models import (
    FailureReason, MemoryObservationError, ProcessIdentity, ReadPlan, ResolverView, ReviewedProbe,
)
from .pe_image import ImageCodePlan


def guard_probe_image(probe: ReviewedProbe, plan: ImageCodePlan, *,
                      image_sha256: str) -> ReviewedProbe:
    """Add complete image-range matching without expanding the host's resource ceilings."""
    if (not isinstance(plan, ImageCodePlan)
            or probe.executable != plan.executable or probe.versions != (plan.version,)
            or "x64" not in probe.architectures or probe.max_bytes <= plan.checked_bytes):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    if not isinstance(image_sha256, str) or not image_sha256.isascii():
        raise MemoryObservationError(FailureReason.UNSUPPORTED)
    if not hmac.compare_digest(plan.image_sha256, image_sha256):
        raise MemoryObservationError(FailureReason.UNSUPPORTED)

    def resolve(identity: ProcessIdentity, view: ResolverView) -> ReadPlan:
        if identity.architecture != "x64" or identity.pointer_bits != 64:
            raise MemoryObservationError(FailureReason.UNSUPPORTED)
        before = view.main_module()
        if before.size != plan.image_size:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        for item in plan.ranges:
            actual = view.read(before.base + item.rva, item.size)
            if not hmac.compare_digest(hashlib.sha256(actual).hexdigest(), item.sha256):
                raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        if view.main_module() != before:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        result = probe.resolve(identity, view)
        if view.main_module() != before:
            raise MemoryObservationError(FailureReason.TARGET_CHANGED)
        return result

    return replace(probe, architectures=("x64",), resolve=resolve)
