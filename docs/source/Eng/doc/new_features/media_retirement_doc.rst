Media producer retirement
=========================

Audio, recording and LAN advertisement expose immutable retirement status and
raise ``MediaRetirementError`` for pending or uncertain cleanup. The error retains
the original owner and derives from ``AutoControlException`` and ``RuntimeError``.
Resource closure and finalization have separate acknowledgements. Recording flush
is attempted once; uncertain PyAV or sounddevice close is never replayed to claim
success. Zeroconf close supports retry on its original owner.

HostBrowser rejects late publications, retains admitted callbacks and observes the
original browser thread after one cancellation attempt. Its Zeroconf close can be
retried; failed acquisition remains uncertain. One-shot interruption preserves its
identity and exposes the retained owner if cleanup also fails.

MultiViewerHost's ``create_owned_session_offer()`` returns the SDP and original
session retirement receipt. Capture an existing session with ``session_retirement(id)``
before queuing cleanup. Receipt retries cannot stop a replacement peer or screen
source even when its session ID is reused. The legacy tuple-returning API remains.
GUI disconnect and discarded offers still need to adopt this ownership.

Peer hosts and viewers adopt failed-constructor cleanup owners and expose cached,
immutable ``media_failures``. Failed children cannot be overwritten. Live disable
observes original task completion, and peer close proceeds alongside unrelated
media cleanup. A busy microphone-start slot reports pending without blocking the
bridge loop on its lock. Deferred detach and renegotiation bind their original peer.

This producer unit does not complete application caretaker, GUI saved-result
reporting, GUI discard paths, or HostBrowser dialog ownership. Native acceptance
remains pending; validation uses injected resources only.
