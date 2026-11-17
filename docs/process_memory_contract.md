# Reviewed process-memory observations

This is the internal M0/M1 foundation for the background-operation plan in
[Progress.md](../Progress.md). It supplies a semantic reader and typed Windows
read/query calls tested through injected native functions. It does not supply
trusted executable attestation, runtime authorization wiring, a public memory
command, an application adapter or completed native acceptance.

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
| UI state | UIA read-only element properties for an explicitly selected application | No Invoke, SetValue or focus change | Existing UIA implementation; new background adapter integration pending |
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
   the file facts rechecked around every chunk, and the lease kept open;
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
file. It does not prove the code running now (in-memory patching, loaded DLLs), and it
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
cross-process memory or desktop input. The profile registry, application
attestation, reader-owning production adapter and independent completion
verification remain required before public memory commands can be enabled.

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

No native acceptance command is supplied or executed by this increment. Native
execution stays paused under `Progress.md`; native verification of the typed calls,
trusted bootstrap matching, page-protection fault injection, host probe configuration, runtime
lifecycle/policy integration and application coverage remain required for M1/M3.
