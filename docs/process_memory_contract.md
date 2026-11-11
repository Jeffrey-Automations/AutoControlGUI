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
executable identity. That native resolution remains unimplemented.

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

Headless tests exercise exact local buffer layout and real hidden child-process
communication, invalid requests, EOF and shutdown. These checks do not establish
cross-process memory readback, ASLR resolution, native publication guarantees or
desktop noninterference. Shared-memory mappings were rejected because parent-side
mapping reads would bypass the future process-memory provider.

No native acceptance command is supplied or executed by this increment. Native
execution stays paused under `Progress.md`; native verification of the typed calls,
trusted bootstrap matching, page-protection fault injection, host probe configuration, runtime
lifecycle/policy integration and application coverage remain required for M1/M3.
