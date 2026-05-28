# Proposals

A registry of concrete changes under consideration but **not yet committed**.
Proposals live here — not in the numbered specs — so the specs remain
canonical definitions of how the app actually works today.

Each entry states the *change*, the *motivation*, and the main *tradeoff*
so a future reader can decide whether to promote it into the relevant spec
(and implement it) or drop it.

When you accept a proposal: implement it, update the relevant spec in the
same change, and delete the entry here. When you reject a proposal: delete
it (or move a short rationale into the relevant spec's "Open questions").

## ML / Training

### Body-embedding fallback for `person` sub-class

**Change.** When a `person` detection has no `face_embedding` (back of head,
occluded face, low-res crop), fall back to a DINOv2 `object_embedding` on
the person crop for sub-class identification. Implemented as a *separate*
per-class "body" classifier (`kind='classifier'`, distinct from the existing
face classifier) that only votes when the face classifier abstains; do not
fuse 512-d face + 768-d DINOv2 into one head.

**Motivation.** Today a back-of-head label seeds `subclass_examples` but is
useless for kNN (no face vector) and is dropped from Regime B classifier
training. The detector still benefits from the reviewed bbox, but the
recognizer learns nothing from those labels.

**Tradeoff.** DINOv2 on a person crop mostly encodes clothing + pose, so
the body signal is strong *within* a clip (same outfit, same day) and
unreliable *across* clips/days. Risk: confidently mislabeling identities
when two people wear similar clothing, or when the same person changes
outfit. Mitigation candidates: cap body-classifier confidence below face-
classifier confidence, time-decay body examples, or restrict body voting
to within-track propagation only.

**Spec touched if accepted.** `06-ml-training.md` (sub-class assignment
regimes, model registry) and possibly `03-data-model.md` (no schema change
expected — `object_embedding` already exists).
