# Implementation notes migrated from README

Historical implementation notes preserved during the README reorganization on 2026-11-10. These entries describe different development stages and are not a current acceptance checklist. See [Progress](../../../Progress.md) and [updates](../../updates/README.md) for tracked status.


Transfer management now shares `manage_agent_transfer(operation, request)`, `AC_agent_transfer`,
`ac_agent_transfer`, authenticated `POST /agent/transfer`, and Script Builder metadata. The CLI uses
`agent-task transfer --operation review_export --request request.json`. Review returns an approval
token; creation requires that token, the original request key and an explicit note. Export/import
management and portable evidence management support registered hosts, with source-local authority checks.
The Transfers page exposes these operations through explicit Actions, editable JSON and four locales.
Review never sends approval; preparing approval preserves the original host, review token and request
key with an empty note. Changed selections and closed views reject late replies; accepted imports
remain service-owned. Routed evidence consent is persisted before forwarding; exact retries after lost
replies or a coordinator
restart reuse the same grant. Passive diagnostics describe only the local contract, not a live grant
or verified remote/native capability. Read-only completion grants revalidate their retained private
consent at creation and resolution, without reviving original input authority.
Implementation verification is recorded in docs/updates/README.md; remaining delivery and acceptance
are tracked in Progress.md.
Editable request templates are provided in examples/agent_transfer_export_review.json,
agent_transfer_import_review.json and agent_transfer_evidence_review.json, with separate create templates.

Experimental source-host skill operations may select a portable grant with the existing
`handoff_id` and explicit completion/execution task. The source rechecks its actual consent,
recipient and private proof in the skill transaction, including after candidate/publication writes.
Original actions, the candidate's own validation trial and explicit version approval remain required.
New skill trials receive a fresh service-generated request key; legacy unkeyed trials are not backfilled.
Selected evidence retains the source host's actual actions, trials and versions under current authority.
Remaining cross-host acceptance and production delivery are tracked in Progress.md.
Runtime ownership is retained throughout the selected-evidence skill operation and released afterward.

Destination import remains experimental. An explicitly started service accepts
`review_import` / `create_import` / `get_import` / `run_import` / `cancel_import` / `list_imports`
through its runtime transfer controller and authenticated `/agent/transfer` route. A coordinator can
route these finite operations through its own opaque consent token. The destination resolves the
source using its own registry and account; coordinator principals, origins and source credentials
are not forwarded. Approval commits before dispatch, and exact lost-ACK retries retain one import.
Startup resumes accepted never-claimed work and fences unsettled claims for review. Explicit
`run_import` rechecks the original recipient, profile, live origins and source grant under a new
queue generation. Verified private chunks can be reused; an owned complete generation is inspected
and hashed without downloading or publishing again. Additional attempt origins remain restrictive.
An explicitly queued, never-claimed inspection survives another restart; current bytes, profile
and retained attempt origins are rechecked before accepting its result.
Before accepting a published import receipt, the destination rechecks the complete file list
and content digests after its final source response. Changed, missing or extra files leave
the import in requires_review, preserving user edits and the original publication for review.
Changed ownership, bytes or authority cannot confirm publication. Cancellation fences the producer;
unaccepted publication remains requires_review, and confirmed published files remain user output.
Cancelled or expired private chunk accounts are cleaned only after their exact producer retires;
failed cleanup retains capacity until a confirmed retry. Receipts keep their original fixed expiry.
Staging directories and preallocated files are journaled by filesystem identity before bytes
are copied. Expiry retries their exact cleanup after the producer retires, including after restart;
replaced or unrecognized objects retain capacity for review and are never recursively deleted.
Source maintenance retires expired or revoked private export accounts, including after restart
or issuer removal. Failed cleanup retains its reservation. Runtime ownership remains held until
source or destination cleanup finishes; idle maintenance takes no runtime writer.
Create/run replies describe the committed receipt assembled before waking new delivery work;
a later get_import reads current progress. This avoids reading that receipt behind the new writer.
A later maintenance sweep prunes already-cleaned, revoked and expired source metadata to reclaim
its record quota, preserving consent/revocation tombstones and other record families. Cold runtime
maintenance discovers pending source records through a read-only probe; unused controllers stay lazy.
Final runtime owner release is serialized with lazy controller construction and rechecks any late
controller. Active construction or cleanup keeps ownership held for a later close attempt.
Redirected private cache paths are refused before storage opens; failed cleanup retains capacity.
Subsequent maintenance also prunes expired destination import/delivery metadata and its terminal queue
rows after confirmed private cleanup. Active, rebound or unknown queue work prevents pruning; original
consent/revocation tombstones and published user files remain. Cold maintenance performs this retirement
without a listener or producer. Cleanup scans held accounts independently of retained unexpired metadata.
Portable evidence retention and shared surfaces are implemented; remaining fault acceptance and delivery
are tracked in Progress.md.
Experimental source evidence now supports review_evidence/create_evidence/get_evidence/revoke_evidence/
list_evidence through the owning runtime and authenticated local transfer route. Separate durable
consent reuses real recovery/completion proof, current accounts and original local DAG admission.
The registered peer evidence operation matches the actual accepted key/spec and optional DAG node;
it returns only IDs, hashes and finite verification, with evidence_only=true/input_authorized=false.
Review summaries omit the node request_digest; live resolution supplies it for the exact reviewed
accepted key. Source grants do not grant ordinary task reads or input. Selected source-owned skill evidence, routed management and shared public surfaces are implemented.
Remaining fault acceptance and production delivery are tracked in Progress.md.
Experimental coordinator continuation accepts a separately reviewed live remote recovery grant for
the exact original source/key/spec/graph/node and pinned host. Approval and start persist provisional
states, resolve again outside the coordinator writer, then recheck immutable local consent and claims
before activation. Stop cancels pending states; an interrupted provisional approval requires the same
explicit request. Runtime ownership remains held during confirmation without serializing peer readers.
Dependency checks repeat around claim/record and final remote adoption acceptance. A failed grant
fences scheduling and requests bounded pause only for independently matched accepted dependents;
unknown or lost acknowledgements retain claims and require review. Completed effects and unrelated
tasks remain intact. This does not certify native input retirement or complete the full fault matrix.
Legacy delivery-schema upgrade preserves the accepted origin and fixed expiry. Additional origins
remain cumulative across resumes. Stopping an attached REST observer leaves the same service-owned
delivery and runtime owner intact; reattachment reads its result without redispatch.
Actual two-host and separate-process three-host tests independently verify bytes and account scope.
Further restart/cancellation faults, further staging faults, full retention, portable evidence,
client/GUI surfaces and complete-stage verification remain in Progress.md. A receipt grants no
task-input authority or task-completion evidence.

