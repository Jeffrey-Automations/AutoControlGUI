# Media producer retirement

Audio capture/playback, session recording, and LAN advertisement distinguish stopped input from confirmed resource retirement. Their `retirement_status` is an immutable snapshot. `stop()` raises `MediaRetirementError` when retirement is pending or uncertain. The exception derives from `AutoControlException` and `RuntimeError`, and retains its original `owner` for inspection. Retain the owner independently of a page or a task callback.

```python
from je_auto_control.utils.remote_desktop.media_retirement import MediaRetirementError

try:
    producer.stop()
except MediaRetirementError as error:
    original_owner = error.owner
    status = error.status
    # Persist this owner and outcome in the application's retirement owner.
```

`resources` and `finalization` are separate `Completion` values. `CONFIRMED` acknowledges the operation, `PENDING` means admitted work remains, and `UNCERTAIN` means an operation failed without a reliable completion observation. `retryable` describes whether a remaining operation can be attempted; it grants no authority to execute it. A terminal uncertain result remains visible on repeated stop calls. Success does not prove native device behavior beyond the library acknowledgement.

## Audio

Each stream generation owns its admission gate. Callbacks and writes are admitted only after native start acknowledges success; callbacks during start are dropped. Late capture callbacks are dropped, and an admitted callback or write keeps retirement pending until it returns. Stop does not wait on a callback that could itself be asking to stop. Retry the same owner after the operation finishes. A new start cannot overwrite an unresolved generation. Successfully retired instances can start a new generation; callbacks from the previous generation remain rejected.

Native stop and close use sounddevice's `ignore_errors=False`. Cleanup does not reload the optional backend. Both operations are attempted even if stop fails. A failed stop leaves graceful finalization uncertain even when close succeeds. A failed close retains the original stream wrapper, but is not automatically retried. Sounddevice clears its native pointer before reporting a close error, so calling close again cannot recover or acknowledge the original close. Failed-start cleanup follows the same ownership rule.

## Recording

Stopping closes frame admission under the same lock used for encoding. Encoder flush is attempted once, including packet iteration and muxing. Partial flush, mux, write, or setup failures remain recorded. Container close still runs independently. A failed PyAV close is terminal uncertain because it may mark the trailer operation done before raising. Repeating close could then return normally without repairing the failed trailer. The failed container remains owned for diagnosis.

`has_output` indicates that initialization succeeded; it does not mean that the recording was finalized or can be read. Only a complete retirement status acknowledges successful finalization. A recorder is terminal after stop; create a new instance for another recording.

## LAN advertisement

Unregister is attempted once, and Zeroconf close is attempted even when unregister fails. Zeroconf documents close as idempotent, so a failed close can be retried on that same owner. Successful close does not convert failed unregister into a confirmed goodbye. Constructor failure attempts cleanup and returns a retained owner through `MediaRetirementError` if ordinary cleanup remains unresolved. Cancellation and hard control signals keep their original identity. For those signals, `interrupted_retirement_owners(error)` returns the explicitly attached cleanup owners, including when the interruption was wrapped. The application must retain those owners before discarding its error outcome.

## LAN browsing

HostBrowser closes publication admission before cleanup. An admitted callback keeps
retirement pending until it returns, including when that callback requests stop.
Browser cancellation is attempted once; completion requires observing the original
browser thread exit and acknowledgement of Zeroconf close. Only that documented
idempotent close is retried. A failed constructor can leave acquisition uncertain,
even after known resources close. Retain its error owner; never infer completion
from the absence of a returned browser object. One-shot browsing preserves an
original interruption and attaches the browser owner when cleanup also fails.

## Wrappers and current limits

MultiViewerHost offers `create_owned_session_offer()` for asynchronous delivery.
The result contains `session_id`, `sdp`, and a `retirement` receipt retaining the
original peer and shared screen source. Use `session_retirement(session_id)` to
capture an existing session before queuing cleanup. Calling the receipt's `stop()`
retries only that generation. A reused ID or replacement source is unaffected;
other sessions retain their shared source. The legacy `create_session_offer()`
still returns its two-item tuple, and `stop_session(id)` targets the current ID.
GUI disconnect and discarded-offer paths still need to adopt these receipts.
This does not resolve all partial peer-constructor or source-subscription failures.

Mic wrappers retain children when child stop fails. Opus track ending also rejects queued PCM and wakes a waiting receive operation. Opus receiver cancellation retains the exact task until actual completion is observed; cancellation requested is not completion. Repeated stop can observe a completed task. Direct TCP host cleanup continues socket/client teardown after an audio failure and retains the original capture for later observation.

These producer contracts do not complete application shutdown. The application caretaker, original-authority Diagnostics retries, GUI success reporting, HostBrowser dialog ownership, and all peer replacement/discard paths still require integration. In particular, a GUI must not display a recording as saved just because `has_output` is true. Existing consumer paths that swallow errors or drop references are not made durable by this producer unit. Native media/network acceptance remains pending. Validation for this unit uses injected resources and event-loop tasks only.
