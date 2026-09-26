// The standing of a SOURCE, kept strictly apart from grounding (ADR-0004).
// Port of golang/authority/authority.go (itself a port of
// python/src/citenexus/domain/authority.py and the strict branch of
// python/src/citenexus/answer/authority.py).
//
// The faithfulness gate proves an answer's words came from the passage it cites.
// It cannot prove the passage had any standing to answer. Two rules carry over
// unchanged:
//
//   - Metadata-derived, never content-derived. A policy maps caller-supplied
//     METADATA to a tier and is never handed a passage.
//   - Applied strictly AFTER grounding. Selection may reorder evidence and, under
//     a floor, drop it — never promote it — so the only reachable behaviour
//     change is more abstention.
//
// The zero policy (`new AuthorityPolicy()`) ranks every source equal and has no
// floor: the stable sort is then the identity. The feature is strictly opt-in.

/** The metadata key an ordered policy reads by default. */
export const DEFAULT_TIER_KEY = "authority_tier";

/** The rank of a tier the policy does not know — including missing metadata. */
export const UNKNOWN_RANK = -1;

/** The refusal reason when the floor emptied the selection. Byte-identical to
 * the Python and Go references. */
export const INSUFFICIENT_AUTHORITY = "no evidence at or above the required authority tier";

/** A totally-ordered standing. Higher rank = more authoritative. `name` is
 * reporting-only and never compared. */
export interface AuthorityTier {
  readonly rank: number;
  readonly name: string;
}

/** True when `t` is strictly more authoritative than `other`. */
export function tierOutranks(t: AuthorityTier, other: AuthorityTier): boolean {
  return t.rank > other.rank;
}

/**
 * An ordering of tier names plus an optional floor. The zero value
 * (`new AuthorityPolicy()`) is the reference's default.v1 with no floor: every
 * source unranked (rank 0).
 */
export class AuthorityPolicy {
  readonly #rank: ReadonlyMap<string, number> | null;
  readonly #key: string;
  readonly #minimum: AuthorityTier | null;

  constructor(
    rank: ReadonlyMap<string, number> | null = null,
    key: string = DEFAULT_TIER_KEY,
    minimum: AuthorityTier | null = null,
  ) {
    this.#rank = rank;
    this.#key = key;
    this.#minimum = minimum;
  }

  /**
   * The reference's ordered.v1 policy. `order` is LEAST-authoritative first.
   * `minimumTier` is the strict-mode floor by tier name; "" means no floor. A
   * floor name absent from `order` ranks UNKNOWN_RANK, which floors nothing out
   * of the named tiers — so name it from `order`.
   */
  static ordered(order: readonly string[], minimumTier = ""): AuthorityPolicy {
    const rank = new Map<string, number>();
    order.forEach((name, i) => rank.set(name, i));
    const p = new AuthorityPolicy(rank, DEFAULT_TIER_KEY, null);
    if (minimumTier === "") return p;
    return new AuthorityPolicy(rank, DEFAULT_TIER_KEY, p.tierNamed(minimumTier));
  }

  /** A copy that reads its tier name from `key` instead of DEFAULT_TIER_KEY. */
  withKey(key: string): AuthorityPolicy {
    return new AuthorityPolicy(this.#rank, key, this.#minimum);
  }

  /** True when the policy enforces a minimum tier. */
  get hasFloor(): boolean {
    return this.#minimum !== null;
  }

  /** The tier for a source's METADATA — never its text. */
  tierOf(meta: Readonly<Record<string, string>> | null | undefined): AuthorityTier {
    if (this.#rank === null) return { rank: 0, name: "" }; // default.v1: everything unranked
    const key = this.#key === "" ? DEFAULT_TIER_KEY : this.#key;
    const name = meta !== null && meta !== undefined && Object.hasOwn(meta, key) ? (meta[key] as string) : "";
    const r = this.#rank.get(name);
    if (r !== undefined) return { rank: r, name };
    return { rank: UNKNOWN_RANK, name };
  }

  /** The tier for a bare tier NAME — how a caller states a floor. */
  tierNamed(name: string): AuthorityTier {
    const key = this.#key === "" ? DEFAULT_TIER_KEY : this.#key;
    return this.tierOf({ [key]: name });
  }

  /** True when `t` is at or above the floor, or there is no floor. */
  meetsFloor(t: AuthorityTier): boolean {
    return this.#minimum === null || t.rank >= this.#minimum.rank;
  }
}

/** The selected candidates plus what authority did to get there. */
export interface AuthoritySelection<E> {
  /** The floor survivors, most authoritative first; equal tiers keep input order. */
  candidates: E[];
  /** Grounded but dropped for standing — kept so a refusal can say what it declined to cite. */
  excluded: E[];
  /** True when the floor actually WITHHELD evidence — not merely configured. */
  floorApplied: boolean;
}

/**
 * The reference's strict-mode select_by_authority: enforce the floor
 * (below-floor candidates are excluded outright, with no fallback), then a
 * STABLE sort by descending tier. No secondary key. `meta` is the only view of a
 * candidate selection gets: it cannot read the passage.
 */
export function selectByAuthority<E>(
  candidates: readonly E[],
  meta: (c: E) => Readonly<Record<string, string>> | null | undefined,
  policy: AuthorityPolicy,
): AuthoritySelection<E> {
  const kept: { c: E; tier: AuthorityTier }[] = [];
  const excluded: E[] = [];
  for (const c of candidates) {
    const t = policy.tierOf(meta(c));
    if (!policy.meetsFloor(t)) {
      excluded.push(c);
      continue;
    }
    kept.push({ c, tier: t });
  }
  // Array.prototype.sort is stable (ES2019).
  kept.sort((a, b) => b.tier.rank - a.tier.rank);
  return { candidates: kept.map((k) => k.c), excluded, floorApplied: excluded.length > 0 };
}
