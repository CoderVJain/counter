// The app half of the MCP Apps postMessage dialect, shared by all three cards.
//
// A host renders a card in a sandboxed iframe and speaks JSON-RPC to it over postMessage. What a
// read-only card needs is short:
//
//   card -> host   ui/initialize                  (request)
//   host -> card   result: hostInfo, hostContext
//   card -> host   ui/notifications/initialized
//   host -> card   ui/notifications/tool-result   { content, structuredContent }
//   card -> host   ui/notifications/size-changed  { width, height }
//
// Nothing else is implemented, on purpose. These cards read; they never call a tool back, so
// tools/call, resources/read and the display-mode requests would all be dead code.
//
// Each card document defines its own render(data) and this calls it once the result arrives.

(function () {
  "use strict";

  var PROTOCOL_VERSION = "2026-01-26";
  var INITIALIZE_ID = 1;

  function send(message) {
    message.jsonrpc = "2.0";
    parent.postMessage(message, "*");
  }

  // The host sizes the iframe from this, so a card that renders and stays silent is a clipped card.
  function reportSize() {
    send({
      method: "ui/notifications/size-changed",
      params: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      },
    });
  }

  // The spec asks a card to keep reporting its size, and a first measurement taken before layout
  // settles is wrong in a way nobody notices until a card is clipped in front of an audience.
  if (window.ResizeObserver) {
    new ResizeObserver(reportSize).observe(document.documentElement);
  }

  window.addEventListener("message", function (event) {
    var message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;

    if (message.id === INITIALIZE_ID && message.result) {
      send({ method: "ui/notifications/initialized" });
      return;
    }

    if (message.method === "ui/notifications/tool-result") {
      render((message.params && message.params.structuredContent) || {});
      reportSize();
    }
  });

  send({
    id: INITIALIZE_ID,
    method: "ui/initialize",
    params: {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "counter-card", version: "0.1.0" },
      appCapabilities: { availableDisplayModes: ["inline"] },
    },
  });
})();
