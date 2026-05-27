"""kNN sub-class lookup over `subclass_examples`.

Shared by `vd.assign_subclass` (per-detection bootstrap) and
`vd.assign_track_subclass` (per-track vote across member detections). Each
caller runs the query against an embedding, then aggregates the winners
according to its own rules.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DetectionModel, Subclass, SubclassExample


async def knn_subclass(
    session: AsyncSession,
    class_id: uuid.UUID,
    detection_id: uuid.UUID,
    query_vec: object,
    use_face: bool,
) -> tuple[uuid.UUID, float] | None:
    """Return the (subclass_id, confidence) winner of a top-5 cosine kNN.

    The winner is the sub-class with the most votes among the 5 nearest
    example detections; ties break on mean cosine similarity, which is also
    the reported confidence. The detection itself is excluded so an example
    cannot self-confirm.
    """
    emb = DetectionModel.face_embedding if use_face else DetectionModel.object_embedding
    distance = emb.cosine_distance(query_vec)
    rows = (
        await session.execute(
            select(Subclass.id, distance.label("dist"))
            .select_from(SubclassExample)
            .join(DetectionModel, DetectionModel.id == SubclassExample.detection_id)
            .join(Subclass, Subclass.id == SubclassExample.subclass_id)
            .where(
                Subclass.class_id == class_id,
                Subclass.is_active.is_(True),
                DetectionModel.id != detection_id,
                DetectionModel.deleted_at.is_(None),
                emb.is_not(None),
            )
            .order_by(distance)
            .limit(5)
        )
    ).all()
    if not rows:
        return None

    sims: dict[uuid.UUID, list[float]] = {}
    for subclass_id, dist in rows:
        sims.setdefault(subclass_id, []).append(1.0 - float(dist))
    winner = max(sims, key=lambda sid: (len(sims[sid]), sum(sims[sid]) / len(sims[sid])))
    members = sims[winner]
    return winner, sum(members) / len(members)
