import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(siteRoot, '..');

const biopharmaFiles = [
  {
    src: 'docs/BIOPHARMA_INSTRUMENT_INTEGRATION_CATALOG.md',
    dest: 'src/content/docs/biopharma-integration/catalog.md',
    slug: '/biopharma-integration/catalog/',
    fileName: 'BIOPHARMA_INSTRUMENT_INTEGRATION_CATALOG.md',
    description:
      'Master catalog and signal archetypes for connecting 20+ upstream, downstream, PAT, fill-finish, and GMP utility instruments to OpenHistorian.',
  },
  {
    src: 'docs/XCELLEREX_X_PLATFORM_INTEGRATION.md',
    dest: 'src/content/docs/biopharma-integration/xcellerex-x-platform.md',
    slug: '/biopharma-integration/xcellerex-x-platform/',
    fileName: 'XCELLEREX_X_PLATFORM_INTEGRATION.md',
    description:
      'Integration guide for Cytiva Xcellerex X-Platform single-use bioreactors (50 L – 2000 L) and Figurate automation (Emerson DeltaV & Rockwell PlantPAx).',
  },
  {
    src: 'docs/USP_BIOREACTORS_SARTORIUS_THERMO_EPPENDORF.md',
    dest: 'src/content/docs/biopharma-integration/usp-bioreactors.md',
    slug: '/biopharma-integration/usp-bioreactors/',
    fileName: 'USP_BIOREACTORS_SARTORIUS_THERMO_EPPENDORF.md',
    description:
      'Upstream bioreactor integration for Sartorius Biostat STR & Ambr 15/250 (BioPAT MFCS), Thermo Fisher HyPerforma S.U.B. (TruBio DV), and Eppendorf BioFlo / DASGIP.',
  },
  {
    src: 'docs/PAT_CELL_ANALYZERS_AND_SPECTROSCOPY.md',
    dest: 'src/content/docs/biopharma-integration/pat-analyzers-spectroscopy.md',
    slug: '/biopharma-integration/pat-analyzers-spectroscopy/',
    fileName: 'PAT_CELL_ANALYZERS_AND_SPECTROSCOPY.md',
    description:
      'At-line PAT cell analyzers and in-line spectroscopy: Nova BioProfile FLEX2, Beckman Coulter Vi-CELL BLU, Roche Cedex Bio HT, Raman Rxn2/Rxn4, and Hamilton Arc sensors.',
  },
  {
    src: 'docs/DSP_CHROMATOGRAPHY_TFF_FILTRATION.md',
    dest: 'src/content/docs/biopharma-integration/dsp-chromatography-tff.md',
    slug: '/biopharma-integration/dsp-chromatography-tff/',
    fileName: 'DSP_CHROMATOGRAPHY_TFF_FILTRATION.md',
    description:
      'Downstream purification chromatography and TFF filtration skids: Cytiva ÄKTA (UNICORN 7), Sartorius Sartoflow / Resolute, and MilliporeSigma Mobius / Cogent.',
  },
  {
    src: 'docs/ASEPTIC_FILL_FINISH_LYO_AND_GMP_UTILITIES.md',
    dest: 'src/content/docs/biopharma-integration/aseptic-fill-finish-lyo-utilities.md',
    slug: '/biopharma-integration/aseptic-fill-finish-lyo-utilities/',
    fileName: 'ASEPTIC_FILL_FINISH_LYO_AND_GMP_UTILITIES.md',
    description:
      'GMP lyophilizers, SKAN isolators, aseptic filling lines, LasAir III / Airnet II particle counters, BACnet/IP EMS, and Veolia Sievers M9 TOC / WFI utilities.',
  },
  {
    src: 'docs/LEGACY_PROTOCOLS_BACNET_OPCDA_MODBUS_S7.md',
    dest: 'src/content/docs/biopharma-integration/legacy-protocols.md',
    slug: '/biopharma-integration/legacy-protocols/',
    fileName: 'LEGACY_PROTOCOLS_BACNET_OPCDA_MODBUS_S7.md',
    description:
      'Legacy fieldbus and PLC protocol integration: BACnet/IP & MS/TP BBMD routing, Windows COM OPC DA 2.05a zero-DCOM bridge, Modbus RTU/TCP, Siemens S7comm, and 4-20 mA HART.',
  },
  {
    src: 'docs/LEGACY_SERIAL_RS232_AND_PI_UFL_REPLACEMENT.md',
    dest: 'src/content/docs/biopharma-integration/legacy-serial-rs232-pi-ufl.md',
    slug: '/biopharma-integration/legacy-serial-rs232-pi-ufl/',
    fileName: 'LEGACY_SERIAL_RS232_AND_PI_UFL_REPLACEMENT.md',
    description:
      'RS-232 / Moxa NPort serial streaming (Mettler Toledo / Sartorius MT-SICS balances, osmometers) and ALCOA+ SHA-256 watchfolder ingestion replacing OSIsoft PI UFL.',
  },
  {
    src: 'docs/HARDWARE_SIZING_AND_CAPACITY_PLANNING.md',
    dest: 'src/content/docs/architecture/hardware-sizing.md',
    slug: '/architecture/hardware-sizing/',
    fileName: 'HARDWARE_SIZING_AND_CAPACITY_PLANNING.md',
    description:
      'Hardware sizing, compression math, 10k–25k tag clinical/pilot GMP reference Bill of Materials (BOM), 10-year NVMe + 15-year S3 WORM tiering, and Level 2.5 Industrial Edge IPC specs.',
  },
];