Registered source management now routes review/create/get/list/revoke through a coordinator-owned
opaque review. Consent binds the actual local caller, current host fingerprint, peer review, manifest
digest and original key. Approved intent commits before forwarding; lost replies and coordinator
restart retry the same source grant. Changed actor/host/token/note/key or a different reply manifest
is refused. Pending reviews and retained route records each cap at128; expiry removes only local
route metadata while preserving consent fences. Runtime closure discards unapproved cached reviews;
durable approvals remain recoverable. The source uses its own account, and local principal/
origin headers stay local. Destination lifecycle, source-owned skill evidence and shared surfaces are implemented; remaining
acceptance and production delivery are tracked in Progress.md.

Existing remote DAG calls now read the actual persisted host book when pinning a host and before
and after each retained connection call. Another process replacing/removing the endpoint or token,
damaged configuration or revoked captured local authority invalidates the operation. Reads neither
initialize nor quarantine the book; local service delegation and the closed remote routes stay compatible.

Cross-host outcome handoff remains experimental and incomplete. The runtime-owned local source core reviews
selected completed file outcomes and commits consent-bound immutable blobs with actual issuer and
recipient checks. Authenticated source management and peer-read HTTP routes now expose those reviewed
manifests/chunks. Peer reads use the receiving server's ordinary bearer/RBAC gate and rate limits;
local principal/origin headers are refused before foreign principal/store lookup. The local service
client preserves real owner delegation for management only. Transfer requests are capped at1MiB before
server reads; the bounded client refuses oversized request dispatch and success/error reply decoding
without changing ordinary HTTP limits. Destination publication, live evidence adoption and shared public surfaces are implemented.
Remaining lifecycle acceptance and production delivery are tracked in Progress.md. A transfer receipt grants no task-input authority.

Source export excludes actual runtime/transfer databases and sidecars, current source-owner and
issuer user stores, service-owned connection files and owned evidence directories before opening
selected bytes. The service registers its actual private files; ordinary same-named outputs remain
valid. Manifest checks apply to selected outputs. Peer reads and exact retries recheck current path
authority without rehashing historical user output, and path checks retain the operation deadline.
DAG artifacts follow at most sixteen real recovery links to the original submitted task, binding
actual accepted requests and local DAG admission. The admitting actor is reauthorized, and its actual
user store is private even when distinct from the source owner. Recovery children need no fabricated
submission row; genuine standalone sources need no DAG row. A private lineage digest is rechecked at
review, creation, exact retry and peer reads. Actual private recovery ownership/reviewer bindings
also join the digest and their user stores stay private. Source operations honor cooperative
cancellation around byte access and grant writes; a committed intent remains exactly recoverable
after a cancelled reply. Artifact expiry is its completed source updated+30days; retries/restarts do
not refresh it or substitute an older ancestor deadline. Real local renewed readers use their current
private completion authority while old input remains revoked. Cross-host commit races, automatic cleanup and destination lifecycle/evidence remain open.

Runtime owns a TransferPeer through its actual batch host adapter. Registered transfer reads pin the
persisted endpoint/credential and reread the book before and after HTTP, with current local caller
checks. Source authentication uses the receiving host's own credential; local principal/origin headers
are absent. Actual configured credential-book paths stay private without initializing or reloading the
console. Closed manifests and canonical base64 chunks require matching export IDs/hashes, at most256KiB
per chunk and a fixed deadline. The1MiB transfer wire cap also applies behind URL path prefixes;
ordinary HTTP keeps its existing limit. Invalid numeric budgets, including oversized integers, fail
with typed errors before dispatch. Remaining cross-host fault acceptance and production delivery are tracked in Progress.md.

Idle background workers check empty work queues without reserving a database writer, reducing
contention with task status and completion transactions. A nonempty hint still requires the original
transaction to recheck and claim the work. Claim generations, stale-work recovery and retry limits
remain enforced; task and transport deadlines are unchanged.

Lease maintenance binds expiry/revocation stops to the actual input owner and generation in the
same stop transaction. A delayed watcher cannot rewrite retired recovery evidence or cancel a newer
lease. The accepted final state and cancellation token are set before the stop becomes visible;
current revocation and the original deadlines remain enforced.

Stopped browser tasks with confirmed effects can now use the existing completion review and
skill workflow with their actual original WebRunner context. The owned worker permanently freezes
SDK input/network before its input journal and lease release; the runtime retains at most 16
contexts for at most 300 absolute seconds, starting before detachment. Preview/new admission probe that exact effect task's live SDK view.
The verifier borrows it for fresh bounded DOM/value reads, without configure, input ACKs, transfers
or another browser/helper. Retirement, capability probes and cleanup deny nested tools and native input.
Same-profile tasks keep separate contexts. A saved context ID grants nothing.
Private completion authorization can explicitly renew the verification scope within the original
ceiling while the original input specification stays immutable. Expired input origins grant no reads;
bounded private custody alone is not authority. Removed owners, disabled targets, changed sources,
expiry and failed reads invalidate contexts. Confirmed process reaping is required to free ownership;
failed cleanup stays tracked. Restart cannot restore a page. Network-retired DOM is not new server data.
Existing Python/AC/MCP/REST/CLI/Builder and GUI Actions share the same review requests. Skill recording
keeps original actions; publication requires its own actual validation trial and selected completion.
See `examples/agent_browser_retained_completion.py`. Cold browser-prefix reconstruction, remote
readers, production deployment and deferred native/browser/device/24-hour acceptance remain open.

