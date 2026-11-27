/* eslint-env webextensions, serviceworker */
// Background service worker — owns the recording state machine and
// turns inbound events from the content script into AutoControl JSON
// action entries. Translation lives in ``actionFor``.
//
// The headless suite runs this module in the Qt JavaScript engine
// (test_browser_extension_runtime.py), which does not parse async /
// await, object spread or an optional catch binding — so this file
// sticks to promise chains and Object.assign.

// nosemgrep: codacy.javascript.security.hard-coded-password
const STATE_KEY = "autocontrol.recorder.state";  // nosemgrep: codacy.javascript.security.hard-coded-password

/**
 * @typedef {Object} RecorderState
 * @property {boolean} recording
 * @property {string|null} startUrl
 * @property {number|null} tabId  the tab whose events are recorded
 * @property {Array<Array>} actions  AC_/WR_ JSON action entries
 */

const DEFAULT_STATE = Object.freeze({
    recording: false,
    startUrl: null,
    tabId: null,
    actions: Object.freeze([]),
});

function freshState(overrides) {
    return Object.assign({}, DEFAULT_STATE, { actions: [] }, overrides);
}

function loadState() {
    return chrome.storage.local.get(STATE_KEY).then((stored) => {
        // ``stored`` is whatever chrome.storage round-trips for us; we
        // only ever copy own enumerable properties onto a fresh default.
        /* eslint-disable security/detect-object-injection */
        const saved = stored != null
            && Object.prototype.hasOwnProperty.call(stored, STATE_KEY)
            ? stored[STATE_KEY] : null;
        /* eslint-enable security/detect-object-injection */
        if (saved == null || typeof saved !== "object") {
            return freshState({});
        }
        return freshState(saved);
    });
}

function saveState(state) {
    return chrome.storage.local.set({ [STATE_KEY]: state });
}

/**
 * The ``${secrets.NAME}`` reference recorded in place of a sensitive
 * field's value; the executor resolves it from the secret vault at replay.
 * ``name`` comes from the page, so it is reduced to an identifier here.
 *
 * @param {string} name - the field's name, id or autocomplete hint
 * @returns {string}
 */
export function secretReference(name) {
    let safe = String(name || "").replace(/\W+/g, "_").replace(/^_+|_+$/g, "");
    if (!safe) {
        safe = "password";
    }
    if (/^\d/.test(safe)) {
        safe = "_" + safe;
    }
    return `\${secrets.${safe}}`;
}

// A sensitive event never carries its value into the recording, even
// from an older content script that still sent one.
function keysFor(event) {
    return event.sensitive ? secretReference(event.secret) : (event.value || "");
}

/**
 * Translate one captured DOM event into an AutoControl JSON action.
 * Pure function — used by both the live recorder and the test suite.
 *
 * @param {Object} event - {type, selector, value, url}, or
 *     {type: "input", selector, sensitive: true, secret, url}
 * @returns {Array|null}
 */
export function actionFor(event) {
    if (!event || typeof event.type !== "string") {
        return null;
    }
    switch (event.type) {
        case "navigate":
            return ["AC_web_open", { url: event.url }];
        case "click":
            return ["AC_web_run", {
                action: "WR_left_click",
                params: { element_name: event.selector },
            }];
        case "input":
            return ["AC_web_run", {
                action: "WR_send_keys_to_element",
                params: {
                    element_name: event.selector,
                    keys: keysFor(event),
                },
            }];
        case "submit":
            return ["AC_web_run", {
                action: "WR_element_submit",
                params: { element_name: event.selector },
            }];
        case "key":
            return ["AC_web_run", {
                action: "WR_press_key",
                params: { keycode: event.value || "" },
            }];
        default:
            return null;
    }
}

function startRecording(message) {
    // The popup names the tab it started in; only that tab's events are
    // recorded (see recordEvent), so typing in another tab never joins.
    if (!Number.isInteger(message.tabId)) {
        return { ok: false, reason: "no tab to record" };
    }
    const startUrl = message.startUrl || null;
    return saveState(freshState({
        recording: true,
        startUrl,
        tabId: message.tabId,
        actions: startUrl ? [["AC_web_open", { url: startUrl }]] : [],
    })).then(() => ({ ok: true }));
}

function stopRecording(state) {
    return saveState(Object.assign({}, state, { recording: false }))
        .then(() => ({ ok: true, actions: state.actions }));
}

function recordEvent(state, message, sender) {
    if (!state.recording) {
        return { ok: false, reason: "not recording" };
    }
    // The content script runs in every tab; the sender's tab ID is set
    // by the browser, not by the page. A navigation keeps the tab ID, so
    // the recording follows the tab from page to page.
    if (sender?.tab?.id !== state.tabId) {
        return { ok: false, reason: "not the recording tab" };
    }
    const action = actionFor(message.event);
    if (!action) {
        return { ok: false };
    }
    state.actions.push(action);
    return saveState(state).then(() => ({ ok: true }));
}

// Every command — start, stop, reset, an event, and the reads too — runs
// its load -> change -> save as one link of this chain. Two quick events
// therefore never both read the same old action list (the later write
// dropping the earlier action), and an event still being written when
// Stop arrives finishes before Stop reads the state, so it cannot put
// ``recording: true`` back afterwards.
let queueTail = Promise.resolve();

function serialised(task) {
    const result = queueTail.then(task);
    // A failed link still answers its own caller with the error; the
    // chain itself carries on so one bad write does not stall the rest.
    queueTail = result.then(() => undefined, () => undefined);
    return result;
}

function dispatch(message, sender) {
    return serialised(() => loadState().then((state) => {
        switch (message?.command) {
            case "start":
                return startRecording(message);
            case "stop":
                return stopRecording(state);
            case "event":
                return recordEvent(state, message, sender);
            case "status":
                return { ok: true, state };
            case "reset":
                return saveState(freshState({})).then(() => ({ ok: true }));
            case "export":
                return {
                    ok: true,
                    json: JSON.stringify(state.actions, null, 2),
                };
            default:
                return { ok: false, reason: "unknown command" };
        }
    }));
}

function endRecordingInTab(tabId) {
    return serialised(() => loadState().then((state) => {
        if (!state.recording || state.tabId !== tabId) {
            return undefined;
        }
        return saveState(Object.assign({}, state, { recording: false }));
    }));
}

function replyWithError(sendResponse, error) {
    console.error("handleMessage failed:", error);
    try {
        sendResponse({ ok: false, reason: String(error) });
    } catch (replyError) {
        // The message port may already be closed (popup dismissed
        // before reply). Log so the swallow is visible in devtools —
        // the original error is the one the caller actually cares about.
        console.debug("sendResponse failed:", replyError);
    }
}

if (typeof chrome !== "undefined" && chrome.runtime) {
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        // Returning true keeps the response channel open for async
        // work. The rejection handler keeps a failed dispatch from
        // dropping silently (ESLint
        // security-node/detect-unhandled-async-errors).
        dispatch(message, sender).then(
            sendResponse,
            (error) => replyWithError(sendResponse, error),
        );
        return true;
    });
}

if (typeof chrome !== "undefined" && chrome.tabs?.onRemoved) {
    // Closing the recorded tab ends the recording; its ID is never reused.
    chrome.tabs.onRemoved.addListener((tabId) => {
        endRecordingInTab(tabId).catch((error) => {
            console.error("ending the recording failed:", error);
        });
    });
}
