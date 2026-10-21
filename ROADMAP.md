# Sovereign Roadmap

Status: planning document, owner: Sovereign Signal. Last updated 2026-10-19.
Current release: 0.7.1 (closed beta, MVO). This file is the canonical product
roadmap. GitHub Issues and Milestones are the public execution layer; when
they disagree with this file, this file wins until it is edited.

## Where Sovereign stands

Shipped and proven on clean VMs (macOS 13.6 and 27.0.1): install, first run,
archive creation, Claude Code connector, capture, curator drafting (local hub
inference or one hosted provider per archive: Anthropic, OpenAI, Gemini,
Grok, Muse), approval, and a fresh AI session reading the result. Trust
gears ship: ask-first default, fade eligibility after ten clean routine
decisions, a per-pass cap, landed review, revoke anytime.

## The field (researched 2026-10-19)

Four camps:

1. **Lab memory.** ChatGPT consolidates memory in the background. Claude
   Managed Agents memory is file-based and exportable, and Anthropic warns
   untrusted input can poison memory that later sessions trust. Portability
   is one-way: import tools pull memories out of ChatGPT; export stays lossy.
2. **Developer memory APIs.** Mem0, Zep, Cognee, Letta, Supermemory
   (roughly 31k GitHub stars, plugins for Claude Code and Cursor).
   Auto-extract into vectors or graphs, benchmark recall, no approval gate.
   Infrastructure for agent builders, not tools for a person.
3. **Session capture.** claude-mem (roughly 100k stars) auto-captures
   Claude Code sessions and injects compressed context later; it recently
   failed a public secret-redaction test, storing planted keys verbatim.
   Beacon (Asymptote Labs, $5.5M seed) captures session history across 20+
   harnesses for enterprise review.
4. **Markdown knowledge bases.** Basic Memory (MCP-native, 21 tools,
   $15/mo cloud sync), OpenKnowledge, Instinct (reverse-engineered as git
   plus markdown plus grep). Agents write directly to the knowledge base.

Read: files-as-truth is now consensus and stops being a differentiator.
Nobody else gates writes behind earned trust. That is Sovereign's open lane.

## Positioning

**Memory you can audit.** Every trusted fact has a source, an approval, and
a history. Autonomy is earned in gears and revocable in one click. Local-only
archives structurally refuse hosted models. Secrets live in the Keychain,
never in files. The archive is plain markdown in git, readable with no
Sovereign software at all.

## Capability backlog (the possibilities)

Grouped by theme. Effort is rough: S days, M one to two weeks, L a month+.

### Capture without poison
- **Gated session ingestion** (M): watch Claude Code and Codex transcripts,
  distill candidate captures into the owning tool's raw lane only. Curator
  still gates promotion. Matches claude-mem's magic, keeps the trust story.
- **Capture from anywhere** (S): share-sheet and drag-drop into the app,
  landing in raw inbox.
- **Voice and screenshot capture** (M): same lane discipline, new inputs.

### Readable everywhere
- **Read-only MCP server** (M): any MCP client reads curated cards through
  the same posture rules as `sov load`. Writes stay lane-gated; no MCP
  write path into the trusted layer, ever.
- **Second flagship connector** (S/M): Codex to Claude Code grade
  (diagnostics, first-run proof, best-effort watermark removed).
- **Additional connectors** (S each): Cursor hardening, Gemini CLI,
  OpenCode, as demand appears.

### Into the archive (cold start and migration)
- **Importers** (S each): ChatGPT memory extraction prompt flow, Claude and
  Codex memory folders, claude-mem database export, Supermemory and Mem0
  exports, loose markdown folders. Everything lands untrusted in an import
  lane; the curator promotes. No silent bulk-trust option.
- **Guided first week** (S): the app suggests three starter captures and
  shows the loop closing, using the user's own data.

### Trust machinery
- **Temporal validity** (M): cards gain valid-from, supersedes, and
  review-by dates. The curator proposes conflicts and asks "still true?"
  on stale facts instead of letting them rot.
- **Dedupe and merge proposals** (S): curator spots near-duplicate cards
  and drafts merges for approval.
- **Wrong-memory benchmark** (S to publish v0): a small repeatable test
  measuring how often a memory system stores false or stale facts.
  Publish methodology and results against auto-write baselines.
- **Audit view** (S): one screen answering "what does my archive believe,
  who said it, who approved it, when."

### Distribution and growth
- **Auto-update** (M): signed updates delivered in-app (Sparkle or the
  existing app-update path productized). Required before the beta widens.
- **Demo assets** (S): 60-second install-to-remembered video; screenshots
  for README and release pages.
- **Marketplace presence** (S): connector listings where each harness
  keeps them; awesome-list submissions.
- **API key walkthrough** (S): non-technical in-app guide for creating a
  provider key, with per-provider steps.

### Beyond one person (later)
- **Two-Mac wizard** (L): productize the hub-and-mirror setup that today
  only the maintainer's fleet runs.
- **Team archives** (L): shared curated layer, per-person raw lanes,
  per-lane posture. Same law, bigger surface.
- **Windows** (L): only after Mac retention is proven.

## Milestone candidates

Pick one per release. Each is sized to close in a single version.

**v0.8.0 "Reach"** (recommended next): read-only MCP server, importers
(ChatGPT prompt flow plus Claude/Codex memory folders first), auto-update,
positioning copy pass ("memory you can audit"), API key walkthrough.
Why: attacks distribution and cold start, the two risks every review names,
without touching the trust core.

**v0.9.0 "Capture"**: gated session ingestion for Claude Code, then Codex;
temporal validity fields and staleness prompts; audit view.
Why: matches the category's automatic magic while keeping the gate.

**v1.0 "Public"**: second flagship connector hardened, demo assets,
wrong-memory benchmark published, guided first week, pricing decision.
Exit closed beta when three to five outside users have completed the loop
unassisted and returned on day two.

Decision rule for sequencing anything else: does it (a) get Sovereign into
more hands, (b) deepen the audit moat, or (c) reduce review burden? Work
that does none of the three waits, however interesting it is.

## Tracking

- This file: canonical roadmap, edited in the template repo, published to
  GitHub by the normal kit flow.
- GitHub Issues (SovereignSignal/sovereign): public execution and beta
  feedback. Labels: `connector`, `trust`, `ux`, `distribution`, `bug`.
- GitHub Milestones: one per version above; an issue belongs to exactly
  one milestone.
- Notion stays for operations and health reporting, not product planning.
  One source of truth beats two half-synced ones.

## Contributor notes

Read this file, `README.md`, `CHANGELOG.md`, and `SUPPORT.md` first.

- Run the full suite before claiming anything (see
  `docs/release-checks.md`): the template suite, the console backend
  suite, and every `apps/console/tests/*.cjs` suite.
- Releases go through `apps/console/notarize.sh`. Zip with
  `ditto --sequesterRsrc`; a plain zip breaks the seal on macOS 13.
  Verify: SHA-256, `codesign --verify --deep --strict`, `spctl`,
  `xcrun stapler validate`, zero `._*` files inside the bundle.
- Validate release candidates on clean macOS 13 and current macOS VMs.
  Never enter personal accounts in a test VM.
- The first-run archive default stays in the home folder, never
  Documents: macOS privacy rules deny background jobs there.
- Curator rules: one provider per archive, pinned HTTPS hosts, keys only
  in the Keychain, local-only archives refuse hosted providers, and a
  provider switch resets trust to ask-first. The Muse provider still
  needs `CURATOR_ENDPOINT`; no canonical public host is established.
- Work is tracked as GitHub issues under the milestones above, built in
  the order listed, each verified before the next starts.
