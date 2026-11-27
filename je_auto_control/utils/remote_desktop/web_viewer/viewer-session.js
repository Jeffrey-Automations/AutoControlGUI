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
