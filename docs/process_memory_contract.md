# Reviewed process-memory observations

This documents the background-operation work in [Progress.md](../Progress.md).
It supplies a semantic reader, typed Windows read/query calls, an owned fixture
assembly and a managed fixture profile. Verification uses injected native
functions and buffers. Native acceptance, trusted runtime dependencies and real
application integration remain incomplete. No arbitrary-address memory command
is exposed.

## Ownership and scope

An application adapter owns a `ProcessMemoryReader` inside its existing managed
helper. The runtime remains the owner of tasks, cancellation and action authority.
A separate observer service was rejected because it would require another
authentication and lifecycle boundary before an observation could be used.

The host reviews a `ReviewedProbe` with exact application versions, architectures,
semantic field names, decoder and resolver. A query only chooses a subset of those
fields. It cannot provide addresses, offsets, expressions, process enumeration or
new permissions. A probe is executable trusted adapter code, not serialized user
configuration. The package is intentionally absent from the facade, executor,
MCP, REST and GUI registries until those boundaries have real policy integration.

The runtime adapter must pass its live `TaskOperation.checkpoint` into `observe`.
The default checkpoint only checks cooperative cancellation; it is not an
authorization check. Calling the internal reader does not authorize reading a
process. Existing desktop foreground and input-presence gates are unchanged.

## Windows capability matrix

| Operation | Source and scope | Background requirement | Evidence and present state |
|---|---|---|---|
| Process/session identity | Retained OS handle, creation time, session and architecture; reviewed application attestor | Read/query/synchronize rights only; no privilege escalation | Typed calls and injected tests implemented; executable attestation and native acceptance pending |
| UI state | UIA read-only element properties for an explicitly selected application | No Invoke, SetValue or focus change | Scoped reader and internal read-only managed adapter have injected/helper coverage; native deployment trust and acceptance pending |
| Browser state | Existing WebRunner managed DOM session and reviewed origins | Dedicated managed browser; no desktop input fallback | Existing browser path; this reader adds no browser access |
| Fixture semantic state | Reviewed schema resolved for the retained fixture process identity | Bounded `VirtualQueryEx` / `ReadProcessMemory` provider; no writes | Typed provider and injected-call tests implemented; trusted resolver and native acceptance pending |
| Application command | Each application's official API, CLI or IPC with scoped resources | Must independently prove no foreground/focus/mouse/input interference | Application selection and command adapter pending |
| OS service operation | Specific approved service's management interface | Explicit service scope and independent status readback | Adapter and policy integration pending |
| Completed background task | Fresh state or artifact verification under current runtime authority | Observation does not grant execution rights or replace a completion receipt | End-to-end M4/M5 integration pending |

The same matrix is data in `utils/process_memory/background_profile.py`
(`WINDOWS_PROFILE`), and a test keeps the two row for row. A route names one
of a closed set of `Channel`s; desktop keyboard, mouse, focus and foreground
switching are not channels, and a route naming one is refused when it is
built. `route(profile, operation)` returns a route only when its state is
`existing` or `injected_tests`; an unknown operation or a pending adapter is
`unsupported`, never a fallback to desktop input. The module reads and opens
nothing and imports no input, wrapper or native code.

## Retained identity and private reads

`ProcessIdentity` includes host/session identifiers, PID, process birth, executable
identity and version, architecture and pointer width. A retained provider handle
must report the actual process identity, including after reads. Reused PIDs and
changed identity invalidate the whole observation.

### Windows provider and attestation boundary

`windows.py` owns each process handle and serializes identity, query, read and close.
It opens only `PROCESS_QUERY_INFORMATION`, `PROCESS_VM_READ` and `SYNCHRONIZE`.
The last right permits a zero-time process-liveness check. It never requests write,
terminate, all-access or privilege-adjustment rights. Failed close keeps ownership
with the existing reader cleanup queue.

`windows_native.py` binds DWORD and BOOL with fixed widths and address/length
arguments with pointer-sized ctypes. `VirtualQueryEx` uses the caller's 28-byte
or 48-byte layout, including when a 64-bit caller observes a 32-bit WOW64 target.
A 32-bit caller refuses a 64-bit target. `IsWow64Process2` must be available;
unknown architectures are unsupported rather than guessed.

The provider measures PID, process creation time, Windows session ID, architecture
and liveness from the retained process relationship. A required host-reviewed
attestor receives those immutable `NativeProcessFacts` and returns a `ProcessIdentity`.
It must independently bind host/session, executable identity and application version
to those facts and the owned launch. The provider supplies no default attestor,
passes no expected identity to the callback, rejects replaced native identity fields,
and measures facts again after attestation. A path string, fixture nonce, self-reported
digest or a callback that merely echoes an expected identity is not an attestation.
The production attestor and trusted fixture bootstrap matching remain unimplemented.

### Owned-launch attestation

`windows_launch.py` is the first attestor, chosen by the maintainer on 2026-11-15.
It attests only a process the host launches itself. `PinnedExecutable` is host
configuration: the host and session labels, the executable and version identifiers,
and the SHA-256 of the image bytes (64 lowercase hex digits). `launch_attested` then:

1. leases the image file with a fresh `WindowsImageObserver.lease(path, ...)`: opened
   with `GENERIC_READ` and only `FILE_SHARE_READ`, digested from its actual bytes, with
   the file facts rechecked around every chunk, and the lease kept open. Before any byte
   is read, `windows_image_trust.require_trusted_image` refuses the path unless every
   directory from the drive root down is a real directory (no reparse point) that no
   account outside SYSTEM, Administrators, TrustedInstaller and the running user may
   rename, delete, re-link, re-ACL or add files to, and the leased handle's final path is
   the requested path. The lease fixes the bytes; this keeps `CreateProcess`, which
   resolves the path again by name, and the loader's search of the image's directory on
   that same file. An observer built with an injected kernel must inject this check too,
   or its lease refuses;
2. requires that digest to equal the pin, in constant time, before anything is started;
3. calls the caller's launcher, which must return a `LaunchRecord` holding the PID and
   birth it measured from the new process's own handle (the launcher owns the child and
   ends it if attestation fails);
4. observes the child's image with a second fresh observer and requires the same
   volume, 128-bit file ID, size and digest as the lease, and the same PID and birth as
   the record.

Only then does it return an `OwnedLaunch` whose `OwnedLaunchAttestor` mints a
`ProcessIdentity` for those native facts and refuses any other (a different birth, PID
or session). One deadline covers both measurements. On failure both observers are closed
and the original error propagates; launcher exceptions become `unsupported` without their
message, and cancellation signals propagate unchanged.

What it proves: the bytes on disk, held against writers from before the launch until
the observation, are the pinned ones, and the child the host started maps that same
file. The default fixture channels (`pinned_channel`, `pinned_uia_channel`) start the
child in the image's directory with `pinned_child_options`: a minimal environment whose
`PATH` holds only the system directories, so neither the host's working directory nor
its tokens and keys reach the fixture. It does not prove the code running now (in-memory patching, loaded DLLs), and it
cannot attest a process the host did not start.

