/*!
 * Two Squares — the header's Sectors disclosure (partials/header.html, styles in nav.css).
 * A button that shows / hides a small panel of the four sector pages. Disclosure pattern:
 * focus stays on the button when it opens, Tab walks into the panel; Esc closes it and returns
 * focus to the button; a click outside, tabbing out, scrolling on, or the header going mobile closes it.
 * Plain JS, no motion engine needed (the panel's fade is CSS; reduced motion makes it instant).
 */
(function (w, d) {
  "use strict";
  const box = d.querySelector("[data-nav-sectors]");
  if (!box) return;
  const btn = box.querySelector(".nav-sectors__toggle");
  const panel = box.querySelector(".nav-sectors__panel");
  if (!btn || !panel) return;
  let open = false, y0 = 0, hideTimer = 0;

  // the thumbnails load on intent (hover / focus of the button), so they're ready when it opens
  const warm = () => panel.querySelectorAll('img[loading="lazy"]').forEach((i) => { i.loading = "eager"; });

  function show() {
    if (open) return;
    open = true;
    clearTimeout(hideTimer);
    warm();
    panel.hidden = false;
    void panel.offsetWidth;                        // commit the closed state so the fade runs
    box.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
    y0 = w.scrollY;
    d.addEventListener("pointerdown", outside, true);
    w.addEventListener("scroll", onScroll, { passive: true });
  }
  function hide(returnFocus) {
    if (!open) return;
    open = false;
    box.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
    d.removeEventListener("pointerdown", outside, true);
    w.removeEventListener("scroll", onScroll);
    hideTimer = setTimeout(() => { if (!open) panel.hidden = true; }, 360);
    if (returnFocus) btn.focus({ preventScroll: true });
  }
  function outside(e) { if (!box.contains(e.target)) hide(false); }
  function onScroll() { if (Math.abs(w.scrollY - y0) > 80) hide(false); }

  btn.addEventListener("click", () => (open ? hide(false) : show()));
  btn.addEventListener("pointerenter", warm, { once: true });
  btn.addEventListener("focus", warm, { once: true });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); hide(true); }
  });
  box.addEventListener("focusout", (e) => {
    if (open && e.relatedTarget && !box.contains(e.relatedTarget)) hide(false);
  });
  const mobile = w.matchMedia("(max-width: 900px)");
  const onMq = () => { if (mobile.matches) hide(false); };
  mobile.addEventListener ? mobile.addEventListener("change", onMq) : mobile.addListener(onMq);
  // history back into a page with the panel open (bfcache): start closed
  w.addEventListener("pageshow", (e) => { if (e.persisted) { hide(false); panel.hidden = true; } });
  w.TS = w.TS || {};
  w.TS.closeSectors = () => hide(false);
})(window, document);
