/* eslint-env webextensions, browser */
// Popup UI — talks to the background service worker via runtime
// messages. No DOM crawling here; selectors come from content_script.
// Promise chains rather than async / await: the headless suite runs this
// file in the Qt JavaScript engine, which does not parse the latter.

function send(command, extra) {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage(Object.assign({ command }, extra), (reply) => {
            resolve(reply || {});
        });
    });
}

function refresh() {
    return send("status").then((reply) => {
        const state = reply.state || {};
        document.getElementById("state").textContent =
            state.recording ? "recording" : "idle";
        document.getElementById("count").textContent =
            String((state.actions || []).length);
    });
}

// Every handler ends in a logged rejection handler so a failed promise
// can't drop silently (ESLint security-node/detect-unhandled-async-errors).
function logFailure(error) {
    console.error("popup action failed:", error);
}

function safeRefresh() {
    refresh().catch(logFailure);
}

function startRecording() {
    // The background records only this tab, by ID, so events from other
    // tabs never join this recording.
    return chrome.tabs.query({ active: true, currentWindow: true })
        .then((tabs) => {
            const tab = tabs[0];
            return send("start", { startUrl: tab?.url, tabId: tab?.id });
        });
}

function downloadExport() {
    return send("export").then((reply) => {
        if (!reply.ok) { return; }
        const blob = new Blob([reply.json || "[]"], {
            type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        chrome.downloads.download({
            url,
            filename: "autocontrol-recording.json",
            saveAs: true,
        });
    });
}

document.getElementById("start").addEventListener("click", () => {
    startRecording().then(safeRefresh, logFailure);
});

document.getElementById("stop").addEventListener("click", () => {
    send("stop").then(safeRefresh, logFailure);
});

document.getElementById("reset").addEventListener("click", () => {
    send("reset").then(safeRefresh, logFailure);
});

document.getElementById("export").addEventListener("click", () => {
    downloadExport().catch(logFailure);
});

// Kick off the initial refresh — safeRefresh() logs any failure.
safeRefresh();
