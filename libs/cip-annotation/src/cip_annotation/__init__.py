"""CIP training-data flywheel: consent-gated annotation queue + dataset manifests.

Shared by the vision modules that grow the corpus (M07 bat, M08 ball). See the
package README for why the consent gate lives in one place rather than one per
service.
"""

from __future__ import annotations

from cip_annotation.dataset import (
    DatasetVersion,
    dataset_checksum,
    freeze_dataset,
    get_dataset,
)
from cip_annotation.queue import (
    MODALITY_BALL,
    MODALITY_BAT,
    REASON_FAILED,
    REASON_LOW_CONFIDENCE,
    REASON_SAMPLED,
    EnqueueResult,
    SelectedFrame,
    enqueue_frames,
    purge_person,
    queue_size,
)

__version__ = "0.1.0"

__all__ = [
    "MODALITY_BALL",
    "MODALITY_BAT",
    "REASON_FAILED",
    "REASON_LOW_CONFIDENCE",
    "REASON_SAMPLED",
    "DatasetVersion",
    "EnqueueResult",
    "SelectedFrame",
    "__version__",
    "dataset_checksum",
    "enqueue_frames",
    "freeze_dataset",
    "get_dataset",
    "purge_person",
    "queue_size",
]
