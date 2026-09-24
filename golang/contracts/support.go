package contracts

import "context"

// SupportChecker is an injected judge of whether a passage supports a claim —
// typically an NLI classifier. It exists for the one case the deterministic gate
// cannot handle at all: a claim in one language and its evidence in another
// (token containment cannot verify an English sentence against a Dutch
// passage).
//
// It is NOT trusted the way the gate is, so the library uses it ASYMMETRICALLY
// (see golang/answer.VerifyAnswer):
//
//   - contradicted is a VETO everywhere: a claim the gate accepted is still
//     dropped when the checker says its passage contradicts it. A veto can only
//     add abstention, so it cannot admit an ungrounded claim.
//   - entailed may ADMIT a claim only when the claim's language and the
//     passage's declared language differ, and every such claim is labelled
//     (result.Claim.VerifiedBy) so a caller can refuse to trust it.
//
// Both scores are probabilities in [0, 1]. Failure is an error, never a score:
// (0, 0, nil) is a finding ("neither"), not "I could not run".
type SupportChecker interface {
	Check(ctx context.Context, claim, passage string) (entailed, contradicted float64, err error)
}