`PopenLauncher(arguments, **popen_options)` is the launcher. It starts the image from an
argv list (`shell` is refused) and measures PID and birth from the handle `Popen` holds,
the one `CreateProcess` returned, so the measurement cannot land on a process that
reused the PID. It refuses a measured PID that differs from `Popen.pid` and a second
launch, and keeps the child as `child` for the caller to wait on or end. Tests drive
the real observer and launcher code through injected native calls and a fake `Popen`;
nothing has been launched natively.

### Observed image-file evidence

`windows_image.py` adds a separate one-shot `WindowsImageObserver`. It acquires
only a query/synchronize process handle, measures birth/session/architecture from
that retained relationship, and queries its current image filename. The file is
opened with `GENERIC_READ`, `OPEN_EXISTING` and only `FILE_SHARE_READ`; a successful
lease excludes ordinary write/delete opens and conflicting writable mappings.
File type, volume plus 128-bit file ID, timestamps, attributes and size are measured
from that same file handle. SHA-256 is computed from its actual bytes. Native facts,
image filename and file metadata are rechecked around the bounded read sequence.

The caller must provide a byte ceiling, timeout and live checkpoint. The finite
artifact ceiling is 64 MiB and the read buffer is at most 64 KiB; these are resource
bounds, not measured performance targets. Checkpoints run between acquisition
phases and file chunks, not every individual metadata syscall, and cannot interrupt
a blocked native call. The observer is not an authorization service. Native ABI
errors become closed failure reasons; checkpoint and cancellation exceptions
propagate unchanged.

A successful `observe` returns `ObservedImageFile`, with private identity and digest
fields omitted from representations. It retains both leases until explicit `close`.
Failure/cancellation retires the observer and attempts cleanup. Failed handles stay
owned, `pending_cleanup` remains true, and `close` retries only those handles. The
caller must retain the observer until cleanup succeeds. An observer cannot be
reused for another acquisition, including after retirement.

This is current image-file evidence, **not loaded-image or launch attestation**.
The queried pathname could refer to different current backing bytes from those
originally loaded. It does not prove Python fixture source or imported runtime
code. No `ProcessIdentity` is minted from this evidence, no expected identity/digest
is accepted as a measurement, and no public tool is added. Owned launch/source
delivery, loaded-image binding, trusted runtime dependencies, fixture attestor and
per-launch resolver remain unimplemented. Injected tests exercise the actual
acquisition code with fake native buffers; native acceptance remains paused.

The ABI and file semantics follow Microsoft's
[QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew),
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
and [FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)
contracts. Image-name length validation uses Windows UTF-16 code units, including
non-BMP and unpaired-surrogate filenames, rather than Python code-point counts.

Each native read is limited to 1 MiB and one committed, readable, unguarded region.
The semantic reader splits reviewed ranges at region boundaries under its smaller
per-probe budget. Failed or short reads publish no bytes; post-read region and native
identity changes fail the observation. These checks and cooperative checkpoints do
not interrupt a blocked syscall. Owned helper retirement remains M3 work.

Two provider shapes were considered: exposing raw handles to application adapters,
or retaining handle lifetime and native checks behind `ProcessHandle`. The latter
keeps cleanup and read bounds in one owner. The attestation callback receives facts,
not a raw native handle, and must use separately reviewed launch evidence.

ABI references are Microsoft's [memory information layouts](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-memory_basic_information),
[VirtualQueryEx](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex),
[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory),
[IsWow64Process2](https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2)
and [process access rights](https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights).

The reviewed resolver runs anew for each observation. It supplies one private
payload range and optionally an eight-byte sequence range. A native adapter must
resolve its current module/fixture location from the retained target relationship;
it cannot cache an absolute address across launches or trust a path string as
executable identity.

The resolver is called as `resolve(identity, view)`. The view is its only reach
into the target and is valid for that one call; afterwards every call on it fails.
`view.read(address, size)` goes through the same checked path as payload reads and
is charged to the same byte, region and deadline budget. `view.main_module()`
returns a `ModuleSpan` (base and size, hidden from representations) measured from
the retained handle: on Windows the first module `K32EnumProcessModulesEx` lists,
which Microsoft documents as the executable, with `LIST_MODULES_32BIT` for a WOW64
target seen from a 64-bit caller, and `K32GetModuleInformation` repeating the same
base. The reader then requires that base to start the allocation of a committed,
readable mapping. A failure raised by the reader's own checks inside the view
(budget, deadline, changed target, the live checkpoint) is kept and raised again
after `resolve` returns, so a resolver that catches it cannot still produce a plan.
Only injected tests exercise this; native module resolution is unverified.

The reader visits only intersecting regions. Each region must be committed,
readable and unguarded. Addresses, lengths and pointer-width arithmetic are
validated before reading. The provider must return exact immutable bytes.
Region metadata and process identity are checked again after every chunk.
Short reads, changed mappings and inaccessible pages produce no partial values.

The byte budget includes sequence reads. Region visits are charged per chunk,
including repeated sequence visits. One monotonic deadline covers opening,
resolution, reads, decoding and successful return after cleanup. Every provider
call and decoder invocation has checkpoints before/after the operation. These
checks detect overruns but cannot preempt a blocking native call or decoder;
the future owned helper must supply hard process retirement and provider time
bounds. This package does not claim a hard real-time timeout.

## Semantic output and consistency

The decoder returns exactly the requested fields as bounded strings, signed
64-bit integers, booleans or null. The reader copies them to an immutable tuple.
The result includes the adapter's target ID and a digest of the checked process
identity, so a changed process birth cannot reuse an earlier observation's identity.
No mapping, raw byte buffer, handle, PID or address is returned. Sensitive process
identity and semantic values are omitted from object representations. Reviewed
schemas must exclude secrets; an allowlisted semantic value is intentionally
visible to its authorized caller.

For a target with a sequence protocol, the reader requires an even sequence before
the payload and the same sequence afterward. The target must increment to an odd
value before changing the payload and publish the next even value afterward.
The result says `sequence_checked`; it does not imply a snapshot if the target
does not implement that protocol. A target without it returns `best_effort`.
Repeated equal bytes alone never imply atomicity. This increment performs one
attempt; an inconsistent observation fails instead of retrying with a fresh budget.

Successful sequence-checked observations retain the checked counter as `revision`.
Best-effort observations have `revision=None`. Consumers can distinguish equal
semantic values separated by a target update, instead of treating value equality
as evidence that the target has not changed. A revision does not make a subsequent
command atomic; the command adapter must compare it at its own commit boundary.

Failures have closed reasons for unsupported probes, denied scope/access, changed
targets, unreadable regions, partial reads, inconsistent snapshots, exhausted
budgets/deadlines, decoding and cleanup. Provider adapters should use
`MemoryObservationError`, `PermissionError` or other `OSError` subclasses for
expected native failures. The reader normalizes other ordinary provider exceptions
to a safe failure too; resolver and decoder exceptions never expose their original
messages. Provider adapters must not log captured data or addresses themselves.
Cancellation, executor stop and hard interruption signals propagate after cleanup
instead of becoming ordinary failures. Live checkpoint authority errors also
propagate unchanged; only failures raised inside provider/resolver/decoder calls
are normalized, not the surrounding runtime authority checks.

## Managed semantic grounding

