# One pending proposal per card

An update's proposal filename must name its existing target card. The curator
normalizes model-generated aliases before writing proposals, and both the app
gate and command-line approval refuse legacy aliases that name another target.

Within one curator pass, further evidence for the same target is merged into
the current unapproved draft. The source references and hashes are retained in
the proposal metadata and the source judgments remain in the ledger. Conflicting
source claims remain for owner review; input order does not establish authority.
Combined drafts always wait for the owner, even if a normal update gear exists.
An earlier screening or taste flag cannot be cleared by a later clean source.

A draft already visible in the pending or audit queue is left untouched. Further
source material for its target is deferred without recording a consumed content
hash, and the watermark stays below it. It becomes eligible after the owner
decides the pending item. Legacy alias metadata also reserves the target.

Failed merges preserve the earlier draft and keep the failed input retryable.
Publication refuses to replace a proposal that appeared during the model call.
This prevents a review decision from racing with a silent proposal rewrite.

Existing duplicate queues need a separate recovery step: retain all originals,
prepare one consolidated draft on owner-controlled inference, inspect unresolved
source conflicts, then replace the group with one canonical proposal. This is
queue maintenance only; it is not an approval or promotion into knowledge.
