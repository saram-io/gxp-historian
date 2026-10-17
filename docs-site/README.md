# OpenHistorian GxP Documentation Site (Astro Starlight + Cloudflare Workers)

This directory contains the standalone **Astro Starlight** documentation portal for the **OpenHistorian GxP Industrial Historian**, configured for deployment on **Cloudflare Workers Static Assets** (not Cloudflare Pages) via [`wrangler.jsonc`](wrangler.jsonc).

## Features

- **Cloudflare Workers Static Assets (`wrangler.jsonc`):**
  - Serves `dist/` directly from Cloudflare Workers edge static assets (`assets.directory = "./dist"`, `not_found_handling = "404-page"`, `html_handling = "auto-trailing-slash"`).
- **Automatic Source Synchronization (`scripts/sync-docs.mjs`):**
  - Automatically syncs all 8 Biopharma & Legacy Equipment Integration guides from [`../docs/`](../docs/) into `src/content/docs/biopharma-integration/` and rewrites internal Markdown links to Starlight routes.
  - Automatically syncs all 8 Commercial GMP Validation Binder documents from [`../gxp-validation-package/dist_binder/`](../gxp-validation-package/dist_binder/) into `src/content/docs/gxp-validation/` and copies `COMPLETE_GMP_VALIDATION_BINDER.html` to `public/binder/COMPLETE_GMP_VALIDATION_BINDER.html`.
- **Full-Text Search:** Built-in static search powered by **Pagefind**.
- **Mermaid Diagrams & KaTeX Math:** Automatic client-side theme-aware Mermaid rendering (`dark` / `neutral`) and build-time KaTeX math rendering (`remark-math` + `rehype-katex`).

## Commands

Run all commands from the `docs-site/` directory:

| Command | Action |
| :--- | :--- |
| `pnpm install` | Install dependencies (including `wrangler`) |
| `pnpm run sync` | Sync `../docs/*.md` and `../gxp-validation-package/dist_binder/*` into the Starlight content collection |
| `pnpm run dev` | Sync docs and start the local Astro dev server at `http://localhost:4321` |
| `pnpm run build` | Sync docs, build the production static site to `./dist/`, and generate the Pagefind search index |
| `pnpm run cf:dev` | Build the site and preview locally inside the Cloudflare Workers `workerd` runtime (`wrangler dev`) |
| `pnpm run deploy` | Sync docs, build `./dist/`, and deploy to **Cloudflare Workers** (`wrangler deploy`) |

## Deploying to Cloudflare Workers

### Option A: Deploy via Wrangler CLI

```bash
cd docs-site
pnpm exec wrangler login   # First-time authentication only
pnpm run deploy
```

### Option B: Cloudflare Workers Builds (Git CI/CD)

1. In the Cloudflare Dashboard, go to **Compute (Workers) -> Workers & Pages -> Create application -> Workers** and import this repository.
2. Set the **Workers Builds** configuration:
   - **Root directory:** `docs-site`
   - **Build command:** `pnpm run build`
   - **Deploy command:** `npx wrangler deploy`
