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
						'Evidence-first, multilingual, S3-native RAG for Go, JavaScript and Python. Answers only from cited evidence — the exact quote, page and bbox — and abstains when the evidence is weak, missing or conflicting. The guarantee is "no ungrounded claim". Python is the batteries-included facade (ingest/ask/evaluate, injected models, S3); Go and JS expose the deterministic cite-or-abstain core at conformance parity.',
					details:
						'Use CiteNexus when a wrong answer is worse than no answer (legal, medical, finance/compliance, enterprise search). Every model is injected (OpenAI-compatible); CiteNexus owns orchestration, storage, retrieval, fusion, grounding, and evaluation. It never guesses: if no retrieved passage supports the question, it emits the pinned refusal "I can\'t answer that from the available evidence."',
				}),
			],
			title: 'CiteNexus',
			tagline: 'Answers you can defend.',
			description:
				'Evidence-first, multilingual, S3-native RAG for Go, JavaScript and Python. Answers only from cited evidence — with the exact quote, page and bbox — and abstains when the evidence is weak, missing or conflicting. The guarantee is "no ungrounded claim."',
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
						{ label: 'How it holds the line', slug: 'concepts' },
					],
				},
				{
					label: 'Storage & access',
					items: [
						{ label: 'File-based', slug: 'file-based' },
						{ label: 'S3-native', slug: 's3' },
						{ label: 'Access & partitions', slug: 'access' },
					],
				},
				{
					label: 'Ingest',
					items: [
						{ label: 'Ingest anything', slug: 'ingest' },
						{ label: 'Signals & capabilities', slug: 'signals' },
						{ label: 'Vision — figures as evidence', slug: 'vision' },
					],
				},
				{
					label: 'Retrieve & answer',
					items: [
						{ label: 'Bring your own models', slug: 'models' },
						{ label: 'Reranking & retrieval', slug: 'reranking' },
						{ label: 'Ask & abstain', slug: 'ask' },
						{ label: 'The Result object', slug: 'result' },
						{ label: 'Languages & multilingual', slug: 'languages' },
					],
				},
				{
					label: 'Evaluate',
					items: [{ label: 'Evaluate', slug: 'evaluate' }],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'Install — Go, JS, Python', slug: 'install' },
						{ label: 'Scope — is / is not', slug: 'scope' },
					],
				},
			],
		}),
	],
});
