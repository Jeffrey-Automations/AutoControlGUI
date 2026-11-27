"""Run the browser extension's own scripts in the Qt JavaScript engine.

There is no Node or browser in the headless suite, so the extension's
``background.js``, ``content_script.js`` and ``popup.js`` are loaded into a
``QJSEngine`` next to fake ``chrome.*``, ``document`` and ``location``
objects, and driven from Python. The fakes are deliberately small: only what
the three scripts touch.

``chrome.storage.local`` is a double with two modes. In ``auto`` mode every
``get`` / ``set`` settles at once; in ``manual`` mode each one waits in
``__ext.pending`` until the test completes it, so a test chooses the order in
which storage operations finish. A ``get`` reads the stored data when it
completes and a ``set`` writes when it completes, as two overlapping calls on
a real extension can.

Promise jobs in ``QJSEngine`` run from the Qt event loop, one hop per pumped
round, so :meth:`ExtensionHarness.drain` pumps a fixed number of rounds.
"""
import json
from pathlib import Path

from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

EXT_DIR = Path(__file__).resolve().parents[3] / "browser-extension"
STATE_KEY = "autocontrol.recorder.state"
_DRAIN_ROUNDS = 200

_FAKES = r"""
var __ext = {
    data: {}, mode: "auto", pending: [], nextId: 0, failNextSet: false,
    outbox: [], replies: [], listeners: {}, downloads: [],
    activeTabs: [{ id: 7, url: "https://example.test/start" }],
};
function __copy(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}
__ext.settle = function (op) {
    if (op.kind === "get") {
        var out = {};
        if (Object.prototype.hasOwnProperty.call(__ext.data, op.key)) {
            out[op.key] = __copy(__ext.data[op.key]);
        }
        op.resolve(out);
    } else if (op.fail) {
        op.reject(new Error("storage write failed"));
    } else {
        Object.keys(op.items).forEach(function (key) { __ext.data[key] = op.items[key]; });
        op.resolve();
    }
};
__ext.storageOp = function (kind, arg) {
    return new Promise(function (resolve, reject) {
        var op = { kind: kind, id: __ext.nextId++, resolve: resolve, reject: reject };
        if (kind === "get") {
            op.key = arg;
        } else {
            op.items = __copy(arg);
            op.fail = __ext.failNextSet;
            __ext.failNextSet = false;
        }
        if (__ext.mode === "auto") { __ext.settle(op); } else { __ext.pending.push(op); }
    });
};
__ext.complete = function (index) {
    __ext.settle(__ext.pending.splice(index, 1)[0]);
};
__ext.deliver = function (message, tabId) {
    var index = __ext.replies.length;
    __ext.replies.push(null);
    var sender = tabId === null ? { id: "recorder" } : { id: "recorder", tab: { id: tabId } };
    __ext.listeners.message(__copy(message), sender, function (reply) {
        __ext.replies[index] = __copy(reply);
    });
    return index;
};
var chrome = {
    runtime: {
        onMessage: { addListener: function (fn) { __ext.listeners.message = fn; } },
        sendMessage: function (message, callback) {
            __ext.outbox.push(__copy(message));
            if (callback) { Promise.resolve().then(function () { callback({ ok: true }); }); }
        },
    },
    tabs: {
        onRemoved: { addListener: function (fn) { __ext.listeners.removed = fn; } },
        query: function () { return Promise.resolve(__copy(__ext.activeTabs)); },
    },
    storage: { local: {
        get: function (key) { return __ext.storageOp("get", key); },
        set: function (items) { return __ext.storageOp("set", items); },
    } },
    downloads: { download: function (options) { __ext.downloads.push(__copy(options)); } },
};

var __dom = { listeners: {}, reads: [], byId: {} };
var FakeElement = class {
    constructor(tag, attrs) {
        this.nodeType = 1;
        this.tagName = tag.toUpperCase();
        this.attrs = attrs || {};
        this.id = this.attrs.id || "";
        this.parentElement = null;
        this.children = [];
        this.textContent = "";
        this.handlers = {};
    }
    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
    }
    addEventListener(type, fn) { this.handlers[type] = fn; }
};
var HTMLInputElement = class extends FakeElement {
    constructor(attrs) { super("input", attrs); this.type = (this.attrs.type || "text").toLowerCase(); }
};
var HTMLTextAreaElement = class extends FakeElement {
    constructor(attrs) { super("textarea", attrs); this.type = "textarea"; }
};
var HTMLSelectElement = class extends FakeElement {
    constructor(attrs) { super("select", attrs); this.type = "select-one"; }
};
__dom.field = function (kind, attrs, value) {
    var classes = { input: HTMLInputElement, textarea: HTMLTextAreaElement, select: HTMLSelectElement };
    var element = new classes[kind](attrs);
    Object.defineProperty(element, "value", { get: function () {
        __dom.reads.push(element.id || element.getAttribute("name") || kind);
        return value;
    } });
    return element;
};
__dom.fire = function (type, target) {
    (__dom.listeners[type] || []).forEach(function (fn) { fn({ type: type, target: target }); });
};
__dom.click = function (id) { __dom.byId[id].handlers.click({ type: "click" }); };
var document = {
    documentElement: new FakeElement("html"),
    addEventListener: function (type, fn) {
        (__dom.listeners[type] = __dom.listeners[type] || []).push(fn);
    },
    getElementById: function (id) {
        if (!__dom.byId[id]) { __dom.byId[id] = new FakeElement("button", { id: id }); }
        return __dom.byId[id];
    },
};
var location = { href: "https://example.test/login" };
function addEventListener() {}
"""