The runtime has an internal `SemanticTarget` contract for host-selected adapters.
Every concrete semantic target must implement `cleanup()`. Retirement failures
must raise while retaining resource ownership for retry; adapters without cleanup
cannot be instantiated. The worker uses this same contract when closing after EOF
or revocation.
Task JSON and observation fields cannot opt an ordinary target into it. Existing
targets retain full-payload fingerprinting and their existing `perform` calls.

`SemanticSnapshot` validates the exact observation schema at runtime ingress.
It preserves target identity, adapter/schema, source, semantic fields, consistency,
completeness and revision in the grounding fingerprint. Only observation ID and
capture timestamps are excluded. The runtime still expires observations after
30 seconds and rejects replaced observation IDs. Invalid, incomplete or unknown
helper fields fail before publication. Semantic values are omitted from repr.

Grounded dispatch supplies the original snapshot and the prepared journal action
ID to `perform_grounded`. Adapters must recheck state at their commit boundary.
`SemanticReceipt` binds a successful result to that operation ID and declares
`atomic` or `non_atomic` comparison. A receipt confirms the adapter's reply, not
independent task completion or desktop noninterference. A wrong-operation receipt,
untyped reply or `AgentEffectUnknown` follows the existing uncertain journal path;
the consumed observation cannot be replayed. Unknown effects require readback.

`MemorySemanticTarget` binds a reader to a host-selected `MemoryBinding`: target
ID, measured process identity, reviewed probe and allowed fields. It pins the ready
task specification and authorization owner (user, role and source store), and
requires the matching live managed scope for every read and
command. Read failures retain their sanitized reason; they never become empty
snapshots. Pending handle cleanup prevents further reads. Grounded dispatch checks
policy, reads again and compares provenance/state before forwarding the original
snapshot and operation ID to the separate command owner. Only that owner can
claim atomic comparison at commit. Cleanup permanently retires the target and
raises until pending reader handles are closed; repeated cleanup retries ownership.
The host must create a dedicated target/reader/command owner per resource lifecycle.
This seam has injected-provider runtime tests and is used by the fixture profile
described below. Memory failure reasons retain their type across
the owned helper channel. The worker emits only a closed reason code and fixed
message, never the memory exception text. The host requires the exact error schema
and rejects unknown reasons, extra fields and mixed event/result packets without
echoing their contents. Legacy unstructured memory errors are rejected rather than
parsed from text. This preserves read failure distinctions; an error after command
dispatch still follows the uncertain-effect journal path, not automatic replay.

`FixtureCommands` implements the internal `AC_fixture_set_state` adapter operation
with exactly `document_id` and `job_status` arguments. It requires the host's
schema-one binding, both fixture fields, a checked memory revision and a private
launch nonce. The owned control transport receives only `compare_set`, under a
one-second exchange ceiling and the live task checkpoint. This ceiling bounds the
fixture exchange; it is not a measured service-level performance claim.
Receipts must match the operation, nonce, requested values, exact scalar types and
expected revision plus two. Unknown replies stop further commands; cleanup retains
transport ownership until closure succeeds. The transport must retire failed
streams to prevent late replies from serving later requests. The runtime never
automatically resends an unknown effect. The internal command is not registered as
a standalone public executor command; it is offered only by a fixture task.
Native launcher and attestation acceptance remain pending. Injected tests combine the actual reader, fixture buffers and
runtime completion; they do not establish native acceptance.

`OwnedFixtureControl` wraps an already host-owned `OwnedChannel`; construction
performs no launch and transfers ownership only after challenge validation succeeds.
The fixture's optional `--rpc` mode uses correlated request IDs and exposes only
bootstrap, snapshot and compare-set operations; legacy fault-injection `set` is
unavailable over RPC. Bootstrap stores only validated private locations and nonce,
not a measured process identity. Control frames retain the fixture's 1,024-byte
limit and one-second deadline ceiling. Typed state and receipt schemas reject
unrecognized fields before returning data. Failed exchanges or malformed results
retire the channel; failed retirement retains its owner for cleanup retry.
Close can interrupt a waiting request without acquiring its lock. Hidden subprocess
tests cover this behavior without cross-process memory reads. A Windows venv
launcher can spawn a second interpreter, so the channel's launch PID and the
fixture's self-reported PID must not be assumed equal or used as attestation.

`OwnedFixtureTarget` is an internal, unregistered assembly for the native fixture.
The host constructs it with a `FixtureImage`, an owned launcher, two fresh image
observers and a provider factory. Explicit diagnostic callers use
`start(checkpoint=...)`; managed callers may let `ready()` start it lazily. The
provider factory must return an unopened provider using the supplied launch
attestor. Task JSON cannot supply these objects. Startup parses the pinned baseline,
attests the launch, checks bootstrap identity, and binds the image guard to the
original launch hash before publishing the private semantic target.

Managed readiness requires the exact current task, fixed target and fixture command
scope. It pins the task and owner key, including the authorization-store path,
before acquisition. Readiness admission is nonblocking and remains exclusive until
the private memory target is bound. A competing caller cannot claim a newly
published inner target. Startup callbacks use the original operation and recheck
that context before readiness succeeds. Failure after the claim retires the
resources; unrelated scope refusals do not retire an existing owner's target.

The hidden `memory_target_helper.py` test fixture serves this path through the real
semantic worker/proxy with injected launch calls and buffers. It uses a fresh
synthetic identity per helper process, not OS attestation. Tests cover semantic
completion, typed read failures and process retirement. Semantic worker requests
pin task, owner/store provenance, target and profile kind. Dispatch, reader checkpoints,
command guards and result publication refresh the original owner's stored authority.
Any role change, including an upgrade, requires a new host-reviewed session. Missing
or damaged stores fail closed with fixed wire errors. Command guards retain the
original request checkpoint even inside a temporarily replaced operation scope.
Cleanup remains available after revocation. Trusted local and explicit storeless
owners retain the existing deferred-authorization semantics.

These checks use real temporary user stores and injected memory. They cannot make
revocation atomic with a read or interrupt a blocked syscall. The host still owns
cancellation, live profile checks and helper retirement.

`NativeSemanticTarget` selects the existing non-display channel route through a
fixed host-class property. Task options cannot select display routing. On Linux,
a configured owner-service binding must list the exact helper argv; policy or
service failures cannot fall back locally. Without a binding, the existing local
route remains available and carries no owner-service containment claim. Desktop
and browser proxies retain their display route. Bootstrap validation and retained
cleanup ownership use the same proxy implementation for both channel types.

Injected routing tests do not prove Linux containment. Reviewed helper source,
imports and authority-store access under the service's separate identity and empty
environment still need provisioning. A child fixture also needs nested-grant
integration. These remain production prerequisites, with native execution paused.

The private packaged entry is `je_auto_control.utils.agent_runtime.fixture_worker`.
Only reviewed host code supplies its `--config` absolute path and independent
`--config-sha256` digest. It accepts no launch configuration through ordinary RPC.
The schema-one JSON file has exactly these fields:

```json
{
  "schema": 1,
  "host": "reviewed-host",
  "target": "fixture",
  "image": "C:\\reviewed\\memory_fixture.exe",
  "image_sha256": "<independently reviewed lowercase SHA-256>",
  "read_timeout": 1
}
```

