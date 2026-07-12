// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Project GitHub Pages: https://muthuishere.github.io/citenexus
// https://astro.build/config
export default defineConfig({
	site: 'https://muthuishere.github.io',
	base: '/citenexus',
	integrations: [
		starlight({
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
					label: 'Storage',
					items: [
						{ label: 'File-based', slug: 'file-based' },
						{ label: 'S3-native', slug: 's3' },
					],
				},
				{
					label: 'Build',
					items: [
						{ label: 'Bring your own models', slug: 'models' },
						{ label: 'Ingest anything', slug: 'ingest' },
						{ label: 'Ask & abstain', slug: 'ask' },
						{ label: 'Evaluate', slug: 'evaluate' },
					],
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