class ExtensionHarness:
    """One ``QJSEngine`` holding the fakes and whichever extension scripts a test loads."""

    def __init__(self) -> None:
        self._app = QApplication.instance() or QApplication([])
        self._engine = QJSEngine()
        self._engine.installExtensions(QJSEngine.Extension.ConsoleExtension)
        global_object = self._engine.globalObject()
        global_object.setProperty("globalThis", global_object)
        self._modules = []
        self.run(_FAKES, "<fakes>")

    def run(self, source: str, name: str = "<test>"):
        """Evaluate ``source``; raise with the engine's message when it throws."""
        result = self._engine.evaluate(source, name)
        if result.isError():
            raise AssertionError(f"{name}: {result.toString()}")
        return result

    def value(self, expression: str):
        """The JSON-decoded value of ``expression`` (``None`` for undefined or null)."""
        result = self.run(f"JSON.stringify({expression})")
        return None if result.isUndefined() else json.loads(result.toString())

    def drain(self) -> None:
        """Pump the event loop until queued promise jobs have run."""
        for _ in range(_DRAIN_ROUNDS):
            self._app.processEvents()

    def load_background(self) -> None:
        """Import ``background.js`` as the ES module the manifest declares."""
        module = self._engine.importModule(str(EXT_DIR / "background.js"))
        if module.isError():
            raise AssertionError(f"background.js: {module.toString()}")
        self._modules.append(module)
        self.drain()

    def load_script(self, name: str) -> None:
        """Evaluate a classic script (the content script or the popup)."""
        path = EXT_DIR / name
        self.run(path.read_text(encoding="utf-8"), str(path))
        self.drain()

    def send(self, message: dict, tab_id: int | None = None) -> int:
        """Deliver ``message`` to the background listener, as if sent from ``tab_id``; return its reply slot."""
        return self.run(f"__ext.deliver({json.dumps(message)}, {json.dumps(tab_id)})").toInt()

    def reply(self, slot: int):
        """The reply the background sent for ``slot``, or ``None`` while it has not answered."""
        return self.value(f"__ext.replies[{slot}]")

    def request(self, message: dict, tab_id: int | None = None):
        """Send ``message``, let it finish, and return the reply."""
        slot = self.send(message, tab_id)
        self.drain()
        return self.reply(slot)

    def stored_state(self):
        """The recorder state as ``chrome.storage.local`` holds it."""
        return self.value(f"__ext.data[{json.dumps(STATE_KEY)}]")

    def manual_storage(self) -> None:
        """From now on, storage operations wait for :meth:`complete`."""
        self.run('__ext.mode = "manual"')

    def pending(self) -> list:
        """The kinds (``get`` / ``set``) of the storage operations waiting once queued jobs have run, oldest first."""
        self.drain()
        return self.value("__ext.pending.map(function (op) { return op.kind; })")

    def complete(self, index: int) -> None:
        """Let the waiting storage operation at ``index`` finish."""
        self.run(f"__ext.complete({int(index)})")
        self.drain()