The config digest covers its exact bytes, including whitespace. The loader checks
it before following the image path, rejects duplicate or unknown fields, limits
config bytes to 16 KiB and image bytes to 64 MiB, and validates the pinned PE plan
against the existing 1 MiB observation ceiling. The read timeout must be positive
and at most 60 seconds. Executable/schema labels remain fixture/1; PID, addresses,
argv, session and challenge are not config fields. Each worker creates fresh
session and challenge values. The leased launch rechecks the image pin, so static
preparation does not replace launch-time attestation.

`load_fixture_image()` performs static preparation only. The native factory accepts
64-bit Windows, and `OwnedFixtureTarget.ready()` remains the process-acquisition
boundary. EOF or a rejected owner/task before readiness starts no fixture. The
entry uses the existing worker protocol and guarded cleanup. Reads are bounded in
bytes, not wall time; opening a replaced special file can block before the regular
file check. The host-owned helper deadline and retirement remain the interruption
boundary. Constructing the worker registers no profile by itself. Config and image pins do not establish
interpreter, imported-source or DLL trust, and native execution remains paused.

The assembly selects a read budget of the complete image plan plus the fixture's
72 bytes, capped at 1 MiB, with at most 1,024 region checks. The host chooses a
finite read timeout of at most 60 seconds (default 1 second). Startup image
measurement and each bootstrap exchange separately retain their 1-second bounds;
there is no claim of a single wall-time deadline for the whole startup sequence.
The runtime integration test explicitly selects a 5-second read budget to include
policy checkpoints. This is a ceiling, not a measured performance guarantee.

Cleanup retires the launcher first to interrupt IPC, tries every resource even
when one fails, and retains failed owners for later cleanup calls. Retirement
prevents late startup publication. The public wrapper never exposes its private
semantic target, and runtime completion uses the same cleanup path. Interruption
signals take precedence over ordinary cleanup failures after all owners are tried.
Injected tests prove the assembly contract; DLL trust, native loaded-image
compatibility and desktop noninterference remain unverified. No profile or public
command registration is enabled by this assembly.

`OwnedChannelLauncher` adapts the existing `PopenLauncher` to the same owned IPC
process. `launch_attested` can lease the pinned executable, start the channel,
measure PID/birth from its retained launch handle and observe the same image file.
The one private process-handle seam is host code only. `bind_control` then requires
bootstrap PID and pointer width to match that measured identity; a launcher shim's
descendant is refused, never silently substituted. This does not prove loaded-code
integrity, trusted interpreter dependencies or source delivery. Keep it unregistered
until those requirements and native acceptance are satisfied.
The caller retains launcher, lease and observer owners during attestation. An
attestation failure after launch leaves the channel with its launcher for explicit
cleanup; failed lease or process retirement remains retryable. Launcher close does
not close the separately owned image leases. Tests inject native calls and channels;
this assembly has not launched a native attested fixture.

`NativeSemanticTarget` carries the same contract over the existing owned helper
channel. Trusted host code supplies the reviewed helper argv and an explicit
resource lock. The helper must advertise semantic protocol version one before
configuration. Both sides refuse desktop input, including cleanup. Worker cleanup
also denies executor commands, whether requested over IPC or triggered by EOF.
The host accepts only an exact boolean cleanup acknowledgement before retiring a
live helper; an unconfirmed cleanup retains ownership for retry.

The worker rechecks task tool scope and the closed request schema before calling
the adapter. Existing host checkpoints enforce cancellation and deadlines while
waiting for replies. `AgentEffectUnknown` and `AgentObservationStale` preserve
their types across the shared channel. A blocked fixture command has been
cancelled after entry and its actual helper process retired in a headless test.

`test/fixtures/semantic_helper.py` tests this IPC path with an owned counter, not
cross-process memory or desktop input. The dedicated fixture profile uses the
same semantic protocol; application attestation and reader-owning native adapter
verification remain required before claiming native readiness.

## Semantic completion

### Managed fixture profile

The existing `manage_agent_target` / `AC_agent_target`, CLI target operation and
GUI Host targets JSON editor accept a dedicated `fixture` kind. Registration
requires `manage_hosts` and is inert. No fixture process starts until an authorized
task reaches managed readiness. An example profile shape is:

```json
{
  "name": "fixture",
  "kind": "fixture",
  "allowed_tools": ["AC_fixture_set_state"],
  "roots": [],
  "apps": [],
  "settings": {
    "config_path": "C:\\reviewed\\fixture.json",
    "config_sha256": "<independently reviewed lowercase SHA-256>"
  }
}
```

The profile name must match the deployment's target. Only these two settings are
accepted. Tasks cannot supply them, choose a helper interpreter or argv, grant
filesystem roots or desktop applications, or expand the fixed tool set. The proxy
uses the current interpreter with `-I -u -m` and the packaged fixture worker, so
that interpreter must have the reviewed package installed. Isolation flags are
not source attestation.

The host verifies a closed bootstrap extension containing fixture contract version
one, the loaded config digest and target ID. Before changing its scope, the worker
requires the matching fixture profile, deployment path/digest and host-issued task
profile pin. Omitting the profile is refused. The generic semantic worker is unchanged.
Immutable profile identity, persistence, live disablement and explicit resume use
the existing runtime controls. The adapter's Windows x64 gate runs before helper
acquisition. The GUI Apply target action passes the same profile through the shared
service; no separate GUI authority exists.

Passive listings retain `readiness=not_probed` and `native_evidence=not_recorded`.
The explicit diagnostic `probe` uses a separate non-display helper with a 15-second
bootstrap deadline and a 10-second artifact inspection deadline. It validates the
pinned configuration and PE bytes without constructing a native target or executing
the fixture. Successful reports contain `status=static_artifacts_ready`, bounded
`checked_bytes`, `fixture_execution=not_run` and `native_evidence=not_recorded`.
The private worker's `--inspect` mode accepts only empty bootstrap/inspection requests;
it refuses task configuration, desktop events and execution. Static inspection is
portable; it does not bypass the Windows x64 gate for actual fixture acquisition.

At most two inspections may own capacity in one host process, with one per profile
per runtime. Host-management authority is refreshed during request polling and before
publication. Timeouts and cancellation retire the helper. Failed retirement retains
its owner and capacity for runtime-close retries. Shutdown seals new admissions and
retains the runtime database lock while construction or retirement is unfinished,
including when no task lease exists. Passive listing never starts this helper.
The GUI target-operation selector with Apply target and the headless target-control
API use this same path.
Neither this diagnostic nor the injected roundtrip/disable tests prove native
availability or loaded-code trust. Native execution remains paused.

### Completion evidence

Host-selected semantic adapters can declare an ordered `observation_sources`
contract and a nonempty `observation_fields` tuple of at most 64 unique field names.
Every source must corroborate every declared field. The first declared source is
the command's primary snapshot. Such adapters return
an `ObservationReport` through the existing observation API; task JSON cannot enable
this capability. The native proxy requires the exact source contract and report
version 3 and sorted `semantic_fields` in the worker bootstrap. Versions 1 and 2
are rejected. A generic semantic proxy refuses that extension.

