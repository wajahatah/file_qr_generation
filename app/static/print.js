"use strict";
// Opens the print dialog once the QR image has loaded -- printing before it loads
// would give a blank square. Inactive QR codes are never printed automatically.
(function () {
  const img = document.getElementById("print-qr");
  const live = document.body.dataset.live === "1";
  document.getElementById("print-btn").addEventListener("click", () => window.print());
  if (!live) return;
  if (img.complete && img.naturalWidth > 0) window.print();
  else img.addEventListener("load", () => window.print(), { once: true });
})();
