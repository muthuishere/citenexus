// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

// Project GitHub Pages: https://muthuishere.github.io/citenexus
// https://astro.build/config
export default defineConfig({
	site: 'https://muthuishere.github.io',
	base: '/citenexus',
	integrations: [
		starlight({
			plugins: [
				starlightLlmsTxt({
					projectName: 'CiteNexus',
					description:
						'An evidence-integrity layer for retrieval, in Go, JavaScript and Python. Answers only from cited evidence — the exact quote and page — and abstains when the evidence is weak, missing or conflicting. The guarantee is "no ungrounded claim". Python is the batteries-included facade (ingest/ask/evaluate, injected models, S3); Go and JS expose the deterministic cite-or-abstain core at conformance parity.',
					details:
						'Use CiteNexus when a wrong answer is worse than no answer (legal, medical, finance/compliance, enterprise search). Every model is injected (OpenAI-compatible); CiteNexus owns orchestration, storage, retrieval, fusion, grounding, and evaluation. It never guesses: if no retrieved passage supports the question, it emits the pinned refusal "I can\'t answer that from the available evidence."',
				}),
			],
			title: 'CiteNexus',
			tagline: 'Answers you can defend.',
			// In-page nav for the long pages (several run past 200 lines with 8-10 H2s).
			// H2s only, so the right-hand rail stays a map, not a second sidebar.
			tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 2 },
			description:
				'An evidence-integrity layer for retrieval, in Go, JavaScript and Python. Answers only from cited evidence — with the exact quote and page — and abstains when the evidence is weak, missing or conflicting. The guarantee is "no ungrounded claim."',
			customCss: ['@fontsource-variable/inter', './src/styles/citenexus.css'],
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/muthuishere/citenexus' },
			],
			editLink: {
				baseUrl: 'https://github.com/muthuishere/citenexus/edit/main/site/',
			},
			sidebar: [
				{
					label: 'Start here',
					items: [
						{ label: 'Quickstart', slug: 'quickstart' },
						{ label: 'Install — Go, JS, Python', slug: 'install' },
						{ label: 'How it works', slug: 'architecture' },
						{ label: 'The guarantee, and its limits', slug: 'concepts' },
					],
				},
				{
					label: 'What it stops getting wrong',
					items: [
						{ label: 'The claim that does not follow', slug: 'faithfulness' },
						{ label: 'Two sources disagree', slug: 'scenarios/conflicting-sources' },
						{ label: 'The wrong law, quoted correctly', slug: 'authority' },
						{ label: 'The document it cannot read', slug: 'languages' },
						{
							label: 'A model failed and nobody said so',
							link: '/providers/#failure-must-be-sayable',
						},
						{ label: 'Open gap — wrong subject, right source', slug: 'scenarios/subject-scope' },
					],
				},
				{
					label: 'Build it',
					items: [
						{ label: 'Ingest anything', slug: 'ingest' },
						{ label: 'Bulk & batch ingest', slug: 'bulk-ingest' },
						{ label: 'Storage — file-based', slug: 'file-based' },
						{ label: 'Storage — S3-native', slug: 's3' },
						{ label: 'Signals & capabilities', slug: 'signals' },
						{ label: 'Vision — figures as evidence', slug: 'vision' },
						{ label: 'Models & endpoints', slug: 'models' },
						{ label: 'Custom endpoints & auth', slug: 'custom-endpoints' },
						{ label: 'Provider contracts', slug: 'providers' },
						{ label: 'Bring your own model — how to', slug: 'bring-your-own-model' },
						{ label: 'Reranking & retrieval', slug: 'reranking' },
						{ label: 'Graph (GraphRAG)', slug: 'graph' },
						{ label: 'Wiki (navigate-not-cite)', slug: 'wiki' },
					],
				},
				{
					label: 'Read the answer',
					items: [
						{ label: 'Ask & abstain', slug: 'ask' },
						{ label: 'The Result object', slug: 'result' },
						{ label: 'Why did it abstain?', slug: 'abstention' },
						{ label: 'Evaluate', slug: 'evaluate' },
					],
				},
				{
					label: 'Operate it',
					items: [
						{ label: 'Access & partitions', slug: 'access' },
						{ label: 'Revoke a document', slug: 'revoke' },
						{ label: 'Corpus reconciliation', slug: 'scenarios/regulated-audit' },
						{ label: 'Right to erasure', slug: 'scenarios/right-to-erasure' },
					],
				},
				{
					label: 'Worked builds & proof',
					items: [
						{ label: 'Which build?', slug: 'scenarios' },
						{ label: 'Contract review', slug: 'scenarios/contract-review' },
						{ label: 'Multilingual desk', slug: 'scenarios/multilingual-desk' },
						{ label: 'Cross-lingual corpus', slug: 'scenarios/multilingual-corpus' },
						{ label: 'Support assistant', slug: 'scenarios/support-assistant' },
						{ label: 'Evaluate a corpus', slug: 'scenarios/evaluate-a-corpus' },
						{ label: 'Build a domain RAG', slug: 'domain-rag' },
						{ label: 'Worked example: law', slug: 'benchmark-law' },
						{ label: 'Scope — is / is not', slug: 'scope' },
					],
				},
			],
		}),
	],
});