The report requires `field_scope`; `from_dict` requires host `fields` as well as
`required` sources. The wire scope must match the host scope exactly, and source
fields outside that scope are rejected. Even a field omitted by every source
remains missing; if every source fails, all required fields are missing.

Reports retain up to four sources, each tagged as `snapshot`, `partial` or `failure`.
A `PartialObservation` contains validated `CaptureMetadata`, successful scalar
fields and fixed per-field failures. Its values and failures must be disjoint and
together cover the host field scope. The field failure reasons are `not_found`,
`ambiguous`, `protected`, `unsupported`, `unreadable` and `budget_exceeded`.
Valid empty strings, false booleans and null values remain values, never substitutes
for failed reads. Reports preserve capture intervals, missing field names and typed
value conflicts. All successful and partial captures
must refer to the same target lifetime. The host adapter must normalize its reviewed
fields into the same schema and revision domain before declaring this contract.
Equal values with different revisions conflict; boolean and integer values do not
compare equal. Agreement without checked revisions remains `unverified`. Partial,
conflicting and unverified reports remain visible but cannot ground commands.
Authority, cancellation, target-change and cleanup errors are not reportable as
ordinary missing-source reasons and must propagate from acquisition.

Action fingerprints retain every source's state and provenance. The complete report
crosses the helper boundary unchanged before the worker converts it to the primary
command snapshot. The journal retains the full source report and original `semantic_fields`.
Completion parses both reports against that saved scope, so later adapter changes
cannot shrink the requirement. Completion requires fresh compatible evidence from every original source; disagreement or missing
sources produces an unknown result. The complete-only `SemanticSnapshot` wire schema
is unchanged and lives in `semantic_snapshot.py`, re-exported by `semantic_target.py`.

The managed fixture now captures `process_memory` and `fixture_protocol` sources.
The IPC source uses the retained launch-bound control, stamps identity from the
measured memory binding and accepts only the fixed snapshot fields and sequence.
Capture and precommit readback share one owner lock; cleanup can interrupt IPC
without acquiring that lock. Before `compare_set`, fresh complete agreement must
still match the original memory snapshot. The fixture remains responsible for its
atomic sequence comparison at commit.

Safe memory read failures retain the IPC snapshot in a partial report. Unsupported
memory observations can indicate failed code attestation and therefore propagate,
as do scope, lifetime and cleanup errors. IPC protocol/transport failures are not
downgraded to missing sources; their retirement failures remain reachable. Checkpoints
revalidate the captured operation and owner before and after each source boundary.

Tests use injected native calls/buffers, the actual reader and real hidden Python
helper IPC. The scoped UIA reader described below preserves explicit field failures
and best-effort capture metadata. Browser profiles with `semantic_fields` report
host-declared DOM fields through the same schema as a `dom` source bound to the
managed browser context (`dom_observation.py`); the DOM has no revision, so those
captures stay best-effort. Native UI deployment trust remains pending. Existing foreground desktop or
legacy DOM dictionaries are not converted automatically. This work is not native
observation or background-application acceptance.

A `semantic` success criterion compares fresh completion-time observations with
the recorded target witness for a named command. For the test-owned counter:

```json
{"kind": "semantic", "tool": "AC_increment", "fields": {"value": 1}}
```

The command must already be in the task's allowed tools. The criterion grants no
additional fields, reader, native target or command. The Agent Tasks scope JSON
editor and its Submit action preserve this condition through the shared task API.
The host must explicitly register a fixture profile; no fixture is enabled by default.

Before semantic dispatch, the journal stores the validated original snapshot.
Only a host-selected `SemanticTarget` supplies this witness. Completion uses the
last effective attempt for that command; an uncertain attempt stays unknown,
while attempts proven to have no effect do not discard earlier completed work.
Every semantic observation must use the host's `time.perf_counter()` clock domain
and have its entire capture interval inside the current runtime read request.
(`time.monotonic()` ticks every 15.6 ms on Windows before Python 3.13, too coarse
to order a capture against its acceptance.)
The runtime rejects cached pre-dispatch reads and future timestamps before
publication or verification. A helper on another clock domain cannot use this
contract without a separately reviewed clock/proof protocol.

The current snapshot must match target identity, adapter, schema and source, have
a checked revision at least as new as the witness, and use a different observation
ID with a capture interval starting after the witness ended. Best-effort snapshots,
changed identities, missing fields and absent witnesses yield `unknown`.

Expected fields are bounded scalars compared without coercion. A valid readback
with different values yields `failed`, even when the command returned success.
An exact match yields `passed`; other criteria and unresolved receipts still
prevent task success. `result_equals` continues to inspect the prior result only.
IPC fixture tests cover lying success replies and helper restart; these checks do
not establish native memory acceptance or desktop noninterference.

## Cleanup ownership

Each observation opens and closes its own handle. A failed close remains owned
by the reader; `pending_cleanup` stays true and `close_pending()` explicitly retries
only retained failed handles. A close failure cannot return a successful observation
or claim retirement. If cancellation and failed close coincide, cancellation still
propagates and the reader retains cleanup ownership. The future runtime adapter
must retain the reader/helper while this flag is true; dropping the reader is not
proof that the process handle retired.

## Native fixture protocol and acceptance design

The headless fixture in `test_process_memory_reader.py` uses schema version 1:
little-endian `uint32 document_id`, followed by a 12-byte zero-padded ASCII
`job_status`. States are exactly `ready`, `busy` or `done`. An optional independent
eight-byte little-endian sequence counter follows the even/odd contract above.

The future native fixture must be a repository-owned child process. Its owned
bootstrap channel reports its birth identity, executable/version digest and the
current payload/sequence locations. The parent must measure and match these facts
against its retained read-only process handle before constructing a reviewed probe.
The fixture exposes a separate test-control channel for changing state and fault
injection; memory writes are performed by the fixture itself, never by the reader.

Native acceptance must cover 32/64-bit layout, ASLR across restarts, guard/no-access
pages, cross-region payloads, changed protection, short reads, process exit, PID
reuse, permission denial, cancellation and failed handle retirement. Compare exact
semantic values to fixture-owned expected values. Independently observe foreground
window, focus, mouse and desktop-input events to establish noninterference.

### Native artifact preparation

The separate [native fixture source](../test/fixtures/native_memory/README.md) is
an x64 C implementation with static CRT. Its builder compiles a captured source
copy, rejects ambient compiler options, checks unchanged source, and inventories
the image without executing it. Current direct imports are `bcrypt.dll` and
`kernel32.dll`; source, image and build-tool hashes are recorded per build.
This removes the Python interpreter/source chain from this candidate artifact,
but does not establish loaded-image or OS dependency trust. Protocol behavior,
foreground noninterference and native fault cases remain unverified.

`plan_pinned_image` now derives a factory-only code plan from the full pinned
baseline SHA-256. The supported format is bounded x64 PE32+ with all executable
sections enumerated. The parser rejects writable executable sections, overlapping
layouts, invalid entry points, unsupported relocation types, and relocations or
import-address tables that touch protected bytes. Headers and complete aligned
executable spans are included; callers cannot construct or replace a plan to omit
coverage. File and image bounds are 64 MiB, and protected reads are capped at 1 MiB.