Stopped tasks with confirmed effects can use `manage_agent_recovery("preview_completion", {"task_id": id})`
to review a separate verification task. Call `create_completion` with the exact task_id/snapshot and a
review note, then finish the returned task. A private atomic binding selects a permanently read-only
helper; source actions never replay and fresh independent criteria plus input retirement prove success.
Skill plans must be fully confirmed; dynamic tasks must have no dormant finite plan or unknown effects.
Observe may precede finish: identical helper configuration reruns readiness without replacing its authority.
Source/reviewer authority stays live, including after helper cleanup and across explicit retries/restarts.
Existing API/AC/MCP/REST/CLI/Builder and GUI Actions share the workflow. Remote readers and
production deployment remain in Progress.md; desktop capability still requires separate native evidence.

Managed-only DAGs can register a durable whole-graph batch with
`manage_agent_dag("register", {"definition": graph, "max_parallel": 4})`, then explicitly call
`run_dag(graph, batch_id=batch["batch_id"])`. Registration performs no target operation. The stored
graph pins topology, node contracts, host configuration and parallelism; destination keys/spec tags
bind each node to that batch. A claim commits before possible delivery, and exact destination spec /
completion / input-retirement evidence gates dependants. Repeated begin is refused after success,
interruption or a lost submit reply. `get/list/inspect` retain coordination identity across restart.
Use API/AC/MCP/REST/CLI/Builder or the DAG Actions batch register/read controls and optional batch ID.
For a stopped batch, `review_continuation` returns a read-only whole-graph snapshot and explicit node
decisions. Pass its reviewed `snapshot`, `decisions` and a nonempty `note` through
`run_dag(graph, batch_id=id, recovery=request)` to approve and consume one continuation attempt.
Only independently completed originals or genuine completed recovery successors can be adopted;
dispatch requires a never-claimed pending node with no accepted destination request. Local authority
can be renewed within equal/narrower roots. Unknown claims are never replayed. DAG Actions exposes
fencing, review and explicit continuation; fencing stops new dispatch and leaves accepted tasks under
their own lifecycle. To delegate coordination to an explicitly started service, call
`manage_agent_dag("run_background", {"batch_id": id, "definition": graph, "max_parallel": 4})`.
Add `approval_id` for an explicitly approved continuation. DAG Actions exposes both background actions;
closing the view leaves accepted service work alive. `get.background` reports bounded queue state.
Restart fences old attempts and requires review, without replaying queued or unknown deliveries.
Both original owner and submitting actor remain live checks; local tasks use their owning runtime.
The existing `prune_agent_tasks()` and hourly maintenance also collect expired unused registrations
and settled successful batches (30 days by default). Unresolved batches retain task/recovery evidence
and admission gates. Results add `deleted_batches` and `deleted_dag_deliveries`; foreign queues and
user outputs remain untouched. Remote evidence retention still requires an explicit handoff contract.
Caller-coordinated bound runs pin the local service path, endpoint, credential fingerprint and generation.
All local node calls reuse that client; replaced metadata stops future calls and requires explicit review.
Server-side batch evidence reads its owning runtime directly. No bearer credential is cached by binding.
Ordinary non-batch clients retain adaptive discovery; bound batches require generation-bearing metadata.
Local batch nodes now use the source service's closed `local_task` transport after a durable claim.
The exact spec/key is admitted as the original owner, with the real caller recorded atomically. Runtime
checks refresh both identities and the live attempt before input; losing admin authority over another
owner's work also blocks execution. Existing requests without this trusted admission are never backfilled.
Task metadata exposes bounded `local_dag_admission` audit data; accepted input retains its cleanup contract.
For a reviewed recovery successor that must remain readable to its original owner, pass
`owner_policy="source_owner"` to recovery preview/review_authorization, then carry its
`ownership.review` as `ownership_review` into explicit create/create_authorized. The child retains the
source owner and records the real reviewer atomically; both identities remain live input checks.
The recovery GUI offers this owner selection. Omitted policy keeps caller ownership and ordinary read
isolation. DAGs can adopt an independently completed source-owned child through normal recovery evidence.
Existing caller-owned children are not automatically transferred or backfilled into this policy.
See [the continuation protocol](../../source/Eng/doc/ai_agents/agent_dag_batches_doc.rst).

Triggers can explicitly use `manage_agent_trigger("review_authorization", {"trigger_id":"..."})`,
then `create_authorized` with `trigger_id`, `snapshot`, `authorization_review`, reviewed `spec` and `note`.
The new registration preserves its full template/config/pending limit within original/live/current
authority, retires the old binding atomically and enables future notifications. Shared lineage history
keeps accepted keys and outstanding tasks across renewal, removal and restart; inherited queued events
are never redispatched. Schedule windows restart in the future and file checkpoints remain. API/AC/MCP/
REST/CLI/Builder and the GUI trigger selector share this explicit flow; ordinary enable cannot replace
expired authority. Review only prepares a request with a blank note.

Published skills can use `manage_agent_skill("review_authorization", {"candidate_id":"..."})`,
then explicit `create_authorized` with `candidate_id`, `snapshot`, `authorization_review`, reviewed
`spec` and `note`. Renewal preserves the whole plan/parameter schema and source root ceiling, retaining
live restrictions and intersecting current authority. It creates an audited draft in the same skill
lineage; fresh validation and explicit next-version publication are required. Old versions remain
unchanged. Identical approval deduplicates; stale versions/context fail. API/AC/MCP/REST/CLI/Builder and
the GUI Skills operation selector share this flow. Trigger renewal uses the separate flow above.

Stopped tasks with retired origin authority can explicitly use `review_authorization`, then
`create_authorized` with `task_id`, `snapshot`, reviewed `spec`, `note` and `authorization_review`.
The successor retains every live source restriction and intersects current authority with the original
root ceiling; roots may only stay equal or shrink. Other permissions, mode/model, budgets and completion
conditions stay fixed. Approval is audited atomically with the unique successor; the source and its
revoked witnesses stay unchanged. All recovery surfaces include these operations, with separate GUI
Actions for authorization review and creation. See the [recovery guide](../../source/Eng/doc/ai_agents/agent_recovery_doc.rst).
Task recovery does not clear input quarantine or restore application state; skills and triggers use their separate renewal flows above.

