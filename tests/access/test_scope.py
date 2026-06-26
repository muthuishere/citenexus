"""Query-scope resolution into a PartitionPath prefix (spec §7c, §6b)."""

import pytest

from trustrag.access import resolve_scope
from trustrag.domain.partition import PartitionPath

HIERARCHY = ("org", "product_line", "product")


def test_full_scope_resolves_to_leaf_path() -> None:
    scope = {"org": "acme", "product_line": "contracts", "product": "nda-review"}
    path = resolve_scope(scope, HIERARCHY)
    assert path == PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )
    assert path.depth == 3


def test_partial_scope_resolves_to_prefix_subtree() -> None:
    scope = {"org": "acme", "product_line": "contracts"}
    path = resolve_scope(scope, HIERARCHY)
    assert path == PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
    assert path.depth == 2


def test_root_only_scope_resolves_to_depth_one_prefix() -> None:
    path = resolve_scope({"org": "acme"}, HIERARCHY)
    assert path == PartitionPath.of(("org", "acme"))


def test_empty_scope_resolves_to_empty_root_prefix() -> None:
    path = resolve_scope({}, HIERARCHY)
    assert path.depth == 0


def test_resolved_prefix_is_prefix_of_descendant_leaves() -> None:
    prefix = resolve_scope({"org": "acme", "product_line": "contracts"}, HIERARCHY)
    leaf = resolve_scope(
        {"org": "acme", "product_line": "contracts", "product": "nda-review"}, HIERARCHY
    )
    assert prefix.is_prefix_of(leaf)


def test_gap_in_scope_is_rejected() -> None:
    # product present but product_line missing — a prefix may not skip a level.
    with pytest.raises(ValueError, match="product_line"):
        resolve_scope({"org": "acme", "product": "nda-review"}, HIERARCHY)


def test_unknown_scope_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="region"):
        resolve_scope({"org": "acme", "region": "eu"}, HIERARCHY)
