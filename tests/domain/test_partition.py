"""PartitionPath — variable-depth hierarchy with prefix addressing (spec §6b)."""

from trustrag.domain.partition import PartitionPath


def test_variable_depth_paths() -> None:
    p3 = PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )
    p1 = PartitionPath.of(("workspace", "w1"))
    assert p3.depth == 3
    assert p1.depth == 1


def test_equality_is_order_sensitive() -> None:
    a = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    b = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    reordered = PartitionPath.of(("product_line", "contracts"), ("org", "acme"))
    assert a == b
    assert a != reordered


def test_is_prefix_of() -> None:
    a = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    b = PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )
    assert a.is_prefix_of(b)
    assert not b.is_prefix_of(a)


def test_divergent_path_is_not_a_prefix() -> None:
    a = PartitionPath.of(("org", "acme"), ("product_line", "hr"))
    b = PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda")
    )
    assert not a.is_prefix_of(b)


def test_as_pairs_view() -> None:
    a = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    assert a.as_pairs() == (("org", "acme"), ("product_line", "contracts"))


def test_json_round_trip() -> None:
    a = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    assert PartitionPath.model_validate_json(a.model_dump_json()) == a
