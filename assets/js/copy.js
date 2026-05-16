(function () {
  var COPY_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
  var CHECK_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';

  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (e) {
        reject(e);
      } finally {
        document.body.removeChild(ta);
      }
    });
  }

  function flash(btn) {
    btn.innerHTML = CHECK_SVG;
    btn.setAttribute("data-copied", "true");
    btn.setAttribute("aria-label", "Copied");
    setTimeout(function () {
      btn.innerHTML = COPY_SVG;
      btn.removeAttribute("data-copied");
      btn.setAttribute("aria-label", "Copy code");
    }, 1500);
  }

  // Wrap each <pre> in a div with a copy button.
  document.querySelectorAll("pre").forEach(function (pre) {
    if (pre.parentElement.classList.contains("pre-wrap")) return;
    var wrap = document.createElement("div");
    wrap.className = "pre-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.setAttribute("aria-label", "Copy code");
    btn.innerHTML = COPY_SVG;
    btn.addEventListener("click", function () {
      var code = pre.querySelector("code");
      var text = (code ? code.innerText : pre.innerText).replace(/\n$/, "");
      copy(text).then(function () { flash(btn); });
    });
    wrap.appendChild(btn);
  });

  // Standalone install-pill copy button.
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sel = btn.getAttribute("data-copy");
      var target = sel ? document.querySelector(sel) : null;
      var text = target ? target.innerText : btn.previousElementSibling?.innerText;
      if (!text) return;
      copy(text.trim()).then(function () { flash(btn); });
    });
  });
})();
