// Port of golang/authority/authority_test.go.
import { describe, expect, it } from "vitest";
import { AuthorityPolicy, DEFAULT_TIER_KEY, UNKNOWN_RANK, selectByAuthority } from "./authority.js";

interface Src {
  id: string;
  meta?: Record<string, string>;
}
const metaOf = (s: Src) => s.meta;
const ids = (ss: Src[]) => ss.map((s) => s.id);
const tiered = (id: string, tier: string): Src => ({ id, meta: { [DEFAULT_TIER_KEY]: tier } });

describe("authority", () => {
  it("zero policy is the identity", () => {
    const sel = selectByAuthority([tiered("a", "adopted"), tiered("b", "note"), { id: "c" }], metaOf, new AuthorityPolicy());
    expect(ids(sel.candidates)).toEqual(["a", "b", "c"]);
    expect(sel.floorApplied).toBe(false);
  });

  it("ordered sorts stably by tier", () => {
    const p = AuthorityPolicy.ordered(["note", "proposal", "adopted"]);
    const inp = [tiered("n1", "note"), tiered("a1", "adopted"), { id: "u" }, tiered("n2", "note"), tiered("a2", "adopted")];
    expect(ids(selectByAuthority(inp, metaOf, p).candidates)).toEqual(["a1", "a2", "n1", "n2", "u"]);
  });

  it("floor excludes below and unknown", () => {
    const p = AuthorityPolicy.ordered(["note", "proposal", "adopted"], "proposal");
    const sel = selectByAuthority([tiered("n", "note"), tiered("p", "proposal"), { id: "u" }, tiered("a", "adopted")], metaOf, p);
    expect(ids(sel.candidates)).toEqual(["a", "p"]);
    expect(ids(sel.excluded)).toEqual(["n", "u"]);
    expect(sel.floorApplied).toBe(true);
  });

  it("withKey reads another column", () => {
    const p = AuthorityPolicy.ordered(["proposal", "adopted"]).withKey("source_layer");
    expect(p.tierOf({ source_layer: "adopted" })).toEqual({ rank: 1, name: "adopted" });
    expect(p.tierOf({ [DEFAULT_TIER_KEY]: "adopted" }).rank).toBe(UNKNOWN_RANK);
  });
});
