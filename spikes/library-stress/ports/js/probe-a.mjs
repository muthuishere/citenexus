// Probe A, run against the JS port's ASK FLOW.
//
// It used to call isSupported / isSupportedV2 directly and report "0/9
// accepted". That was true of the FUNCTION and false of the library: the shipped
// flow (askWith / ask) was still calling the frozen v1 predicate, so all nine
// lies came out as grounded answers while this probe printed a clean sheet. A
// probe that can pass while the shipped path is broken is worse than no probe —
// it is the "green suite as camouflage" failure ADR-0014 documents.
//
// So the probe now drives the FLOW. Each case is a one-document corpus holding
// the true passage plus an injected generator that returns the falsified answer;
// the question shares content tokens with the passage, so retrieval and the
// relevance gate both pass and the ONLY thing between the lie and the caller is
// the faithfulness gate the flow actually calls.
//
// Requires a built package: `cd js && npm run build`.
import { askWith } from '../../../../js/dist/answer/answer.js';
import { Decision } from '../../../../js/dist/result/result.js';
import { isSupported } from '../../../../js/dist/gate/gate.js';
import { isSupportedV2 } from '../../../../js/dist/gate/verify-v2.js';

const cases = [
	['legal', 'role inversion', 'Who shall indemnify whom for damage to the property?', 'The tenant shall indemnify the landlord for damage to the property.', 'The landlord shall indemnify the tenant for damage to the property.'],
	['finance', 'role inversion', 'Who pays the fee of 400 basis points?', 'The borrower pays the lender a fee of 400 basis points.', 'The lender pays the borrower a fee of 400 basis points.'],
	['medical', 'role inversion', 'Which drug increases the effect of the other in adult patients?', 'Ibuprofen increases the effect of warfarin in adult patients.', 'Warfarin increases the effect of ibuprofen in adult patients.'],
	['legal', 'negation deletion', 'May the employee disclose confidential information?', 'The employee shall not disclose confidential information.', 'The employee shall disclose confidential information.'],
	['operations', 'negation deletion', 'May the reactor be restarted without a signed safety review?', 'The reactor must not be restarted without a signed safety review.', 'The reactor must be restarted without a signed safety review.'],
	['medical', 'negation deletion', 'Is this medication approved for patients under twelve years?', 'This medication is not approved for patients under twelve years.', 'This medication is approved for patients under twelve years.'],
	['finance', 'value swap', 'What revenue did region A and region B report?', 'Region A reported 40 million in revenue and region B reported 12 million.', 'Region A reported 12 million in revenue and region B reported 40 million.'],
	['physics', 'value swap', 'At what temperature does the sample melt and boil?', 'The sample melts at 240 kelvin and boils at 610 kelvin.', 'The sample melts at 610 kelvin and boils at 240 kelvin.'],
	['physics', 'comparator inversion', 'Which chamber has the greater pressure?', 'Pressure in chamber one is greater than pressure in chamber two.', 'Pressure in chamber two is greater than pressure in chamber one.'],
];

/** A generator that says exactly what it is told to say — a stand-in for a model
 *  that hallucinates a plausible inversion of its own evidence. */
const saying = (reply) => ({ answer: () => reply });

let holes = 0;
let blindControls = 0;
for (const [domain, attack, question, passage, answer] of cases) {
	const corpus = [{ document_id: 'd1', text: passage }];

	// The attack: the flow must refuse.
	const res = await askWith(corpus, question, { generator: saying(answer) });
	const answered = res.evidence.decision === Decision.answered;

	// The control: quoting the passage back must still be answered, or the
	// "0 holes" reading is just a gate that refuses everything.
	const ctl = await askWith(corpus, question, { generator: saying(passage) });
	const controlOK = ctl.evidence.decision === Decision.answered;

	if (answered) holes++;
	if (!controlOK) blindControls++;

	const verdict = answered ? 'ANSWERED (hole)' : 'REFUSED   (ok)';
	const control = controlOK ? 'quote answered' : 'QUOTE REFUSED (gate is blind)';
	const label = (accept) => (accept ? 'accept' : 'reject');
	console.log(
		`  [${domain.padEnd(10)}] ${attack.padEnd(19)} predicate v1=${label(isSupported(answer, passage))}` +
			` v2=${label(isSupportedV2(answer, passage))} -> flow ${verdict}, ${control}`,
	);
}

console.log(`\n  js (FLOW, askWith): ${holes}/${cases.length} false answers emitted to the caller.`);
console.log(`  js (FLOW control): ${blindControls}/${cases.length} verbatim quotes wrongly refused.`);
if (holes > 0 || blindControls > 0) process.exit(1);
