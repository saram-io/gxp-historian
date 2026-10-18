import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { visit } from 'unist-util-visit';

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function remarkMermaid() {
  return (tree) => {
    visit(tree, 'code', (node) => {
      if (node.lang === 'mermaid') {
        const escaped = escapeHtml(node.value);
        node.type = 'html';
        node.value = `<div class="mermaid-wrapper"><pre class="mermaid" data-mermaid-src="${escaped}">${escaped}</pre></div>`;
      }
    });
  };
}

export default defineConfig({
  site: 'https://gxphistorian.com',
  markdown: {
    remarkPlugins: [remarkMermaid, remarkMath],
    rehypePlugins: [rehypeKatex],
  },
  integrations: [
    starlight({
      title: 'GxPHistorian',
      description:
        'A 21 CFR Part 11, EU GMP Annex 11, and ISPE GAMP 5 Qualified Open-Source Industrial Time-Series Historian & Asset Framework',
      logo: {
        src: './src/assets/logo.svg',
      },
      social: {
        github: 'https://github.com/saram-io/gxp-historian',
      },
      head: [
        {
          tag: 'link',
          attrs: {
            rel: 'preconnect',
            href: 'https://fonts.googleapis.com',
          },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'preconnect',
            href: 'https://fonts.gstatic.com',
            crossorigin: true,
          },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'stylesheet',
            href: 'https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=Noto+Serif+KR:wght@400;600;700&family=Playfair+Display:ital,wght@0,400..900;1,400..900&family=Roboto+Mono:ital,wght@0,100..700;1,100..700&display=swap',
          },
        },
      ],
      customCss: ['./src/styles/custom.css'],
      components: {
        Header: './src/components/Header.astro',
        Footer: './src/components/Footer.astro',
      },
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 3,
      },
      sidebar: [
        {
          label: 'Getting Started',
          items: [
            { label: 'Documentation Portal Home', slug: 'docs' },
            { label: 'Overview & PI System Parity', slug: 'docs/getting-started/overview' },
            { label: 'Quickstart & Deployment', slug: 'docs/getting-started/quickstart' },
          ],
        },
        {
          label: 'Architecture & Part 11 Controls',
          items: [
            { label: '4-Pillar System Architecture', slug: 'docs/architecture/four-pillar-architecture' },
            { label: '21 CFR Part 11 & ALCOA+ Controls', slug: 'docs/architecture/part11-compliance' },
            { label: 'Hardware Sizing & Capacity Planning', slug: 'docs/architecture/hardware-sizing' },
          ],
        },
        {
          label: 'REST API, AI / MCP, HMI & Excel',
          items: [
            { label: 'REST API Reference (historian-api)', slug: 'docs/clients-and-api/rest-api-reference' },
            { label: 'Pydantic AI Co-Pilot & MCP Server', slug: 'docs/clients-and-api/pydantic-ai-and-mcp' },
            { label: 'Grafana Vision Operator HMI', slug: 'docs/clients-and-api/grafana-vision-hmi' },
            { label: 'Excel DataLink Client (Power Query & UDFs)', slug: 'docs/clients-and-api/excel-datalink' },
          ],
        },
        {
          label: 'Connectors & Protocols Reference',
          items: [
            { label: 'Connectors & Wiring Encyclopedia', slug: 'docs/connectors/overview' },
            { label: 'OPC UA (:4840) & Classic OPC DA (COM)', slug: 'docs/connectors/opc-ua-and-opc-da' },
            { label: 'BACnet/IP (:47808) & BACnet MS/TP', slug: 'docs/connectors/bacnet-ip-and-mstp' },
            { label: 'Modbus TCP (:502) & Modbus RTU (RS-485)', slug: 'docs/connectors/modbus-tcp-and-rtu' },
            { label: 'Siemens S7, EtherNet/IP, HART, RS-232 & UFL', slug: 'docs/connectors/plc-s7-ethernetip-hart-serial-ufl' },
          ],
        },
        {
          label: 'Biopharma & Legacy Equipment Guides',
          items: [
            { label: 'Master Biopharma Instrument Catalog', slug: 'docs/biopharma-integration/catalog' },
            { label: 'Cytiva Xcellerex X-Platform (Figurate)', slug: 'docs/biopharma-integration/xcellerex-x-platform' },
            { label: 'USP Bioreactors (Sartorius, Thermo, Eppendorf)', slug: 'docs/biopharma-integration/usp-bioreactors' },
            { label: 'At-Line PAT & In-Line Spectroscopy', slug: 'docs/biopharma-integration/pat-analyzers-spectroscopy' },
            { label: 'DSP Chromatography & TFF Filtration', slug: 'docs/biopharma-integration/dsp-chromatography-tff' },
            { label: 'Cell & Gene Therapy, mRNA-LNP & CRFs', slug: 'docs/biopharma-integration/cgt-mrna-lnp-instruments' },
            { label: 'Aseptic Fill-Finish, Lyo & GMP Utilities', slug: 'docs/biopharma-integration/aseptic-fill-finish-lyo-utilities' },
            { label: 'Stability Chambers, Cold Chain & Autoclaves', slug: 'docs/biopharma-integration/stability-chambers-cold-chain-autoclaves' },
            { label: 'Legacy Fieldbus (BACnet, OPC DA, Modbus, S7)', slug: 'docs/biopharma-integration/legacy-protocols' },
            { label: 'Legacy RS-232 Serial & PI UFL Replacement', slug: 'docs/biopharma-integration/legacy-serial-rs232-pi-ufl' },
          ],
        },
        {
          label: 'GAMP 5 & CSA Validation Binder',
          items: [
            { label: 'Qualification Suite & Binder Overview', slug: 'docs/gxp-validation/overview' },
            { label: '01 — Validation Master Plan (VMP)', slug: 'docs/gxp-validation/01-vmp' },
            { label: '02 — User Requirements Specification (URS)', slug: 'docs/gxp-validation/02-urs' },
            { label: '03 — Functional & Design Spec (FDS)', slug: 'docs/gxp-validation/03-fds' },
            { label: '04 — CSA Functional Risk Assessment (FRA)', slug: 'docs/gxp-validation/04-fra' },
            { label: '05 — SOUP / OSS Vendor Dossier', slug: 'docs/gxp-validation/05-soup-dossier' },
            { label: '06 — Executed IQ/OQ Evidence Report', slug: 'docs/gxp-validation/06-iq-oq-evidence' },
            { label: '07 — Requirements Traceability Matrix (RTM)', slug: 'docs/gxp-validation/07-rtm' },
            { label: '08 — Validation Summary Report (VSR)', slug: 'docs/gxp-validation/08-vsr' },
          ],
        },
      ],
    }),
  ],
});
