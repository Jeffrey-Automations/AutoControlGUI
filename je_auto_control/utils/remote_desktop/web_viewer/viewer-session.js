// Session plumbing for the web viewer, kept free of the DOM so the headless
// test suite can evaluate it in Qt's JavaScript engine (QJSEngine). That
// engine has no async functions, optional catch bindings or object spread,
// so this file sticks to promises, `catch (err)` and Object.assign.
"use strict";

// Hands an inbound data channel to the route registered for its exact label
// and reports whether one was. The host also offers channels this page does
// not speak (usb, whether or not passthrough is on); those stay unbound, so
// a channel arriving late can never replace the control channel.
function routeDataChannel(channel, routes) {
  const label = channel.label;
  if (!Object.prototype.hasOwnProperty.call(routes, label)) return false;
  routes[label](channel);
  return true;
}

// Closes a channel, peer connection or audio context that may already be
// closed or missing; teardown runs from every failure path.
function closeQuietly(target) {
  if (!target) return;
  try {
    target.close();
  } catch (err) {
    // already closed: nothing left to release
  }
}

function stopTracks(stream) {
  if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
}

// The MediaStreams this page captured, by name, so a disconnect stops them
// all in one call. A permission prompt can outlive the session that opened
// it: acquire() stops a stream granted after releaseAll(), or one granted
// while the name is already held, and resolves to null instead.
function createLocalMedia() {
  const held = {};
  let session = 0;
  const media = {
    acquire: function (name, request) {
      const askedIn = session;
      return request().then(function (stream) {
        if (askedIn !== session || held[name]) {
          stopTracks(stream);
          return null;
        }
        held[name] = stream;
        return stream;
      });
    },
    get: function (name) { return held[name] || null; },
    release: function (name) {
      const stream = held[name] || null;
      delete held[name];
      stopTracks(stream);
      return stream;
    },
    releaseAll: function () {
      session += 1;
      Object.keys(held).forEach(media.release);
    },
  };
  return media;
}

// Input in the host's dispatcher protocol (utils/remote_desktop/input_dispatch.py),
// the one the native viewer speaks too: payload.action names the call, and
// text is the "type" action with a "text" field.
const MOUSE_BUTTONS = ["mouse_left", "mouse_middle", "mouse_right"];

function inputMessage(action, fields) {
  return { type: "input", payload: Object.assign({ action: action }, fields) };
}

function buttonMessage(action, coords, buttonIndex) {
  return inputMessage(action, {
    x: coords[0], y: coords[1], button: MOUSE_BUTTONS[buttonIndex] || "mouse_left",
  });
}

function wheelMessage(coords, deltaY) {
  return inputMessage("mouse_scroll", { x: coords[0], y: coords[1], amount: -Math.sign(deltaY) * 3 });
}

// A key that produces one character is typed; any other key sends nothing.
function keyMessage(key) {
  return key.length === 1 ? inputMessage("type", { text: key }) : null;
}