const validationFiles = [
  {
    src: 'gxp-validation-package/dist_binder/01_Validation_Master_Plan_VMP.md',
    dest: 'src/content/docs/gxp-validation/01-vmp.md',
    description: 'Document 01 — Validation Master Plan (VMP-OPENHISTORIAN-2026-001) governing CSV/CSA qualification.',
  },
  {
    src: 'gxp-validation-package/dist_binder/02_User_Requirements_Specification_URS.md',
    dest: 'src/content/docs/gxp-validation/02-urs.md',
    description: 'Document 02 — User Requirements Specification (URS-001 through URS-015) for OpenHistorian GxP.',
  },
  {
    src: 'gxp-validation-package/dist_binder/03_Functional_And_Design_Specification_FDS.md',
    dest: 'src/content/docs/gxp-validation/03-fds.md',
    description: 'Document 03 — Functional and Design Specification (FDS) across the 4-Pillar Historian Architecture.',
  },
  {
    src: 'gxp-validation-package/dist_binder/04_CSA_Functional_Risk_Assessment_FRA.md',
    dest: 'src/content/docs/gxp-validation/04-fra.md',
    description: 'Document 04 — FDA Computer Software Assurance (CSA) Functional Risk Assessment (FRA).',
  },
  {
    src: 'gxp-validation-package/dist_binder/05_SOUP_OSS_Vendor_Qualification_Dossier.md',
    dest: 'src/content/docs/gxp-validation/05-soup-dossier.md',
    description: 'Document 05 — SOUP / Open-Source Software Vendor Qualification Dossier & Container SHA-256 Digests.',
  },
  {
    src: 'gxp-validation-package/dist_binder/06_Executed_IQ_OQ_Protocol_And_Evidence_Report.md',
    dest: 'src/content/docs/gxp-validation/06-iq-oq-evidence.md',
    description: 'Document 06 — Executed IQ/OQ Protocol & Cryptographic Evidence Report (15 Automated Tests).',
  },
  {
    src: 'gxp-validation-package/dist_binder/07_Requirements_Traceability_Matrix_RTM.md',
    dest: 'src/content/docs/gxp-validation/07-rtm.md',
    description: 'Document 07 — Bidirectional Requirements Traceability Matrix (RTM) mapping URS to FRS and IQ/OQ tests.',
  },
  {
    src: 'gxp-validation-package/dist_binder/08_Validation_Summary_Report_VSR.md',
    dest: 'src/content/docs/gxp-validation/08-vsr.md',
    description: 'Document 08 — Validation Summary Report (VSR) and QA Release Disposition for Production GMP Use.',
  },
];

function transformMarkdown(raw, defaultDescription) {
  const lines = raw.split(/\r?\n/);
  let title = 'OpenHistorian Documentation';
  let bodyStartIndex = 0;

  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^#\s+(.+)$/);
    if (match) {
      title = match[1].trim();
      bodyStartIndex = i + 1;
      break;
    }
  }

  let body = lines.slice(bodyStartIndex).join('\n').trimStart();

  // Rewrite relative links to biopharma integration guides
  for (const item of biopharmaFiles) {
    const escapedFile = item.fileName.replace(/\./g, '\\.');
    // Match both (docs/FILENAME.md) and (FILENAME.md)
    const linkRegex = new RegExp(`\\]\\((?:docs\\/)?${escapedFile}(#[^)]+)?\\)`, 'g');
    body = body.replace(linkRegex, (_, hash) => `](${item.slug}${hash || ''})`);
  }

  const frontmatter = [
    '---',
    `title: ${JSON.stringify(title)}`,
    `description: ${JSON.stringify(defaultDescription)}`,
    '---',
    '',
  ].join('\n');

  return frontmatter + body + '\n';
}

function syncAll() {
  for (const item of [...biopharmaFiles, ...validationFiles]) {
    const srcPath = path.join(repoRoot, item.src);
    const destPath = path.join(siteRoot, item.dest);
    if (!fs.existsSync(srcPath)) {
      console.warn(`[sync-docs] Warning: missing source file ${srcPath}`);
      continue;
    }
    const raw = fs.readFileSync(srcPath, 'utf8');
    const output = transformMarkdown(raw, item.description);
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    fs.writeFileSync(destPath, output, 'utf8');
  }

  // Copy COMPLETE_GMP_VALIDATION_BINDER.html into public/binder/
  const htmlBinderSrc = path.join(
    repoRoot,
    'gxp-validation-package/dist_binder/COMPLETE_GMP_VALIDATION_BINDER.html'
  );
  const htmlBinderDest = path.join(
    siteRoot,
    'public/binder/COMPLETE_GMP_VALIDATION_BINDER.html'
  );
  if (fs.existsSync(htmlBinderSrc)) {
    fs.mkdirSync(path.dirname(htmlBinderDest), { recursive: true });
    fs.copyFileSync(htmlBinderSrc, htmlBinderDest);
  }

  console.log(
    `[sync-docs] Synced ${biopharmaFiles.length} Biopharma guides, ${validationFiles.length} GMP Validation Binder docs, and COMPLETE_GMP_VALIDATION_BINDER.html.`
  );
}

syncAll();
