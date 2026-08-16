// Probe A, run against the JS port's faithfulness gates.
//
// v1 = isSupported, the frozen SPEC-PORTS-v1 §4 predicate (kept for the
//      conformance vectors; known unsound — it accepts all nine).
// v2 = isSupportedV2, the ADR-0009 ordered-containment + polarity gate.
import { isSupported } from '../../../../js/dist/gate/gate.js';
import { isSupportedV2 } from '../../../../js/dist/gate/verify-v2.js';

const cases = [
	['legal', 'role inversion', 'The tenant shall indemnify the landlord for damage to the property.', 'The landlord shall indemnify the tenant for damage to the property.'],
	['finance', 'role inversion', 'The borrower pays the lender a fee of 400 basis points.', 'The lender pays the borrower a fee of 400 basis points.'],
	['medical', 'role inversion', 'Ibuprofen increases the effect of warfarin in adult patients.', 'Warfarin increases the effect of ibuprofen in adult patients.'],
	['legal', 'negation deletion', 'The employee shall not disclose confidential information.', 'The employee shall disclose confidential information.'],
	['operations', 'negation deletion', 'The reactor must not be restarted without a signed safety review.', 'The reactor must be restarted without a signed safety review.'],
	['medical', 'negation deletion', 'This medication is not approved for patients under twelve years.', 'This medication is approved for patients under twelve years.'],
	['finance', 'value swap', 'Region A reported 40 million in revenue and region B reported 12 million.', 'Region A reported 12 million in revenue and region B reported 40 million.'],
	['physics', 'value swap', 'The sample melts at 240 kelvin and boils at 610 kelvin.', 'The sample melts at 610 kelvin and boils at 240 kelvin.'],
	['physics', 'comparator inversion', 'Pressure in chamber one is greater than pressure in chamber two.', 'Pressure in chamber two is greater than pressure in chamber one.'],
];

let holes = 0;
let v1Holes = 0;
for (const [domain, attack, passage, answer] of cases) {
	const v1 = isSupported(answer, passage);
	const v2 = isSupportedV2(answer, passage);
	if (v1) v1Holes++;
	if (v2) holes++;
	const verdict = v2 ? 'ACCEPTED (hole)' : 'rejected  (ok)';
	console.log(`  [${domain.padEnd(10)}] ${attack.padEnd(19)} v1=${v1 ? 'accept' : 'reject'} -> v2 ${verdict}`);
}
console.log(`\n  js (v1, frozen): ${v1Holes}/${cases.length} false answers accepted as grounded.`);
console.log(`  js: ${holes}/${cases.length} false answers accepted as grounded.`);
