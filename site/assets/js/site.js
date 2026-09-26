/*!
 * Two Squares — site chrome. Runs on every page, after motion.js.
 * Header states · overlay nav · cursor · preloader · lazy images · ambient
 * video manager · toast · copy-to-clipboard · prefetch.
 * Everything here works without motion (reduced motion, or GSAP failed to load):
 * motion-only parts are registered with Motion.global() and receive env.motion.
 */
(function (w, d) {
  "use strict";
  const root = d.documentElement;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const reduce = () => w.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = () => w.matchMedia("(hover: hover) and (pointer: fine)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
    sget(k) { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    sset(k, v) { try { sessionStorage.setItem(k, v); } catch (_) {} },
  };
  const TS = (w.TS = w.TS || {});
  TS.store = store;

  /* ---------------------------------------------------------------- nav: current page */
  (function markCurrent() {
    const here = location.pathname.replace(/index\.html$/, "").replace(/\/$/, "") || "/";
    $$(".site-header__nav a[href], .nav-overlay a[href]").forEach((a) => {
      const u = new URL(a.getAttribute("href"), location.href);
      const p = u.pathname.replace(/index\.html$/, "").replace(/\/$/, "") || "/";
      const section = d.body.dataset.section;           // e.g. "work" on case studies
      if (p === here || (section && a.dataset.section === section)) a.setAttribute("aria-current", "page");
    });
  })();

  /* ---------------------------------------------------------------- lazy images: fade in on decode */
  function wireImages(scope = d) {
    $$(".media > img, .media > picture > img", scope).forEach((img) => {
      if (img.dataset.wired) return;
      img.dataset.wired = "1";
      const done = () => img.classList.add("is-loaded");
      if (img.complete && img.naturalWidth) done();
      else { img.addEventListener("load", done, { once: true }); img.addEventListener("error", done, { once: true }); }
    });
  }
  TS.wireImages = wireImages;
  wireImages();

  /* ---------------------------------------------------------------- toast */
  let toastEl, toastTimer;
  TS.toast = (msg) => {
    if (!toastEl) { toastEl = d.createElement("div"); toastEl.className = "toast"; toastEl.setAttribute("role", "status"); toastEl.setAttribute("aria-live", "polite"); d.body.appendChild(toastEl); }
    toastEl.textContent = msg;
    requestAnimationFrame(() => toastEl.classList.add("is-in"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-in"), 2400);
  };

  /* ---------------------------------------------------------------- copy to clipboard: [data-copy="text"] */
  d.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault();
    const text = b.dataset.copy;
    const ok = () => TS.toast(b.dataset.copied || "Copied");
    if (navigator.clipboard && w.isSecureContext) navigator.clipboard.writeText(text).then(ok, () => fallback());
    else fallback();
    function fallback() {
      const t = d.createElement("textarea"); t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
      d.body.appendChild(t); t.select(); try { d.execCommand("copy"); ok(); } catch (_) { location.href = "mailto:" + text; } t.remove();
    }
  });

  /* ---------------------------------------------------------------- prefetch internal pages on intent */
  (function prefetch() {
    const seen = new Set();
    const go = (a) => {
      if (!a || a.target === "_blank") return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || u.pathname === location.pathname || seen.has(u.pathname)) return;
      seen.add(u.pathname);
      const l = d.createElement("link"); l.rel = "prefetch"; l.href = u.pathname; d.head.appendChild(l);
    };
    d.addEventListener("pointerover", (e) => go(e.target.closest && e.target.closest("a[href]")), { passive: true });
    d.addEventListener("focusin", (e) => go(e.target.closest && e.target.closest("a[href]")));
  })();

  /* ---------------------------------------------------------------- overlay nav (works without motion) */
  (function overlay() {
    const ov = $(".nav-overlay"), toggle = $(".nav-toggle");
    if (!ov || !toggle) return;
    const close = $(".nav-overlay__close", ov);
    let lastFocus = null;
    const focusables = () => $$('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])', ov).filter((el) => el.offsetParent !== null);
    function open() {
      const r = toggle.getBoundingClientRect();
      ov.style.setProperty("--ox", ((r.left + r.width / 2) / innerWidth) * 100 + "%");
      ov.style.setProperty("--oy", ((r.top + r.height / 2) / innerHeight) * 100 + "%");
      lastFocus = d.activeElement;
      ov.hidden = false; ov.removeAttribute("inert");
      requestAnimationFrame(() => ov.classList.add("is-open"));
      toggle.setAttribute("aria-expanded", "true");
      root.classList.add("nav-open");
      w.Motion && w.Motion.stop && w.Motion.stop();
      if (w.gsap && !reduce()) {
        w.gsap.fromTo($$(".nav-overlay__link span, .nav-overlay__foot > *", ov), { yPercent: 60, autoAlpha: 0 },
          { yPercent: 0, autoAlpha: 1, duration: 0.9, ease: w.Motion && w.Motion.DRIFT || "power3.out", stagger: 0.06, delay: 0.25 });
      }
      setTimeout(() => (focusables()[0] || close).focus({ preventScroll: true }), 60);
    }
    function shut() {
      ov.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
      root.classList.remove("nav-open");
      ov.setAttribute("inert", "");
      w.Motion && w.Motion.start && w.Motion.start();
      if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
    }
    TS.closeNav = shut;
    ov.setAttribute("inert", "");
    toggle.addEventListener("click", () => (ov.classList.contains("is-open") ? shut() : open()));
    close && close.addEventListener("click", shut);
    ov.addEventListener("click", (e) => { const a = e.target.closest("a[href]"); if (a && new URL(a.href).pathname === location.pathname) shut(); });
    d.addEventListener("keydown", (e) => {
      if (!ov.classList.contains("is-open")) return;
      if (e.key === "Escape") { e.preventDefault(); shut(); }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    w.addEventListener("resize", () => { if (innerWidth > 900 && ov.classList.contains("is-open")) shut(); });
  })();

  /* ---------------------------------------------------------------- header states (scroll position only; no layout reads per frame) */
  (function header() {
    const h = $(".site-header");
    if (!h) return;
    const firstDark = d.querySelector("main > [data-header='dark']:first-child, main > :first-child[data-header='dark']");
    let lastY = w.scrollY, ticking = false, forced = 0;
    const heroH = () => (firstDark ? firstDark.offsetHeight : 0);
    let heroBottom = heroH();
    w.addEventListener("resize", () => { heroBottom = heroH(); }, { passive: true });
    function update() {
      ticking = false;
      const y = w.scrollY;
      const overDark = firstDark && y < heroBottom - h.offsetHeight;
      root.dataset.headerOver = overDark ? "dark" : "light";
      h.classList.toggle("is-solid", y > 80 && !overDark);
      const dy = y - lastY;
      if (!root.classList.contains("nav-open")) {
        if (forced > 0) h.classList.add("is-hidden");
        else if (y > innerHeight * 0.3 && dy > 8) h.classList.add("is-hidden");
        else if (dy < -8 || y < innerHeight * 0.3) h.classList.remove("is-hidden");
      }
      if (Math.abs(dy) > 8 || y < 10) lastY = y;
    }
    // sections can force the header out of the way (e.g. the pinned walk)
    TS.hideHeader = (on) => { forced = Math.max(0, forced + (on ? 1 : -1)); update(); };
    w.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    h.addEventListener("focusin", () => h.classList.remove("is-hidden"));
    update();
  })();

  /* ---------------------------------------------------------------- ambient video manager: <video data-autoplay data-src="base" [data-src-sm="base-sm"]> */
  const pickExt = (v) => {
    const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
    return !isSafari && v.canPlayType('video/webm; codecs="vp9"') === "probably" ? "webm" : "mp4";
  };
  TS.pickVideoSrc = (v) => {
    const small = w.matchMedia("(max-width: 900px)").matches && v.dataset.srcSm;
    const base = small ? v.dataset.srcSm : v.dataset.src;
    if (small && v.dataset.posterSm) v.poster = v.dataset.posterSm;
    return base + "." + pickExt(v);
  };
  (function videos() {
    const vids = $$("video[data-autoplay]");
    if (!vids.length) return;
    const setSrc = (v) => {
      if (v.dataset.loaded) return;
      v.dataset.loaded = "1";
      v.muted = true; v.playsInline = true; v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
      v.src = TS.pickVideoSrc(v);
      v.addEventListener("error", () => v.classList.add("is-failed"), { once: true });
    };
    const play = (v) => {
      if (reduce() || v.dataset.paused === "user") return;
      setSrc(v);
      const p = v.play(); if (p && p.catch) p.catch(() => {});
    };
    const near = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) setSrc(e.target); }), { rootMargin: "100% 0px 100% 0px" });
    const vis = new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? play(e.target) : e.target.pause())), { threshold: 0.15 });
    vids.forEach((v) => {
      if (v.hasAttribute("data-eager")) setSrc(v);
      near.observe(v); vis.observe(v);
    });
    d.addEventListener("visibilitychange", () => vids.forEach((v) => (d.hidden ? v.pause() : null)));
    // pause/play toggles: <button data-video-toggle="#id">
    $$("[data-video-toggle]").forEach((b) => {
      const v = $(b.dataset.videoToggle); if (!v) return;
      const sync = () => { b.setAttribute("aria-pressed", String(v.paused)); b.querySelector(".sr-only") && (b.querySelector(".sr-only").textContent = v.paused ? "Play video" : "Pause video"); };
      b.addEventListener("click", () => { if (v.paused) { v.dataset.paused = ""; setSrc(v); v.play().catch(() => {}); } else { v.dataset.paused = "user"; v.pause(); } });
      v.addEventListener("play", sync); v.addEventListener("pause", sync); sync();
    });
  })();

  /* ---------------------------------------------------------------- footer year */
  $$("[data-year]").forEach((el) => (el.textContent = new Date().getFullYear()));

  /* ================================================================ motion-only chrome */
  const M = w.Motion;
  if (!M || !M.global) return;

  // the preloader must hold intros that are already on screen
  const pre = $(".preloader");
  const runPreloader = pre && !root.classList.contains("no-preload") && !reduce();
  if (runPreloader) M.config.introDelay = 1.25;

  M.global((env) => {
    const gsap = w.gsap;
    const offs = [];

    /* ---- preloader: logo wipes in, label rises, the panel lifts (≤1.4s, any input skips) */
    if (pre) {
      if (!env.motion || root.classList.contains("no-preload")) { pre.remove(); }
      else {
        store.sset("ts-intro", "1");
        const logo = $(".logo", pre), label = $(".t-label", pre);
        const tl = gsap.timeline({ onComplete: () => pre.remove() });
        tl.to(logo, { clipPath: "inset(0 0% 0 0)", duration: 0.75, ease: "ts.cut" })
          .to(label, { autoAlpha: 1, y: 0, duration: 0.45, ease: "ts.out" }, "-=0.25")
          .to(pre, { clipPath: "inset(0 0 100% 0)", duration: 0.7, ease: "ts.cut" }, "+=0.12");
        const skip = () => { if (tl.progress() < 1) tl.progress(1); };
        ["wheel", "touchstart", "keydown", "pointerdown"].forEach((ev) => w.addEventListener(ev, skip, { once: true, passive: true }));
      }
    }

    /* ---- cursor (fine pointers only): a ring lerped to the pointer; [data-cursor="Label"] grows it */
    if (env.fine) {
      const c = d.createElement("div");
      c.className = "cursor"; c.setAttribute("aria-hidden", "true");
      c.innerHTML = '<span class="cursor__label"></span>';
      d.body.appendChild(c);
      const label = $(".cursor__label", c);
      const xTo = gsap.quickTo(c, "x", { duration: 0.35, ease: "power3" });
      const yTo = gsap.quickTo(c, "y", { duration: 0.35, ease: "power3" });
      let shown = false;
      const move = (e) => {
        if (e.pointerType && e.pointerType !== "mouse") return;
        xTo(e.clientX); yTo(e.clientY);
        if (!shown) { shown = true; gsap.set(c, { x: e.clientX, y: e.clientY }); c.classList.add("is-visible"); }
      };
      const over = (e) => {
        const t = e.target;
        const lab = t.closest && t.closest("[data-cursor]");
        const hide = t.closest && t.closest("input, textarea, select, iframe, [data-cursor='none']");
        c.classList.toggle("is-hidden", !!hide);
        if (lab && lab.dataset.cursor && lab.dataset.cursor !== "none") { label.textContent = lab.dataset.cursor; c.classList.add("is-label"); }
        else c.classList.remove("is-label");
      };
      const leave = () => c.classList.remove("is-visible");
      const enter = () => shown && c.classList.add("is-visible");
      w.addEventListener("pointermove", move, { passive: true });
      d.addEventListener("pointerover", over, { passive: true });
      d.documentElement.addEventListener("pointerleave", leave);
      d.documentElement.addEventListener("pointerenter", enter);
      offs.push(() => { w.removeEventListener("pointermove", move); d.removeEventListener("pointerover", over); c.remove(); });
    }

    /* ---- overlay shapes drift slowly (only while the overlay is open is it visible, but it's cheap) */
    $$(".nav-overlay__shape").forEach((s, i) => {
      const tw = gsap.to(s, { x: i ? 24 : -30, y: i ? -18 : 22, rotation: "+=6", duration: 9 + i * 3, ease: "sine.inOut", yoyo: true, repeat: -1 });
      offs.push(() => tw.kill());
    });

    return () => offs.forEach((f) => f());
  });
})(window, document);
