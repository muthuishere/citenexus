"""Pure, I/O-free domain primitives shared by every TrustRAG layer."""

from trustrag.domain.partition import PartitionLevel, PartitionPath
from trustrag.domain.trust import TrustMode

__all__ = ["PartitionLevel", "PartitionPath", "TrustMode"]