Stopped tasks can use `manage_agent_recovery("preview", {"task_id": "..."})` to review source
receipts and a source snapshot without touching an application. Finite skills expose remaining actions
and row outcomes. External-agent and local-model tasks provide `review_template` with a blank goal;
operators must explicitly supply a remaining-work goal, with no copied action list. Explicit `create` approval
supplies the snapshot, reviewed spec and note, creating one linked successor with fresh observations
and receipts. Repeated approval returns that task. Execution mode, model/endpoint, scope, budgets and
completion conditions stay fixed, and unknown effects require reconciliation. Old captures, indexes,
coordinates and completed history are not transplanted. Use `AC_agent_task_recovery`, MCP/REST,
`agent-task recovery preview|create request.json` or Agent tasks → Actions → Review remaining work /
replan / Create reviewed successor task. Delegated sources cannot resume; continue from the successor.
Login and window-state restoration is declared, never inferred: a successor (or any task) may list
`resume_conditions` — `screen`, `browser` or `file_*` clauses only, since receipts are history — and its
first action is admitted only on a fresh observation that passes all of them. A failed or unknown
condition puts the task in `waiting_user` instead of acting; once any action receipt exists the gate is spent.

Built-in Android/iOS managed profiles remain unavailable. Their internal remote-effect guard records
before/after acknowledgements against a physical-device identity and retains quarantine when a local
helper exits with an unconfirmed effect. Recovery requires a trusted device proof after writer retirement
and a later epoch invalidating old commands. No built-in SDK proof, device profile or native acceptance
is implied; remaining integration is in `Progress.md`.
The internal Android transport connects only to an explicit existing loopback ADB server, with no CLI,
daemon management, retry or legacy-shell fallback. Shell-v2 exit evidence has bounded framing/output;
it does not establish app completion, physical-device identity or input retirement.
Internal Android sessions now inspect an exact endpoint, validate physical serial/boot/default-display
focus and pin one boot atomically. Finite input proposals recheck identity and focus on the selected
command connection, with literal bounded text and fixed results. Proposals grant no input authority;
input-window, occlusion, lock/presence and owned-worker integration remain required.
Android checked proposals now bind current native input-window/queue and keyguard evidence. Pointer
checks cover entire half-open touch-region paths and foreign interception/overlays; hashes are rechecked
on the command connection. Old ANR/history cannot certify current state. Human presence and global-monitor
review still require trusted providers; built-in managed device execution remains unavailable.
Internal Android action protocol v2 distinguishes complete pre-input refusal from input failure,
post-input refusal and returned input. Missing/malformed phases or mismatched shell exits remain unknown;
even returned input does not certify remote input retirement or task completion. No retry is authorized.
The internal owned remote SDK worker now checks exact task/owner scope, refreshed authority and physical
takeover; parent monitoring starts before the trusted host factory. Calls require a durable begin ACK,
then matching device/epoch settlement before an end ACK. Missing proof keeps effects quarantined.
Trusted device-control providers, the WDA adapter and managed profile wiring remain required.
The command compiler reads the three native focus fields in one labeled extraction, accepting their
six possible orders while refusing missing/duplicate/empty fields. Pre/post identity and input-security
checks remain, and action deadlines are unchanged. Owned POSIX fixtures avoid extra Git Bash reader
processes without changing file bytes; bounded phase/timing diagnostics exclude commands and output.
Internal AndroidRemoteAdapter now connects checked sessions to this worker through explicit per-command
AndroidCommandLease grants. A fresh identity/routing/security observation is consumed per action; the SDK
recompiles the finite command before sending it once over ADB. Device fencing must suppress old writes
after physical takeover, cancellation or expiry. No default provider exists: standard ADB and killing
the local helper cannot supply that guarantee. Settlement additionally binds one random request ID and
boot to independent input/queue proof. An optional explicit host hierarchy_reader supplies bounded
app-only semantic elements and reviewed non-sensitive text; without it observations remain metadata-only.
XML cannot grant text access; editable/password values and protected descendants stay masked. Raw XML
and private freshness hashes are never published; random observation revisions change after actions and
source changes. Android element references require a current actionable semantic element. Fresh screen
readback can confirm a reviewed positive label; missing/partial/masked content cannot prove text absent.
No CLI/SDK startup or capture fallback is added. Real capture/control providers, protected field-value
verification, Unicode/IME and managed profile delivery remain open.

Managed screen completion now treats built-in desktop and WebRunner previews as partial text evidence.
File targets and desktop window bootstrap supply no semantic screen evidence. Known safe labels can
confirm presence or contradict absence; masked and explicitly hidden labels cannot. Combined conditions
remain unknown if any required evidence is missing, or fail on a known contradiction. Use explicit
browser completion reads for exact DOM/value checks. Custom targets without coverage flags keep legacy behavior.

`lookup_agent_task("key", reviewed_spec)` optionally compares the destination-normalized specification
with the immutable digest stored for the original owner's request. The response advertises
`spec_match_contract=1` and reports `spec_match=matches|differs|unverifiable|not_found` when a spec is supplied.
CLI lookup accepts `--spec reviewed.json`; AC/MCP/REST/Builder share the optional object. Inspection first
queries the key, then compares the reviewed node spec only when the destination advertises the exact
contract. Old destinations stay `unverified`; local origin witnesses are never sent to remote matching.
Changed request identity invalidates the earlier snapshot. Matched nodes also require the exact count,
kinds and passed status of independent criterion reports before confirming recorded completion.
`request_match` binds the node's task spec;
DAG topology/batch approval and continuation remain separate, with `resume_permitted=false`.

`inspect_agent_dag(definition, timeout_seconds=30)` looks up existing local/registered-host requests
without submitting, pausing or resuming tasks. Use `AC_agent_dag_inspect`, MCP `ac_agent_dag_inspect`,
REST action execution, CLI `agent-task inspect-dag reviewed.json`, Script Builder or DAG Actions.
At most 100 nodes and a 300-second maximum budget bound inspection. Remote lookup needs host-management
authority; local principal/store/origin metadata stays local. Results omit remote paths and raw errors.
`recorded_completion` describes the found task only. Node-spec matching is optional; `resume_permitted=false`
explicitly leaves graph/batch approval and continuation unapproved. A missing record
does not prove rejection. GUI inspection is read-only and discards results after graph edits.