`guard_probe_image` requires the exact `OwnedLaunch.image_sha256` as well as matching
application/version labels. The caller must explicitly supply sufficient probe
limits; the guard never raises those limits. Every observation checks the header
and code hashes through the same retained, bounded resolver view as semantic data,
then rechecks module base/size before and after the underlying resolver. A mismatch
publishes no semantic values. Budget, cancellation and cleanup behavior stay with
the reader. No raw executable bytes enter observations.

Loaded addresses differ from file offsets, and relocations may change bytes; see
Microsoft's [PE format specification](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format).
This implementation rejects relocation of protected bytes instead of normalizing
it, with one exception the loader makes to every relocated image: the header's
`ImageBase` must equal the measured base and is then compared as the file's value.
Padding to section alignment is conservatively projected as zero after raw data;
one x64 MSVC image has matched natively. A short read or padding
mismatch refuses the image rather than dropping coverage. Matching these ranges
is not atomic execution integrity, live page-protection evidence, DLL/source trust,
or proof that no other executable mappings exist. x86/ARM64 image plans remain
unsupported. Unit tests use synthetic mappings and static build-artifact inspection.

### Owned fixture preparation

`fixture_probe.py` supplies the internal schema-one adapter. `FixtureBinding`
copies validated bootstrap locations and the parent challenge into an immutable
binding. It rejects unknown protocol/schema versions, incorrect structure sizes,
invalid pointer widths, overflowing ranges and overlapping buffers before reading.
Each resolution checks the retained process PID and pointer width, then reads and
compares the header challenge and locations. This binding is not an attestor.

Its probe accepts only application version `1` and the separately attested
executable ID. The 72-byte ceiling covers the 40-byte header, 16-byte payload and
two eight-byte sequence reads. The decoder requires exactly 16 bytes and canonical
zero-padded `ready`, `busy` or `done` states, even for a query that selects only the
document ID. Unknown fields and mixed generations publish no semantic values.
Injected-provider tests cover this adapter; native acceptance remains paused.

`test/fixtures/process_memory_fixture.py` owns fixed payload and sequence buffers
for its process lifetime. Its bounded JSON-lines protocol uses inherited stdin and
stdout pipes. Bootstrap and control replies have distinct message kinds on the
same transport. This is not yet the separate native acceptance control channel.
Only the fixture changes its buffers. The parent can request expected semantic
state, a validated state change or shutdown; it cannot request arbitrary memory
reads or writes.

The additive `compare_set` command requires an operation ID, launch nonce, expected
even sequence, document ID and job status. The serial server compares the sequence
and publishes the change in one command. Its receipt states `atomic` only relative
to that server's commands. This is not a guarantee against arbitrary memory writes.
Exact retries return the original receipt, including after later state changes;
conflicting reuse of an ID is refused. Launch-bound refusals are also retained.
A 128-entry fixture ledger never evicts: new IDs are refused when full, while old
receipts remain queryable. This is a fixture resource cap, not a performance target.
The legacy `set` command remains for fault injection; runtime adapters must use
`compare_set`. A restart changes the nonce and refuses old requests. Receipts are
not durable across restart, do not attest executable identity, and never replace
independent state readback. Hidden IPC tests cover replay and fresh snapshots;
native memory and desktop noninterference acceptance remain paused.

Bootstrap reports PID, pointer width, buffer locations, fixture source digest and
a fresh launch nonce as unverified self-reports. The nonce is not OS process birth,
and the source digest is not measured executable identity. No reviewed probe may
trust these records without the future provider's independent identity checks.

The parent binds the reported locations with a header challenge. It chooses 16
random bytes and launches the fixture with `--challenge <32 hex digits>`. The
fixture writes a 40-byte header into its own memory (`<8s16sQQ`: magic `JEPMFIX1`,
the challenge, the payload address, the sequence address) and reports the header's
location in the bootstrap. `challenge_resolver(challenge, bootstrap)` in the fixture
module is the reviewed resolver: it requires the identity's PID to equal the
bootstrap PID, reads the header through the resolver view, compares the challenge
in constant time, requires the header's locations to equal the bootstrap's, and only
then returns the plan. Any mismatch produces no plan. This proves the locations are
in the process the retained handle reads; it does not attest the executable, which
remains the attestor's job. Headless tests run it through the real reader against
the fixture's own buffers in the test process; a cross-process native run is still
paused.

Headless tests exercise exact local buffer layout and real hidden child-process
communication, invalid requests, EOF and shutdown. These checks do not establish
cross-process memory readback, ASLR resolution, native publication guarantees or
desktop noninterference. Shared-memory mappings were rejected because parent-side
mapping reads would bypass the future process-memory provider.

The native fixture README documents a static-by-default smoke CLI with an explicit
execution option. Its external image pin and source inventory checks do not establish
dependency trust. Injected smoke tests cover initial state, receipts, fresh readback,
managed completion and retryable cleanup, without running the native artifact.
The C fixture can also prepare fixed split/guard/no-access/decommitted payload
layouts, with bootstrap as their only operation. Source review and compilation do
not validate native page behavior. The diagnostic page runner binds private payload
locations through the checked bootstrap and observes the actual reader's existing
queries. It requires exact adjacent region metadata, a successful eight-byte prefix
read before the second-page query, and one handle for the whole observation.
Changed mappings or evidence from multiple observations cannot pass. Each case
claims and consumes a fresh observation scope; earlier successful traces cannot
be replayed against another target. Split mode
requires complete initial semantic readback; refusal modes require both the expected
reader reason and matching payload evidence, without reading the protected half.
These cases request only read-only IPC snapshots, never state mutations, and do not
claim runtime completion or full native
fault coverage. Only injected tests have exercised the runner.
Native execution stays paused under `Progress.md`; native verification of the typed calls,
trusted bootstrap matching, page-protection fault injection, host probe configuration, runtime
lifecycle/policy integration and application coverage remain required for M1/M3.


### Owned UI fixture preparation

`test/fixtures/native_memory/build_fixture.py --kind uia` builds a separate hidden
window artifact with fixed read-only controls for future scoped UIA tests. Its
schema-2 manifest and kernel32/user32 import allowlist are distinct from the memory
fixture. The default memory build retains its existing schema and dependencies.
The UI artifact has only a correlated one-line private bootstrap and EOF shutdown,
no state mutation API. `OwnedUiaLauncher` uses a receive-only `OwnedUiaChannel`,
which inherits hidden process-tree ownership and bounded startup waits. Its closed
1024-byte envelope rejects duplicates, extra fields and repeated/ended streams.
No command or input acknowledgment can be sent through this channel.

`OwnedProcessChannel` now owns the common launch/retirement lifecycle used by both
fixture launchers. `PopenLauncher.facts()` measures the original retained launch
handle again; bootstrap PID never selects a new process to open. Before publishing
`BoundUiaWindow`, the owner validates the attestor and window PID on both sides of
a checkpoint, then checks current authority again and fences retirement. Binding
verification repeats these checks and retires on failure. File leases remain owned
by the separate `OwnedLaunch`; callers must retain and close both owners.

