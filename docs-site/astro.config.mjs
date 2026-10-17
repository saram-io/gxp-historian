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
  site: 'https://gxphistorian-docs.cloud-expert1666.workers.dev',
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
      customCss: ['./src/styles/custom.css'],
      components: {
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
            { label: 'Overview & PI System Parity', slug: 'getting-started/overview' },
            { label: 'Quickstart & Deployment', slug: 'getting-started/quickstart' },
          ],
        },
        {
          label: 'Architecture & Part 11 Controls',
          items: [
            { label: '4-Pillar System Architecture', slug: 'architecture/four-pillar-architecture' },
            { label: '21 CFR Part 11 & ALCOA+ Controls', slug: 'architecture/part11-compliance' },
            { label: 'Hardware Sizing & Capacity Planning', slug: 'architecture/hardware-sizing' },
          ],
        },
        {
          label: 'REST API, HMI & Excel DataLink',
          items: [
            { label: 'REST API Reference (historian-api)', slug: 'clients-and-api/rest-api-reference' },
            { label: 'Grafana Vision Operator HMI', slug: 'clients-and-api/grafana-vision-hmi' },
            { label: 'Excel DataLink Client (Power Query & UDFs)', slug: 'clients-and-api/excel-datalink' },
          ],
        },
        {
          label: 'Connectors & Protocols Reference',
          items: [
            { label: 'Connectors & Wiring Encyclopedia', slug: 'connectors/overview' },
            { label: 'OPC UA (:4840) & Classic OPC DA (COM)', slug: 'connectors/opc-ua-and-opc-da' },
            { label: 'BACnet/IP (:47808) & BACnet MS/TP', slug: 'connectors/bacnet-ip-and-mstp' },
            { label: 'Modbus TCP (:502) & Modbus RTU (RS-485)', slug: 'connectors/modbus-tcp-and-rtu' },
            { label: 'Siemens S7, EtherNet/IP, HART, RS-232 & UFL', slug: 'connectors/plc-s7-ethernetip-hart-serial-ufl' },
          ],
        },
        {
          label: 'Biopharma & Legacy Equipment Guides',
          items: [
            { label: 'Master Biopharma Instrument Catalog', slug: 'biopharma-integration/catalog' },
            { label: 'Cytiva Xcellerex X-Platform (Figurate)', slug: 'biopharma-integration/xcellerex-x-platform' },
            { label: 'USP Bioreactors (Sartorius, Thermo, Eppendorf)', slug: 'biopharma-integration/usp-bioreactors' },
            { label: 'At-Line PAT & In-Line Spectroscopy', slug: 'biopharma-integration/pat-analyzers-spectroscopy' },
            { label: 'DSP Chromatography & TFF Filtration', slug: 'biopharma-integration/dsp-chromatography-tff' },
            { label: 'Cell & Gene Therapy, mRNA-LNP & CRFs', slug: 'biopharma-integration/cgt-mrna-lnp-instruments' },
            { label: 'Aseptic Fill-Finish, Lyo & GMP Utilities', slug: 'biopharma-integration/aseptic-fill-finish-lyo-utilities' },
            { label: 'Stability Chambers, Cold Chain & Autoclaves', slug: 'biopharma-integration/stability-chambers-cold-chain-autoclaves' },
            { label: 'Legacy Fieldbus (BACnet, OPC DA, Modbus, S7)', slug: 'biopharma-integration/legacy-protocols' },
            { label: 'Legacy RS-232 Serial & PI UFL Replacement', slug: 'biopharma-integration/legacy-serial-rs232-pi-ufl' },
          ],
        },
        {
          label: 'GAMP 5 & CSA Validation Binder',
          items: [
            { label: 'Qualification Suite & Binder Overview', slug: 'gxp-validation/overview' },
            { label: '01 — Validation Master Plan (VMP)', slug: 'gxp-validation/01-vmp' },
            { label: '02 — User Requirements Specification (URS)', slug: 'gxp-validation/02-urs' },
            { label: '03 — Functional & Design Spec (FDS)', slug: 'gxp-validation/03-fds' },
            { label: '04 — CSA Functional Risk Assessment (FRA)', slug: 'gxp-validation/04-fra' },
            { label: '05 — SOUP / OSS Vendor Dossier', slug: 'gxp-validation/05-soup-dossier' },
            { label: '06 — Executed IQ/OQ Evidence Report', slug: 'gxp-validation/06-iq-oq-evidence' },
            { label: '07 — Requirements Traceability Matrix (RTM)', slug: 'gxp-validation/07-rtm' },
            { label: '08 — Validation Summary Report (VSR)', slug: 'gxp-validation/08-vsr' },
          ],
        },
      ],
    }),
  ],
});
