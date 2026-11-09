# Completion evidence and handoffs

[README](../../../README.md) · [Documentation](../../README.md)

## Explicit local DAG evidence handoffs

Existing recovery children held by another caller can provide completion evidence to their
original local DAG through an explicit revocable handoff. In `manage_agent_recovery`, use
`review_handoff` with the final `task_id`, `batch_id` and `node_id`; an authorized manager then calls
`create_handoff` with the same IDs, returned `handoff_review` as `review`, and a nonempty `note`.
The service derives the recipient from the real original admission. In a `review_continuation`
successor decision, explicitly include `handoff_id` alongside `node_id`, `action` and `task_id`, then
review and approve the whole continuation. At most sixteen real recovery links are supported,
including a privately admitted permanent read-only final verifier. Ordinary task ownership remains.

`get_handoff` and `revoke_handoff` take `handoff_id`; `list_handoffs` takes `batch_id` and `node_id`.
Issuance and consumption refresh actual owners, admitting reviewers, issuing-session root witnesses,
current consumer ceilings, fixed scope, effect snapshots, independent completion and retirement.
Approval, start and late dependency validation recheck consent; revocation or evidence loss blocks
adoption. Grants expire no later than the earliest retained terminal witness's existing thirty-day
deadline. Returned data contains bounded IDs, hashes and status, without private task arguments,
captures or principal-store paths. No ordinary task-read/input access, ownership transfer or replay is
granted. Cross-host and non-DAG handoff contracts remain outstanding in `Progress.md`.

The Agent Tasks Handoffs page has an operation selector and JSON editor; Actions prepare review,
create and revoke requests without dispatching them. Five editable `agent_handoff_*.json` examples
cover review/create/get/list/revoke. Python, AC, CLI, authenticated MCP, REST and Builder use the
same recovery operations. These checks establish contract and owned-file behavior; deferred native
desktop, browser, device and 24-hour acceptance still require their own evidence.

## Explicit read-only completion authorization renewal

When original origin references are expired or unavailable, explicitly call
`manage_agent_recovery("review_completion_authorization", {"task_id": "<source-id>"})`.
Review the server-derived `verification_spec` and retained/replaced/current origin context, then call
`create_authorized_completion` with the same `task_id`, returned `snapshot`, `authorization_review`
and a nonempty `note`. Optional `owner_policy="source_owner"` requires the returned `ownership_review`
at creation. Callers cannot supply a replacement verification spec. Existing live constraints stay;
new roots intersect the original ceiling, prior reader ceiling and current session. Ordinary
completion review does not replace this explicit consent for an already renewed reader.

The child is permanently read-only. It independently checks current conditions against the actual
confirmed original effects, without input, replay, restoring captures or modifying old witnesses.
Source/effect snapshots, real owners/reviewers and original DAG admission are rechecked. Task admission
and final completion each revalidate inside their own SQLite writer after SQL; changes roll back.
At most sixteen actual recovery links are supported. A retired successful reader may be explicitly
renewed again, retaining its previous narrower ceiling and all still-valid inherited restrictions.
Changed source/effect evidence remains refused and must not be silently repaired by scope renewal.

Historical `get` preserves succeeded state; loss of renewed authority makes its current
`completion_contract` zero and `completion_authorization` unavailable. DAG adoption and late dependency
validation then refuse that evidence. Malformed/missing renewed read-only markers fail before helper
startup. Recording with `completion_task_id` uses the approved restricted scope and original semantic
actions, but the draft still needs its own fresh validation trial. Renewal does not publish an expired
candidate or renew a published skill grant. Existing skill reauthorization remains separate.

Python, AC, CLI, authenticated MCP, REST and Builder share both operations. The Recovery page exposes
two explicit Actions using its selected task, owner policy and request editor. Editable examples are
`agent_completion_authorization_review.json` and `agent_completion_authorization_create.json`.
Remote read-only providers, cross-host handoffs, actual application
state restoration and deferred native/device/browser/24-hour acceptance remain in `Progress.md`.

## Explicit renewed-reader completion handoffs

Existing `review_handoff` / `create_handoff` can explicitly transfer completion evidence from
a privately renewed, permanently read-only reader to its real original local DAG. Select that reader's
task ID and the actual original batch/node. The service derives the proof; callers cannot supply a
policy, ownership override or authorization bundle. Ordinary handoffs keep their existing rules.

The preview's `evidence.completion_authorization` contains the completion task/review, a bound review
digest, approved-root count and replaced/retained/current origin IDs. It omits private principal paths,
action arguments and captures. Set creation's `review` to the returned top-level `handoff_review`, then
provide a nonempty `note`. Every actual task keeps its reviewed ceiling; all live historical restrictions stay, unavailable
references are explicitly reviewed, and the issuing session's additional constraints remain live.
The grant uses the exact already-verified reader roots. A different intersection requires another
real completion review and verification. The consuming session/profile still applies its own limits.