The binding proves only that this HWND currently belongs to the retained process.
`ScopedUiaSource` additionally pins the root runtime ID across captures, checks the
original HWND and PID, and verifies raw-tree ancestry before and after property
reads. Host code supplies exact automation IDs and chooses only `name`, `value` or
`enabled`. Traversal and ancestry walks have finite budgets. Text reads require
password checks before and after reading; an unavailable protection property is
reported as protected. COM calls remain on the source's owning thread.
Runtime IDs are opaque and may be reused. Pinning and repeated checks detect
observed replacement; they do not establish atomic state or permanent window identity.

`UiaObservationTarget` is an internal read-only managed adapter. It pins the original
task and owner, creates the optional native COM backend during managed readiness,
and publishes source `uia` through report version 3. Per-field failures retain valid
fields from the same capture. A complete UIA capture still has `revision=None` and
`consistency=best_effort`, so it cannot authorize actions or semantic completion.
The adapter rejects commands and grants no Invoke, SetValue, focus or input rights.
During a capture every COM call re-validates the pinned task and owner, while the full
runtime checkpoint (cancellation, durable budget, live authority) runs at most every
50 ms; the unthrottled checkpoint after the capture runs before anything is published.

`owned_uia_target` retains the launcher, pre-launch lease and post-launch observer
before acquisition. `UiaFixtureImage` requires the separate `uia-fixture` version-1
identity, an absolute Windows path and bounded image bytes. Its `attestation_timeout`
covers image attestation; window bootstrap has a separate five-second timeout.
The enclosing helper must bound total readiness and blocking COM work.
The managed adapter owns readiness and terminal state; no second lifecycle is
introduced. Cleanup attempts child retirement first and then both image owners,
retaining failures for retry. The publication lock contains no native work and
prevents source installation after cleanup. `native_uia_target` constructs inert
owners and does not launch a child or create COM until managed readiness.

The helper owner must bound blocking COM work and retain cleanup ownership.
Injected COM tests cover scoped reads, field failures and root replacement; hidden
Python helpers cover managed reporting and timeout retirement. Native deployment
trust remains pending. No native UI executable was run, and native UIA property
exposure and desktop noninterference remain unverified. The UI artifact manifest
stays schema 2; it is independent of observation report version 3. See the fixture
README for the field table and startup protocol.

The typed owner query follows Microsoft's
[GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid)
contract: both the returned thread ID and output PID must be nonzero.


### Fixed read-only UI worker deployment

The host-managed `uia_fixture` profile has empty `allowed_tools`, `roots` and
`apps`. Its settings contain only an absolute `config_path` and the independently
verified `config_sha256` of that file. Profile registration, reload and probe do
not read an image or launch a helper. Probe currently reports `not_supported`
with `native_evidence=not_recorded`; it is not the memory fixture static inspector.

The UI configuration is a closed JSON object with exactly these fields:

| Field | Required value |
|---|---|
| `schema` | Integer `1`, excluding booleans |
| `kind` | `uia_fixture` |
| `host`, `target` | Bounded identifiers; target must match the profile name |
| `image` | Absolute Windows path to the host-reviewed UI fixture |
| `image_sha256` | Independently reviewed lowercase SHA-256 digest |
| `max_image_bytes` | Integer from 1 through 67,108,864 |
| `attestation_timeout` | Number greater than zero and at most 60 seconds |

The shared pinned loader bounds configuration to 16 KiB and rejects duplicate
keys. It hashes the exact configuration bytes before following the image path.
The UI loader bounds and hashes image bytes before constructing owners. The
original launch still leases and rechecks the image; startup self-reports never
select a new PID. Memory deployment and UI deployment schemas remain distinct.

The proxy uses the fixed isolated module `je_auto_control.utils.agent_runtime.uia_worker`.
Its bootstrap must match report version 3, source `uia`, the fixed UI fields and
an exact `uia_fixture` object containing integer `version=1`, configuration SHA
and target. The worker validates platform, deployment reference and original
profile/target pin before mutating scope or acquiring resources. Both worker
and proxy reject effect requests, including direct grounded calls. Existing
host management, CLI and GUI JSON routes carry the profile without new commands.

An empty task tool scope is accepted only in external mode with no planned
actions. Existing completion criteria remain mandatory and `actions_complete`
refuses empty plans. Partial and best-effort UI reports cannot prove semantic
completion. These tasks expose observations for review; they do not imply a
successful effect or grant later input authority. Task options cannot replace
host deployment settings. Disabling the profile revokes work and retires the
original helper under the existing runtime ownership rules.

Tests use injected image/window/COM functions and real hidden Python helper IPC.
The isolated packaged worker help command was checked without native acquisition.
No UI profile was registered against a real native deployment. Trusted helper
source/interpreter/DLL delivery, actual UIA behavior and desktop noninterference
remain pending in Progress.md.

## Internal service-status prerequisite

`WindowsServiceStatusReader` in `agent_runtime/windows_service.py` accepts one
host-selected service key name. Construction validates and binds functions but
opens no handles. Its first `read(timeout=..., checkpoint=...)` opens the local
active SCM database with `SC_MANAGER_CONNECT`, then the named service with
`SERVICE_QUERY_STATUS`. It retains both handles until `close()`. Callers must
retain the reader before reading and through any failed cleanup retry.

Only Win32 own-process/shared-process services, optionally interactive, are
accepted. The reader has no enumeration, remote host, process access, start,
stop, configuration or elevation methods. This is an internal prerequisite,
not a registered profile, executor command, public API or supported os.service
operation. The managed helper, report adapter and operation/readback cycle
remain in `Progress.md`.

The nine-DWORD status is the latest SCM report, marked `best_effort`. Its progress
checkpoint is not a revision. PID is diagnostic only and omitted for stopped,
start-pending and stop-pending states, or when zero. Accepted controls do not
grant operation permission. Query success does not establish an atomic snapshot,
actual instantaneous service state or process identity.

Every admitted acquisition/query/checkpoint failure retires the reader. Close
sets retirement before waiting for the serialized native call, attempts service
then SCM cleanup, and retains failed handles for retry. Nested reads are refused;
checkpoint-triggered close is supported. An admission timeout does not retire
another read already in progress. Deadlines reject late output but cannot
interrupt native calls or cleanup; enclosing helper retirement remains necessary.
Injected tests establish these contracts without calling actual services.

Official contracts are documented in
[QueryServiceStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryservicestatusex),
[OpenSCManagerW](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-openscmanagerw),
[OpenServiceW](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-openservicew)
and [SERVICE_STATUS_PROCESS](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_status_process).

### Internal control and independent readback

`WindowsServiceController` composes the same private session owner as the reader.
Its host-supplied immutable allowed-operation set selects START and/or STOP rights
in addition to QUERY_STATUS. The reader still grants only query rights and does
not bind control functions. Both façades keep service handles private.

`perform(operation, expected=before, operation_id=journal_id, timeout=1,
checkpoint=checkpoint)` rereads through the retained handle and rejects changed
status before dispatch. START requires STOPPED. STOP requires RUNNING or PAUSED
and a reported STOP control bit. This comparison is non-atomic. Start has no
arguments; stop sends only SERVICE_CONTROL_STOP. The returned control status is
discarded because it is not independent readback.