Use `lookup_agent_task("original-key")` (`AC_agent_task_lookup`, MCP `ac_agent_task_lookup`,
`POST /agent/lookup`, CLI `agent-task lookup original-key`, or the task view's Actions menu) to inspect
a submission whose reply was lost. It reads only the original principal/store namespace and never
submits, resumes or acquires input. `found=false` is a current snapshot; a late request may still arrive.
GUI lookup results cannot replace a task/key selected while the request was pending. DAG inspection
shares this lookup; specification-bound recovery approval remains separate work. The query requires task access.

Existing `run_dag` / `AC_run_dag` / MCP `ac_run_dag`, REST action execution, CLI action files,
Script Builder and the DAG Actions menu accept nodes with a `task` payload instead of actions:

DAG types and functions are also exported from `je_auto_control.api` and `je_auto_control.api.core`.

```python
run_dag({"nodes": [{"id": "collect", "host": "reviewed-host", "task": {
    "spec": reviewed_spec, "idempotency_key": "batch-20261024-collect", "wait_seconds": 300}}]})
```

`reviewed_spec` must use skill or an explicitly configured local-model mode, with tools, destination
roots and completion criteria. The host must already expose an authenticated agent runtime with
background dispatch; this does not deploy listeners. Omit `host` for the explicit local service.
The destination validates scope and coordinates resource ownership. Nodes submit once, poll bounded
status and advance only with matching passed criteria, durable completion contract 1 and confirmed input
retirement. Keys are required and must stay stable when recovering the same reviewed batch; rerunning
does not resume paused tasks or replay effects. Stop, timeout or transport/authority failure requests
bounded pause when the task ID is known. A lost acknowledgement stays uncertain; failed nodes retain
the task ID/key and block dependants. The GUI displays retained task IDs. Remote credentials come from
the administrator's registered host; local principal/store paths and origin witnesses stay local.
Production multi-host setup and native/device acceptance remain separately tracked.

Managed HTTP pause/cancel/stop-all/shutdown requests have a separate per-IP reserve with the same
120-per-minute rate and 30-request burst as ordinary traffic, so polling cannot exhaust stop admission.
Authentication, live roles, task ownership, audit and bounded input retirement still apply. The shared
client also reserves transport capacity for DAG batch/node pauses; its control marker admits only closed
pause requests on `/agent/dag`. Other marked DAG operations fail before dispatch. Custom auth gates
retain their own admission contract. This does not guarantee priority over a saturated OS/network.

Managed task success is published after input cleanup is confirmed. If cleanup fails or remains busy,
the task requires review and keeps its input lease; a crash before confirmation remains recoverable.
Completion uses conditional state transitions so concurrent cancellation retains priority. Status and
the existing GUI/API task results expose `metadata.input_released` and durable `completion_contract=1`
for newly confirmed success (legacy records retain zero); final artifacts reflect the settled
state. This supplies local retirement evidence for subsequent DAG coordination.

DAG nodes retain the caller's authorization, cancellation and command ceilings on pool threads,
including custom runners. Each node refreshes store-backed users before execution; removed users fail
that node and dependent nodes are skipped. Individual operations check the refreshed role. Default
remote nodes require `manage_hosts` before opening the host address book or action files, because
registered host credentials may grant more access than local action permissions. Trusted local Python
and administrators retain remote dispatch. Managed task nodes add the closed lifecycle described above;
production multi-host deployment and native acceptance remain separate work.

Browser host profiles can select a reviewed installed Python environment through optional
`settings.helper_python` (an absolute local interpreter path). Explicit helpers run with `-I`, using
installed packages rather than the caller's `PYTHONPATH` or working directory. Virtualenv executable
symlinks retain their environment identity. Task options cannot select the interpreter.
Host managers can call `manage_agent_target("probe", {"name":"reviewed-browser"})` or use
`AC_agent_target`, MCP/REST, `agent-task target probe request.json` and the GUI Host targets operation.
The probe uses a separate bounded owned helper, imports browser dependencies through `je_web_runner`,
then retires it without acquiring input ownership or starting a browser. Its result can say
`python_dependencies_ready`; `browser_launch=not_probed` and `native_evidence=not_recorded` stay explicit.
`last_probe` is an in-memory timestamped diagnostic snapshot; passive readiness and task permissions
are unchanged by probing. Disabled targets stay disabled. Desktop/device native probes remain open.
The prepared isolated environment installs wheels from both feature worktrees. Shared environments
and production checkouts remain untouched; production service configuration and real-browser acceptance
remain separate work. Browser automation still belongs entirely to WebRunner (`je_web_runner`).

Desktop finite skills now use the same context-continuity fence as browser skills. Retiring a
desktop scope or its owned helper requires review before an old prefix can continue; paused form/window
state is not established by historical receipts. Live uninterrupted contexts continue normally. File
adapters retain their persistent-artifact recovery. Target checks run before helper replacement, and
existing resume/status/receipt interfaces expose the human-review result. Draft/authentication/window
state restoration and reviewed remaining-step reconstruction remain open; native acceptance stays paused.

A finite browser skill's verified prefix now requires its original live browser/helper context.
After pause, cleanup, helper loss or runtime restart, retained action history cannot prove that the
form still contains its previous values. Continuation enters human review before launching a replacement
helper or sending the next action. Review the remaining steps and create a new task explicitly.
Pausing before any retained attempt and attempts reviewed as failed/not-applied permit a fresh start.
External owners can reobserve a new context and plan fresh scoped actions; ordinary uninterrupted skills
continue on their existing session. Restoring authenticated/draft browser state remains open work.

Local runtime principal and live-root forwarding now requires an explicit local-service call.
Generic authenticated HTTP requests carry the supplied bearer token; local user/store/witness metadata
is attached only by the runtime client after validating the loopback service destination and route.
The versioned `je_auto_control.api` namespace exposes every advertised `api.core` name, including
managed browser commands, target recovery and skills. Executor typing stubs include all shipped commands;
unresolved postponed project types use the generator's existing `Any` fallback instead of invalid names.
Concurrent budget readers sample clocks inside the exclusive database transaction, preventing false
task timeouts when readers acquire locks in a different order. Actual clock rollback remains fail-closed.
GUI/MCP/REST/CLI share these repaired client and API contracts. Production checkouts and existing
native/browser/device/24-hour acceptance pauses remain unchanged.

Managed browser file commands `browser_link`, `browser_download` and `browser_upload` (with matching
`AC_browser_*` commands) delegate to WebRunner transfer contract version 1. Download and upload grants
require explicit host/task roots. Downloads preserve scoped browser cookies inside the owned SDK/helper,
check complete length and optional SHA256, and publish without overwriting an existing file; reuse
requires its matching SHA256. Uploads read one regular file up to 4 MiB into a checked immutable snapshot,
verify optional SHA256 and SDK metadata, and never submit a form. Network operations remain in `je_web_runner`.
The browser `download_archive` preview accepts a query `url`, explicit `allowed_origins`, rooted `directory`
and `files` with a plain `name` and either `url` or link `selector`/optional `frame`; `page_url` can override
the query page per file. It captures fresh links, downloads at most 16 MiB per file and writes a manifest
whose names/sizes/hashes are independently verified. GUI Actions draft file target/workflow/upload examples
without starting resources. MCP/REST/CLI/Builder/model tools share these commands; link reads still require
drive-input authority. Deployment and real-browser acceptance remain open; existing acceptance pauses hold.

Browser tasks accept pinned completion clauses such as
`{"kind":"browser","operation":"value","selector":"#field","value":"expected"}`.
Operations are exact `text`, `value`, `visible` (boolean), or `url` (no locator). They require an explicit
`AC_browser_read` grant and task origins; completion cannot add permissions. At finish, the same owned
helper checks a current allowed HTTP(S) page and independently reads the full SDK value through guarded
read commands. Receipts, bounded previews and model stop messages do not substitute for those reads.
Blank/unavailable/out-of-scope pages, refused readbacks and invalid verifier replies remain unknown;
failed comparisons remain failed. Cancellation, authority revocation and human-review errors propagate.
GUI Actions can draft an inert browser completion example; API/MCP/REST/CLI finish share the verifier.
SPA URL fragments remain intact while origin checks exclude only the fragment. Browser/native
application acceptance and reviewed transfers remain open.

Managed browser startup now requires the exact WebRunner `ManagedBrowserSession.contract_version == 1`
contract before constructing its policy or opening a proxy/browser. Missing, boolean, string, older or
unknown markers fail with an actionable readiness reason. SDK source `575e5d2` provides complete text/value
readback: at most 8,000 UTF-16 code units, with over-limit/invalid Unicode refusal instead of truncation.
AutoControl applies matching Unicode bounds to browser arguments and workflow preview data before effects.
The consumer/SDK source contract is tested through the real owned helper with fake Chromium; deployment
and real-browser/native acceptance remain separate from that evidence.


`draft_agent_workflow("batch_form", config)` and `transfer` accept `backend: browser` with
explicit `allowed_origins` and a reviewed browser target. CSV/XLSX sources stay rooted; browser drafts
emit only `AC_browser_*` actions and never fall back to desktop input. Forms take `url`, CSS `fields`,
optional frame selectors/new-record control, and submit plus confirmation selectors. Each fill has an
independent exact value readback. Optional `confirmation_column` supplies a per-row expected marker.
Transfers take `source_url`/`destination_url`, capture text/value fields, apply an allowlisted transform,
fill and read back destination fields, then verify saving. A stale confirmation is refused before submit.
`AC_browser_wait` / `browser_wait` polls text/value reads only, including a newly visible element;
`wait_seconds` defaults to 5, is capped by the action budget, and late matching replies are refused.
It never repeats a fill or click. Python/core, catalog/model schemas, MCP, CLI/REST task operations,
Builder and GUI workflow preview use the shared compiler. Browser readback can serve as independent
skill evidence. Actual application acceptance and production upload/download configuration remain open.
Managed browser startup requires WebRunner contract version 1 with complete bounded readback.

Managed browser profiles (`kind: browser`) now delegate to the owned `je_web_runner` SDK from
WebRunner (`D:\Codes\WebRunner`; integration source on its isolated managed-session branch).
Profiles require exact `settings.allowed_origins`, browser-only tools and no desktop apps; every task
also declares a narrower nonempty `options.allowed_origins`. Profile/task grants are checked again on
activation. Registration stays inert. Install the reviewed managed-session SDK and its Chromium runtime
in the helper environment explicitly; absent dependencies fail readiness and nothing is installed automatically.
`AC_browser_navigate`, `AC_browser_click`, `AC_browser_fill`, `AC_browser_select`, `AC_browser_check`
and `AC_browser_read` share Python/core, executor, MCP and Builder schemas. They operate inside the
managed helper; drive them through the existing task submit/observe/act lifecycle, not an ambient browser.
The read operation is `text`, `value` or `visible`; secret form controls are refused by WebRunner.
Observation-local DOM indexes resolve selectors and frames after the runtime's freshness check.
Failed effects remain uncertain and require reconciliation; pause/cancel retire owned resources.
GUI Actions can draft a browser target example for review, and DOM selection only edits the action request.
The dedicated helper preserves one fresh session across readiness checks. Ordinary cleanup acknowledges
browser cleanup and reaps its owned process tree; eligible completion sources instead transfer their
actual frozen context to the bounded runtime collection. Browser tasks acquire no desktop input ownership.
Controlled cross-source tests use the real SDK with fake Chromium and owned IPC/loopback. Browser/native
acceptance, production transfer configuration and additional browser workflow kinds remain tracked in `Progress.md`.

MCP asynchronous calls preserve the accepting caller's role, session, exact root policy and
disclosure view; retired sessions and path policies reject late dispatch. Stateless async calls keep
their fixed profile. HTTP tool-list changes reach all live session streams for plugin updates, while
session enable/disable targets one owner and avoids duplicate delivery. Stream registration and HTTP
headers share one lock so an early notification cannot precede the response headers.
The metadata-only `benchmarks/mcp_discovery.py --repeats 20` benchmark records count, JSON bytes,
warm in-process handshake, search and enable latency. The captured Windows/Python 3.14.4 run has
732 permitted tools / 358,029 initial response bytes in full mode and 5 / 2,029 in progressive mode
(99.43% fewer response bytes). Handshake is 58.263 / 47.439 ms; search median is 16.243 / 19.718 ms.
Progressive enable median is 42.486 ms. These local timings exclude cold imports and native work.
See the dated JSON report under `docs/benchmarks/`; argument-policy coverage limits remain in `Progress.md`.

MCP supports opt-in session disclosure: `je_auto_control_mcp --tool-mode progressive` starts
with five discovery controls; `ac_mcp_tools_enable` / `ac_mcp_tools_disable` change only that session.
`--tool-mode static --tool-profile ac_screen_size,ac_list_windows` supplies a fixed profile for clients
that do not refresh tool lists. The default `full` mode retains its unpaginated permitted list.
Progressive/static pages use opaque, single-use cursors bound to a snapshot and caller; changed tools,
roles, view configuration or expired cursors require restarting `tools/list`. Enable/disable notify
the owning connection. Session closure retires outstanding metadata callbacks and clears cursors.
Use `MCPServer.configure_tool_disclosure(...)` for HTTP/embedded servers, or host environment
`JE_AUTOCONTROL_MCP_DISCLOSURE` and comma-separated `JE_AUTOCONTROL_MCP_TOOL_PROFILE`.
`plan_mcp_tool_profile(...)` and Diagnostics Actions preview startup arguments without starting a server.
Stateless requests use a fixed, unpaginated initial profile; they do not retain session enablement.
Read-only ceilings cover later plugin registrations. Unauthenticated/shared-token peers see operator
tools, matching their existing invocation ceiling; host-management tools require authenticated authority.

MCP tool discovery is available through `search_mcp_tools(query, limit=10)` and
`get_mcp_tool_schema(name)`, corresponding AC/MCP commands, and Diagnostics → Actions.
Search returns bounded summaries with category and required capability; full schemas require a
single-tool lookup. Both queries refresh role authority and respect the registry's read-only filter.
MCP queries use that server's live registry, including plugin changes. CLI inspection:
`je_auto_control_mcp --search-tools document --limit 5` or `--tool-schema ac_mcp_tool_search`.
Full mode remains the default; opt-in session disclosure is described alongside this metadata API.

Agent tool calls use `executor.execute_one(name, arguments)`, returning the raw result through
the same authorization, variable interpolation, cancellation and journal boundaries as action scripts.
Private executor arguments are rejected. Managed task delivery is tracked in `Progress.md`.

Crash-safe input ownership uses a durable resource witness before dispatch/input ACK. After host death, explicitly review and recover the target with `recover_agent_target(target, note)` (host management), after manually releasing held input; task receipts still require separate reconciliation. Workspace document handoff runs outside the disposable input helper, and approved focus steps wait for the scoped application window.

Managed skills record verified semantic flows into immutable candidates. `manage_agent_skill` previews typed parameters, runs a separate validation task, and publishes a numbered version only after explicit review of that candidate's verified success. Repairs are new selector candidates with fresh validation; tasks pin their version and digest. AC/MCP/REST/CLI and the Agent Tasks Actions menu share these operations.

For an interrupted validation trial whose actions are all confirmed, explicitly review/create and
finish a separate read-only completion task, then call `manage_agent_skill("accept", {...})` with the
original `task_id` and optional `completion_task_id`. Publication retains the exact candidate/trial
hash/pin, up to sixteen real read-only recovery links, fresh authority and independently verified
retirement. The original stays stopped; its actions are not replayed. The Actions menu can prepare
the request for review. Publication keeps historical completion IDs/hashes after transient reader
evidence expires; unpublished adoption still needs retained evidence.

`manage_agent_skill("record", request)` also accepts `completion_task_id` for a stopped original
workflow. Keep `task_id` equal to that workflow: its confirmed semantic actions become a draft,
while the separate reader supplies private, independently verified completion evidence. Recording
does not replay actions or change the source state. Source/proof checks and draft insertion share
one transaction with live authority rechecks. Historical `provenance.completion_review` survives
reader retention without granting current authority. The draft, including added validation criteria,
still needs its own new exact validation trial before publication. The Actions menu prepares the
record request without executing it.

For a partially executed validation trial, first call `manage_agent_skill("review_execution", request)`
with `candidate_id`, the original `task_id` and a separate final `execution_task_id`. Then explicitly
`accept` those same IDs with the returned `execution_review`, `expected_version` and a nonempty `note`.
At most sixteen actual executable recovery links must confirm the complete original semantic plan;
a successful different remainder is insufficient. Comparison includes JSON types, captured values,
expectations and grounding, without restoring captures or rebuilding historical UI state. Each task
retains its existing limits and separate approval. Current callers, all owners and actual admission
reviewers must remain authorized. Version, publication and historical `publication.execution_review`
commit atomically, with post-write evidence/authority checks. The original stays stopped and retains
`publication.task_id`; no recovery child becomes a fabricated validation trial. An optional
`completion_task_id` must verify the final executable effect and is nested in this execution audit.
Expired evidence cannot approve an unpublished candidate. Two Actions examples prepare review and
accept requests without executing them; `agent_skill_execution_review.json` and
`agent_skill_execution_accept.json` are editable request examples.

Managed tasks retain live origin path ceilings: removing a source root blocks later actions, trigger fires and skill trials. MCP client roots are isolated per session; retiring that client authority revokes its ceilings. Static host policy remains valid until explicitly replaced. Worker shutdown cancels actual running work, including model initialization before input acquisition, while unstarted deliveries remain durable.

Experimental [managed agent tasks](../../AGENT_TASKS.md) provide owner-scoped submit/observe/act/verify,
pause/resume/cancel, fenced target control, durable action receipts, WorkQueue delivery, local Ollama
inference and a background service shared by Python, AC, MCP, REST, CLI and the Agent Tasks view.
Start explicitly with `je_auto_control agent-task start`; new flows have no mandatory external service.
Four reviewable templates cover download/archive, CSV/XLSX forms, cross-app transfer and workspace
preparation. Use `agent-task draft` or Actions → Preview workflow before submitting.
Durable interval/cron/file/event bindings capture approved task scopes, reauthorize each fire and
deduplicate notifications. Submission keys prevent duplicate tasks across retries and restart.
Owner-scoped receipts and explicit uncertain-outcome review link to run history, journals and task
reports. Generated cache expires after 30 days; user outputs and external journals are preserved.
Evidence caches bind the complete database path and a persistent database identity under
`.agent-evidence-cache/`. Restored databases and legacy caches retain their original history references;
the next action or report starts a new owned journal segment without reading or moving historical files.
Task metadata reports `artifact_cache_state` as `owned` or `historical`. Retention removes only the current
database's recognized cache files; historical files remain, and retained private roots cannot be exported.

On Linux, helper processes can run under the optional [owner service](../../../native/owner_service/README.md).
A root guardian runs each helper in its own cgroup v2 tree, which the helper's account cannot leave.
Closing the channel kills the whole tree, escaped descendants included, and a restarted guardian
recovers after a crash. A root-owned `/etc/je_auto_control/owner_service.json` binding routes
exactly listed helper argv through it. Helpers that drive your desktop or browser always run as
local processes, because a protected helper runs as its own ID with an empty environment and
cannot reach your display. Without that binding, helpers keep running as local
processes, and `agent-task status` reports the mode under `helper_containment`. The Python
package never builds, installs or starts the service, and its builds refuse protected launches
until a reviewed release opens the gate.

`agent-task readiness` (`agent_runtime_readiness`, `AC_agent_runtime_readiness`, the MCP tool and the
Agent Tasks view's Actions menu) reports, for the desktop input and capture, the human-presence source,
Android and iOS control, the browser and the local model, one of `unsupported`, `missing_dependency`,
`unauthorized`, `not_probed`, `not_recorded` or `measured`. It reads only the environment, `PATH` and
installed packages: it contacts no device, launches no helper and asks for no permission, so it never
reports `measured` and every area carries `native_evidence: not_recorded`. An installed tool is
`not_probed`, not ready.

Before deployment or rollback, compare exact source and artifact hashes; the unchanged version number alone does
not identify private-cache compatibility. A runtime without this private-root protection must not reuse the
newer database/cache. A reviewed restore must use matching pre-upgrade state at its recorded locations, retire
owned input first, and exclude retained newer private files from every legacy task root. Preserve uncertain
journals and avoid replay. Keep the compatible runtime if these conditions cannot be established.

Windows USB enumeration emits and decodes UTF-8 explicitly and keeps its PowerShell process hidden.
Unicode device names and diagnostics are preserved in both Python UTF-8 modes; enumeration remains read-only.
Native calls use an owned helper with cancellation/deadlines, recorded input cleanup and per-session
exclusion across runtime databases. Windows shared-desktop tasks share a persistent session source across
runtime/task/helper lifetimes and wait for sixty seconds of fresh unlocked inactivity after monitoring starts.
Only an active supported local console can acquire input; remote, shadowed and unknown sessions fail closed.
Each helper freshly checks its fixed host lease before and after input ACK. Source/reader loss pauses input;
unconfirmed held-input cleanup stays fenced for explicit retry. Closing one runtime preserves another's source.
Target descriptions expose coarse `presence` metadata with `native_evidence=not_recorded` and start no probes.
`agent-task stop-all` stops visible tasks. Other shared desktops require a trusted activity adapter.
Native acceptance and the remaining workflows are in `Progress.md`.

Linux's internal presence_peer_linux retains a noninheritable pidfd for the original connected
Unix stream or sequenced-packet peer. It checks account, birth, namespaces and liveness without
reopening a PID. This process identity does not establish desktop or input authority.

The internal LinuxListener and LinuxChannel transport owns its protected Unix endpoint, socket
and peer. Each bounded JSON packet requires the live original writer's kernel credentials and
pidfd. Extra, missing, negative or truncated descriptor controls are refused; received descriptors
retire before delivery. Admission and I/O share one deadline. Cancellation revokes delivery, and
unfinished or failed cleanup stays unconfirmed. Unknown filesystem objects remain untouched.
Pathname permissions do not isolate hostile processes sharing a UID. Bounded userspace waits
do not promise hard realtime kernel syscall completion.

Physical-activity sources now exist for X11 and macOS. X11 counts XInput2 raw events from real
devices, never from XTEST slaves, and reads `Active`/`LockedHint` from logind: without logind or
`XDG_SESSION_ID` the seat counts as locked. macOS uses a listen-only session event tap (it needs the
Accessibility permission). An event counts as injected only when a process posted it from a non-HID
source state, so a doubt keeps a task waiting rather than letting it take over. Wayland has no
trusted source. On Linux the presence broker, worker and server now run over this transport: the owned
worker binds a fresh private endpoint and reports it in its bootstrap reply, the broker adopts only that
endpoint, and connecting pins the listener to the process it names before the presence challenge. macOS has
no presence transport yet, and the runtime still refuses non-Windows shared desktop tasks until native
acceptance. This transport is not full Linux application or native input acceptance.

[![PyPI](https://img.shields.io/pypi/v/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![Python](https://img.shields.io/pypi/pyversions/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../../LICENSE)
[![Documentation](https://readthedocs.org/projects/autocontrol/badge/?version=latest)](https://autocontrol.readthedocs.io/en/latest/?badge=latest)

**AutoControl** is an open-source, cross-platform **computer-use and GUI automation framework** for AI agents, Python applications, and automated testing. It drives the mouse and keyboard, finds UI targets through template matching, OCR, the OS accessibility tree, or a vision model, records and replays flows, and runs deterministic JSON actions across Windows, macOS, Linux (X11 and Wayland), the BSDs, Android, and iOS.

Every capability ships three ways: a **Python API**, an **`AC_*` action command** usable
from JSON files / CLI / servers, and a **GUI tab**. Nothing is GUI-only.

**[繁體中文](../../../README/README_zh-TW.md)** · **[简体中文](../../../README/README_zh-CN.md)**

---
