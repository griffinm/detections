"""Shared `detection_audits` row builder.

The single-detection PATCH (`api.routers.detections`) and the bulk-review
endpoint (`api.routers.labeling`) both insert audit rows; they must produce
byte-identical shapes so `metrics` queries don't have to distinguish.
"""

import uuid

from vd_db.models import DetectionAudit, DetectionModel


def make_audit(
    detection: DetectionModel,
    *,
    reason: str,
    from_class_id: uuid.UUID | None = None,
    to_class_id: uuid.UUID | None = None,
    from_subclass_id: uuid.UUID | None = None,
    to_subclass_id: uuid.UUID | None = None,
) -> DetectionAudit:
    return DetectionAudit(
        detection_id=detection.id,
        reason=reason,
        from_class_id=from_class_id,
        to_class_id=to_class_id,
        from_subclass_id=from_subclass_id,
        to_subclass_id=to_subclass_id,
        model_version_id=detection.model_version_id,
    )