Before entering the native call, the session records an uncertain attempt in a
bounded, non-evicting ledger. A successful return and final checkpoint produce
an acceptance receipt, never proof of completion. A repeat of the same ID and
request returns that original receipt without dispatch. A conflicting ID reuse
is refused. Native failures, including start error 1053, cannot establish absence
of effects. Uncertain attempts prevent further control in that owner; fresh
reads remain diagnostic and cannot clear uncertainty.
The ledger belongs to this retained session, not durable storage. A helper restart
cannot reconstruct accepted requests; the runtime must retain its journal and
refuse automatic replay across that boundary.

An accepted start blocks new controls until a separate public read reports
RUNNING. An accepted stop similarly waits for STOPPED. The preflight read inside
another perform cannot clear this fence. Thus stale SCM status cannot by itself
cause automatic repeated controls. Reaching the ledger limit refuses another
operation before any effect. The session does not poll, retry, stop dependencies,
change service configuration or elevate privileges.

This implementation remains internal. A future managed profile must review
configured dependencies because SCM can start them with the selected service.
It must also establish operation authority, helper retirement, truthful service
readback criteria and desktop noninterference. Existing best-effort observation
and semantic completion gates are unchanged. Native services have not been run.

See [StartServiceW](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-startservicew),
[ControlService](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-controlservice)
and the [service database](https://learn.microsoft.com/en-us/windows/win32/services/database-of-installed-services).

### Managed service evidence

The in-process managed adapter has a separate service dispatch contract. It does
not implement `SemanticTarget` or convert SCM progress into a revision. A service
observation carries fixed target/configuration/scope identifiers, a retained-owner
binding, a unique observation ID, a capture interval and strict status fields.
The binding identifies this owner lifetime, not a Windows service incarnation or
process identity. The outer dispatcher rejects captures outside its current read
request and fingerprints state without capture IDs or timestamps.

Readiness pins the original task specification and authorization provenance.
Operations recheck that scope before and after checkpoints. Only the host's
allowed `AC_service_start` and `AC_service_stop` operations with empty arguments
can reach the retained controller. Cleanup retires publication before closing the
controller, and failed cleanup remains owned for retry.

The closed completion clauses are:

```json
{"kind": "service_state", "tool": "AC_service_start", "state": "running"}
```

```json
{"kind": "service_state", "tool": "AC_service_stop", "state": "stopped"}
```

Only these tool/state pairs are valid. The criterion must refer to a tool in the
task scope and cannot be used as a resume precondition. A confirmed journal
attempt must match the acceptance's operation ID and operation, with identical
target, configuration, scope and binding across the original observation,
acceptance and new readback. The new capture must begin after acceptance and use
a new observation ID. Cached acceptance retains its original timestamp.

A fresh report with another state fails the condition. Missing acceptance,
unknown effects, old captures, mismatched provenance or another owner binding
produce unknown. Passing means the latest SCM query after acceptance reported
the requested state. It does not prove health, causation, atomic completion or
desktop noninterference. Existing semantic revision and multi-source report
gates remain unchanged.

Tests use the real managed runtime and injected service calls. Owned helper IPC
and service locking are described below. Dependency review, trusted production
deployment and native acceptance remain pending.

### Owned service helper IPC

The service proxy uses a host-selected helper argv and the existing owned channel
with display acquisition disabled. Bootstrap binds version, target, configuration,
service scope and retained-owner binding before observations or effects are
accepted. Every report and acceptance must match that binding. A replacement
helper cannot reuse the earlier owner's evidence. Service commands use a separate
`perform_service` message; ordinary `perform` and semantic `perform_grounded`
cannot dispatch them.

The worker shares background request and retirement guards with semantic targets,
while retaining separate service schemas. Private service configuration accepts only the
fixed task spec and owner. It rejects profile, presence and extra fields before
changing worker state, and pins the original spec and authorization-store source.
Request checkpoints refresh that authority. Request, cleanup and EOF retirement
all refuse desktop input and new cleanup commands. Cleanup accepts only empty
key/button collections and retains failed ownership until retirement succeeds.

Service query errors cross IPC as fixed `ServiceFailure` codes. Unknown reasons,
mixed error formats, extra fields and custom error text are rejected without
echoing their contents. Error envelopes are checked before input events.

Service keys are at most 256 UTF-16 units and contain no slash, backslash or
NUL. A printable ASCII key keeps its original ASCII-folded scope. Any other key
must not contain control, format, surrogate, private-use or unassigned
characters, or any separator other than the plain space, and is folded per
UTF-16 unit with the NT upcase table (`RtlUpcaseUnicodeChar`), the table
case-insensitive registry keys, and so service keys, are compared with. That
table folds at least as much as SCM, so two spellings of one service cannot
hold separate locks; it differs from Python's case mapping (`ß`, `ı`, the
Kelvin sign and `µ` are left alone) and Python's is never used. A key that
folds to printable ASCII shares that ASCII scope. Off Windows there is no such
table and non-ASCII keys are unsupported. Case aliases share one scope and
resource path; whitespace is preserved. The resource key excludes target
name, configuration digest and database path. Two owners using the same lock
root therefore contend for the same service, even with different task/profile
names. The default root is the current user's `.je_auto_control/service_ownership`.
Construction computes paths without launching a helper or acquiring a service.

This is coordination between framework owners using that root. Coordination
across Windows users and external SCM clients is not provided. The lower-level SCM reader's Unicode name support is unchanged.
Hidden Python helper tests inject service calls and check actual child retirement;
they do not establish native SCM compatibility or desktop noninterference.
### Pinned service profiles

A host-reviewed `service` profile accepts exactly `config_path`, `config_sha256`
and `service_key` settings. The key determines the same-service lock before
helper launch. Registration, reload and probe do not open the deployment file,
start a helper or access SCM. A missing deployment therefore does not prevent
reopening the runtime to manage unrelated targets, including when the service
profile is disabled. Probe reports `not_supported` and `native_evidence=not_recorded`.

The fixed worker loads at most 16 KiB of raw configuration and checks its pinned
SHA-256 before parsing the duplicate-free, closed object:

```json
{"schema":1,"kind":"service","target":"reviewed-service","service_key":"ExampleService","operations":["start","stop"]}
```

Operations must be a nonempty unique list drawn from `start` and `stop`. The
profile may narrow that ceiling through `allowed_tools`; tasks may narrow it
again. Neither grants filesystem roots, desktop apps, arbitrary helper commands,
remote SCM connections or credentials. The service key in the profile must match
the loaded key's canonical scope. Case aliases match; whitespace is preserved.
The deployment digest binds configuration bytes; the profile digest binds the
host's task policy. They are separate identities.

Pinned-worker configuration requires exactly `spec`, `owner` and `profile`.
It validates deployment identity, operation ceilings, platform and the task's
profile digest before delegating the unchanged spec and owner to the private
worker contract. The full original task pin prevents later profile substitution.
Private helpers still reject profile injection. Bootstrap and readback continue
to require the same retained-owner binding; restarting cannot confirm an old
command using a new owner.

The profile does not attest a service executable, its dependencies or its desktop
behavior. START can activate configured dependencies. No profile is registered on
a real host by this change, and trusted interpreter/package delivery, dependency
review and native background acceptance remain outstanding.
