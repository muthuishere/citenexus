"""Partition → prefix resolution (spec §6b)."""

from trustrag.domain.partition import PartitionPath
from trustrag.storage.paths import Layer, layer_prefix, leaf_vector_uri, partition_segment


def test_three_level_segment() -> None:
    p = PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )
    assert partition_segment(p) == "org=acme/product_line=contracts/product=nda-review"
    assert (
        layer_prefix(Layer.raw, p)
        == "raw/org=acme/product_line=contracts/product=nda-review"
    )


def test_single_level_prefix() -> None:
    p = PartitionPath.of(("workspace", "w1"))
    assert layer_prefix(Layer.vector, p) == "vector/workspace=w1"


def test_leaf_vector_uri() -> None:
    p = PartitionPath.of(("workspace", "w1"))
    assert (
        leaf_vector_uri("s3://bucket", p) == "s3://bucket/vector/workspace=w1/lancedb"
    )
