"""Pure, I/O-free domain primitives shared by every CiteNexus layer."""

from citenexus.domain.partition import PartitionLevel, PartitionPath
from citenexus.domain.trust import TrustMode

__all__ = ["PartitionLevel", "PartitionPath", "TrustMode"]