At most sixteen actual recovery links may mix previously reviewed executable successors and private
readers. A succeeded intermediate reader needs actual private historical scope and retirement proof;
an ordinary succeeded source does not gain that exemption. No helper is launched or input replayed
while granting or adopting evidence. Old source state, witnesses, receipts and all task owners stay.
The original owner receives only the bounded completion projection, without ordinary access to the
other caller's task. Revocation or lost authority blocks adoption and late dependency validation.

Original accepted-request hashes, raw submission witnesses, private admission, graph, owners/reviewers,
all real source/child snapshots and the leaf renewal remain bound. Reads and post-write checks use
the same SQLite writer, including uncommitted changes; mutation rolls back admission/grant creation.
An inherited `dag_batch` option is not admission: a bounded real recovery chain must resolve the actual
original request and admitting identity without creating a replacement admission row. Earlier ordinary
completion binding hashes remain compatible. Each historical task retains its own policy review;
combining history cannot bypass the normal sixteen-live-origin limit or any original root ceiling.

Exact active retries retain their note and ID; revoked IDs never reactivate. Restart and adoption
preserve the earliest retained terminal witness's thirty-day deadline. Historical get/list/revoke stay
available after an origin expires, while that history supplies no usable completion or input grant.
Python, AC, CLI, authenticated MCP, REST and Builder share the five existing operations. Existing
Handoffs Actions and its JSON editor/result view show the explicit renewed review without dispatching
consent automatically. Cross-host handoff, remote readers, actual application/device
providers and deferred native/browser/device/24-hour acceptance remain in `Progress.md`.

## Explicit task-source completion evidence handoffs

The five existing handoff operations also accept a real non-DAG source task:

- `review_handoff`: supply `source_task` and the actual final evidence `task_id`.
- `create_handoff`: add the returned top-level `handoff_review` as `review`, plus a nonempty `note`.
- `list_handoffs`: supply `source_task`; `get_handoff` and `revoke_handoff` still use `handoff_id`.

Task-source fields and DAG batch/node fields are mutually exclusive. The service resolves persisted
grant IDs to their actual storage family. Original DAG ancestry must use its real batch/node route,
even if a later read-only reader dropped its `dag_batch` option. No synthetic DAG node or admission
is created. Ordinary standalone tasks need no invented submission witness or idempotency key;
any actual accepted request is bound and rechecked on the same SQLite writer.

Select `handoff_id` explicitly in existing skill operations. `record` uses a separate verified reader
through `completion_task_id` and creates a draft which still needs its own new validation trial.
`accept` with `completion_task_id` keeps the actual original candidate's validation task.
`review_execution` and its matching `accept` may select an actual `execution_task_id`; add
`completion_task_id` when the final granted evidence is a separate reader. The service verifies
the exact complete original semantic action plan, real execution IDs and independent final criteria.
A reader never becomes an execution task or a substitute validation trial.

The grant yields only a private bounded evidence view. Original task owners, source state and
receipts remain; ordinary get/list/observe/act/resume access never expands. Granting or adopting
launches no helper and replays no input. Real source/child snapshots, original optional requests,
actual owners/reviewers, retired input and every live historical origin remain checked. New recorded
drafts retain both issuing and consuming session ceilings. Unavailable restrictions require actual
private completion renewal; matching hashes or caller-authored scope flags cannot replace it.
Read-only evidence adoption does not renew a published skill's original input authorization.

At most sixteen real recovery links include source ancestry and the forward granted chain. Earliest
retained terminal evidence expires after thirty days; anchoring at a later reader cannot extend an
older ancestor. Same-writer post-insert and exact-retry checks honor revocation tombstones for both
DAG and task grants. Source/request/role/origin/revocation changes roll back grant creation, draft
recording or publication. Revoked IDs never reactivate. Historical get/list/revoke after an origin
expires expose bounded IDs and hashes, not continued completion or input authority.

The Handoffs page explicitly selects original local DAG or original task when preparing JSON.
Three skill Actions prepare recording, publication or execution review with a handoff placeholder;
they do not issue consent or publish automatically. Python, AC, CLI, authenticated REST/MCP and
Builder share the same operations and actual caller identities. Editable requests are
`agent_task_handoff_review.json`, `agent_task_handoff_create.json`, `agent_skill_recording_handoff.json`,
`agent_skill_completion_handoff.json`, `agent_skill_execution_handoff_review.json` and
`agent_skill_execution_handoff_accept.json` under `examples/`.

Cross-host handoffs, remote readers, actual application/device providers, deferred native
and twenty-four-hour acceptance, and unresolved HTTP409/bootstrap issues remain in `Progress.md`.

Installed wheel and source distributions include the REST Dashboard and Swagger HTML, CSS and
JavaScript resources. The same localhost REST routes and authentication rules apply to an
installed package; serving static pages grants no task or desktop input authority.
