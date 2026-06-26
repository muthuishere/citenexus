"""Allowed-partitions hard pre-filter + optional opaque-acl predicate (spec §7c)."""

from trustrag.access import allowed_partition, apply_acl_predicate, filter_partitions
from trustrag.domain.partition import PartitionPath

ACME_CONTRACTS = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
ACME_CONTRACTS_NDA = PartitionPath.of(
    ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
)
ACME_HR = PartitionPath.of(("org", "acme"), ("product_line", "hr"))
GLOBEX_CONTRACTS = PartitionPath.of(("org", "globex"), ("product_line", "contracts"))


def test_exact_allowed_path_permits_its_partition() -> None:
    assert allowed_partition(ACME_CONTRACTS, {ACME_CONTRACTS})


def test_descendant_of_allowed_prefix_is_allowed() -> None:
    # A principal authorized at a prefix sees the whole sub-tree below it.
    assert allowed_partition(ACME_CONTRACTS_NDA, {ACME_CONTRACTS})


def test_disallowed_sibling_partition_is_rejected() -> None:
    assert not allowed_partition(ACME_HR, {ACME_CONTRACTS})
    assert not allowed_partition(GLOBEX_CONTRACTS, {ACME_CONTRACTS})


def test_ancestor_of_allowed_path_is_not_allowed() -> None:
    # Authorized at acme/contracts/nda does NOT grant the broader acme/contracts.
    assert not allowed_partition(ACME_CONTRACTS, {ACME_CONTRACTS_NDA})


def test_empty_allowed_set_rejects_everything() -> None:
    assert not allowed_partition(ACME_CONTRACTS, set())
    assert not allowed_partition(ACME_CONTRACTS_NDA, frozenset())


def test_filter_partitions_drops_disallowed_and_preserves_order() -> None:
    candidates = [ACME_CONTRACTS, ACME_HR, ACME_CONTRACTS_NDA, GLOBEX_CONTRACTS]
    kept = filter_partitions(candidates, {ACME_CONTRACTS})
    assert kept == [ACME_CONTRACTS, ACME_CONTRACTS_NDA]


def test_filter_partitions_empty_allowed_set_yields_nothing() -> None:
    candidates = [ACME_CONTRACTS, ACME_CONTRACTS_NDA]
    assert filter_partitions(candidates, set()) == []


def test_filter_partitions_with_union_of_prefixes() -> None:
    candidates = [ACME_CONTRACTS_NDA, ACME_HR, GLOBEX_CONTRACTS]
    kept = filter_partitions(candidates, {ACME_CONTRACTS, GLOBEX_CONTRACTS})
    assert kept == [ACME_CONTRACTS_NDA, GLOBEX_CONTRACTS]


# --- optional opaque-acl predicate -----------------------------------------


class _Obj:
    """A candidate EU/object carrying an opaque ``acl`` the library never reads."""

    def __init__(self, name: str, acl: object) -> None:
        self.name = name
        self.acl = acl


def test_acl_predicate_filters_remaining_objects() -> None:
    objs = [_Obj("a", {"role": "partner"}), _Obj("b", {"role": "intern"})]
    kept = apply_acl_predicate(
        objs,
        acl_of=lambda o: o.acl,
        predicate=lambda acl: isinstance(acl, dict) and acl.get("role") == "partner",
    )
    assert [o.name for o in kept] == ["a"]


def test_acl_predicate_default_true_keeps_everything() -> None:
    objs = [_Obj("a", None), _Obj("b", {"x": 1})]
    kept = apply_acl_predicate(objs, acl_of=lambda o: o.acl)
    assert kept == objs


def test_acl_is_never_parsed_only_the_predicate_sees_it() -> None:
    # An acl whose every comparison/parse would blow up; only the predicate,
    # which we control, ever touches it — the library passes it through opaque.
    class Explosive:
        def __eq__(self, other: object) -> bool:
            raise AssertionError("library parsed the acl")

        def __hash__(self) -> int:
            raise AssertionError("library hashed the acl")

        def __bool__(self) -> bool:
            raise AssertionError("library coerced the acl")

    seen: list[object] = []
    sentinel = Explosive()
    objs = [_Obj("a", sentinel)]

    def predicate(acl: object) -> bool:
        seen.append(acl)
        return True

    kept = apply_acl_predicate(objs, acl_of=lambda o: o.acl, predicate=predicate)

    assert kept == objs
    assert len(seen) == 1
    assert seen[0] is sentinel  # the exact opaque object, untouched
