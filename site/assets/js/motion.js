/*!
 * Two Squares — motion core (v1.1, verified with gsap 3.15.0 + lenis 1.3.26)
 *
 * ONE module owns: Lenis (smooth wheel) · gsap.ticker (the only rAF loop) ·
 * ScrollTrigger · SplitText · reduced-motion switching · page registry ·
 * data-attribute effects · refresh strategy · page-transition fallback.
 *
 * Load order (every tag `defer`, so execution order = document order):
 *   gsap → ScrollTrigger → SplitText → [Flip, CustomEase] → lenis → motion.js → [scrub.js] → page script
 * Page scripts register with   Motion.page("home", (env) => { ...; return cleanup })
 * Custom effects register with Motion.effect("name", (el, env) => { ...; return cleanup })
 * and are applied to every [data-name] element.
 */
(function (w, d) {
  "use strict";
  const root = d.documentElement;
  const gsap = w.gsap, ST = w.ScrollTrigger, SplitText = w.SplitText;
  const Motion = (w.Motion = w.Motion || {});
  Motion.version = "1.0.0";
  Motion.effects = Motion.effects || {};
  Motion.pages = Motion.pages || {};
  Motion.lenis = null;
  Motion.booted = false;
  // page-level overrides, set before DOMContentLoaded: Motion.config = { lenis: {...}, anchors: false }
  Motion.config = Object.assign({ lenis: {}, anchors: true }, Motion.config || {});
  Motion.effect = (name, fn) => { Motion.effects[name] = fn; };
  Motion.page = (name, fn) => { Motion.pages[name] = fn; };
  // site-wide inits (header, cursor, overlay …) that must run on every page, before the page init
  Motion.globals = Motion.globals || [];
  Motion.global = (fn) => { Motion.globals.push(fn); };

  // Fail open: if GSAP did not load, drop the pre-states so everything is visible.
  if (!gsap || !ST) {
    root.classList.remove("js-motion", "curtain-in");
    root.classList.add("motion-failed");
    return;
  }

  gsap.registerPlugin(...[ST, SplitText, w.Flip, w.CustomEase].filter(Boolean));
  // iOS: showing/hiding the URL bar fires resize; don't re-measure every trigger for it.
  ST.config({ ignoreMobileResize: true });
  if (w.CustomEase) {
    w.CustomEase.create("ts.out", "0.16, 1, 0.3, 1");     // house "settle" ease
    w.CustomEase.create("ts.inOut", "0.65, 0, 0.35, 1");
    w.CustomEase.create("ts.drift", "M0,0 C0.65,0 0,1.04 1,1");   // reveals: slow start, fast finish, tiny overshoot
    w.CustomEase.create("ts.cut", "0.7, 0, 0.2, 1");                // wipes, overlays
  }
  const EASE = w.CustomEase ? "ts.out" : "expo.out";
  const DRIFT = w.CustomEase ? "ts.drift" : "power3.out";
  Motion.EASE = EASE; Motion.DRIFT = DRIFT;
  gsap.defaults({ duration: 1, ease: EASE });

  const MQ = {
    motion: "(prefers-reduced-motion: no-preference)",
    reduce: "(prefers-reduced-motion: reduce)",
    fine: "(hover: hover) and (pointer: fine)",
  };

  // ------------------------------------------------------------------ Lenis
  // Created on every device when motion is allowed. syncTouch stays false, so
  // touch scrolling is 100% native (momentum, rubber-band, URL bar); Lenis only
  // smooths wheel input and gives us one scrollTo/stop/start API.
  function startLenis() {
    if (!w.Lenis) return null;
    const lenis = new w.Lenis(Object.assign({
      lerp: 0.1,
      smoothWheel: true,
      syncTouch: false,
      autoRaf: false,                 // gsap.ticker drives it: ONE rAF loop for everything
      anchors: false,                 // we handle same-page anchors ourselves (see onAnchorClick)
      stopInertiaOnNavigate: true,
      allowNestedScroll: true,        // overflow:auto panels (menu, rails) scroll natively
    }, Motion.config.lenis));
    Motion.lenis = lenis;
    lenis.on("scroll", ST.update);
    const raf = (time) => lenis.raf(time * 1000);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(raf);
      gsap.ticker.lagSmoothing(500, 33);
      lenis.destroy();
      Motion.lenis = null;
    };
  }

  // Same-page anchors: preventDefault + one smooth scroll + pushState. (Lenis's
  // own `anchors` option lets the native jump happen first; see SPEC pitfalls.)
  function onAnchorClick(e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest && e.target.closest('a[href*="#"]');
    if (!a) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || url.pathname !== location.pathname || !url.hash) return;
    const id = decodeURIComponent(url.hash.slice(1));
    const target = id === "top" ? d.body : d.getElementById(id);
    if (!target) return;
    e.preventDefault();
    Motion.scrollTo(target);
    history.pushState(null, "", url.hash);
    // move focus for keyboard / screen-reader users without a second scroll
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }

  // Offsets come from CSS only: `html { scroll-padding-top: var(--nav-h) }`.
  // Lenis.scrollTo(element) reads scroll-padding-top + scroll-margin-top, and so
  // does the browser's native anchor/focus/scrollIntoView — ONE source of truth.
  // (Passing a JS offset as well doubled it: landed 128px instead of 64px.)
  Motion.scrollTo = (target, opts = {}) => {
    if (Motion.lenis) {
      // Chrome's scroll anchoring can move window.scrollY after a layout change above the
      // viewport without Lenis hearing about it; resync first or the jump lands short
      const L = Motion.lenis;
      if (Math.abs(L.animatedScroll - w.scrollY) > 1) L.scrollTo(w.scrollY, { immediate: true, force: true });
      return L.scrollTo(target, opts);
    }
    const reduce = w.matchMedia(MQ.reduce).matches;
    const behavior = opts.immediate || reduce ? "instant" : "smooth";
    if (typeof target === "number") w.scrollTo({ top: target + (opts.offset || 0), behavior });
    else target.scrollIntoView({ block: "start", behavior });
  };
  // modal / menu open: freeze scroll without layout jump
  Motion.stop = () => { Motion.lenis ? Motion.lenis.stop() : (root.style.overflow = "clip"); };
  Motion.start = () => { Motion.lenis ? Motion.lenis.start() : (root.style.overflow = ""); };

  // Elements already on screen at boot wait for the page transition to uncover
  // them (cross-doc VT: the new page is wiped in over ~0.7 s; JS curtain: ~0.75 s),
  // otherwise their intro plays unseen underneath the transition.
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; };
  Motion.introDelay = 0;
  const introDelayFor = (el) => (Motion.booting && inView(el) ? Motion.introDelay : 0);

  // ------------------------------------------------------------------ effects
  // All effects: transform/opacity/clip-path only; every ScrollTrigger is created
  // inside the gsap.matchMedia() context so revert/cleanup is automatic.

  // data-reveal  → fade + rise once when it enters
  // data-reveal="image" → clip-path inset curtain + inner image settle (for .media figures)
  // data-reveal-group on a parent staggers its [data-reveal] children by 60ms in DOM order
  Motion.effect("reveal", (el) => {
    const isImage = el.dataset.reveal === "image";
    const img = isImage && el.querySelector(":scope > img, :scope > picture > img, :scope > video");
    // no layout (inside display:none — tabs, accordions, filtered lists): a once-trigger here
    // would measure 0/0, fire and kill itself mid-refresh (ScrollTrigger throws) → just show it
    if (!el.getClientRects().length) return revealNow(el);
    const group = el.parentElement && el.parentElement.closest("[data-reveal-group]");
    const idx = group ? [...group.querySelectorAll(":scope [data-reveal]")].indexOf(el) : 0;
    const delay = (parseFloat(el.dataset.delay) || 0) + introDelayFor(el) + Math.max(0, idx) * 0.06;
    const st = () => ({ trigger: el, start: "top 88%", once: true });
    if (isImage) {
      // two tweens, not a timeline: a timeline's ScrollTrigger refreshes lazily, and a page that
      // boots scrolled down (history back) then threw inside ScrollTrigger when `once` killed it
      gsap.fromTo(el, { clipPath: "inset(8% 8% 8% 8%)" }, { clipPath: "inset(0% 0% 0% 0%)", duration: 1.2, ease: DRIFT, delay,
        scrollTrigger: st(), onComplete: () => { gsap.set(el, { clipPath: "none" }); el.setAttribute("data-revealed", ""); } });
      if (img) gsap.fromTo(img, { scale: 1.12 }, { scale: 1, duration: 1.4, ease: EASE, delay, scrollTrigger: st() });
      return;
    }
    gsap.fromTo(el, { opacity: 0, y: 24 }, {
      opacity: 1, y: 0, duration: 1, ease: DRIFT, delay,
      clearProps: "transform",
      onComplete: () => el.setAttribute("data-revealed", ""),
      scrollTrigger: st(),
    });
  });
  function revealNow(el) {
    el.setAttribute("data-revealed", "");
    gsap.set(el, el.dataset.reveal === "image" ? { clipPath: "none" } : { opacity: 1 });
  }

  // data-count="64" [data-count-suffix="+"] → counts up once in view (tabular numerals)
  Motion.effect("count", (el) => {
    const end = parseFloat(el.dataset.count) || 0, dec = (el.dataset.count.split(".")[1] || "").length;
    const suffix = el.dataset.countSuffix || "", o = { v: 0 };
    const fmt = (v) => v.toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suffix;
    el.textContent = fmt(0);
    gsap.to(o, { v: end, duration: 1.6, ease: "power2.out", delay: introDelayFor(el),
      scrollTrigger: { trigger: el, start: "top 90%", once: true },
      onUpdate: () => { el.textContent = fmt(o.v); } });
  });

  // data-split[="lines"]  → masked line reveal; re-splits on font load / width change
  Motion.effect("split", (el) => {
    if (!SplitText || !el.getClientRects().length) { gsap.set(el, { opacity: 1 }); return; }
    el._split = SplitText.create(el, {
      type: "lines",
      mask: "lines",
      linesClass: "line",
      autoSplit: true,                 // re-split after fonts load or width changes
      aria: el.querySelector("a,button") ? "none" : "auto",
      onSplit(self) {
        el._splits = (el._splits || 0) + 1;              // debug/test: how many (re)splits
        gsap.set(el, { opacity: 1 });
        self.masks.forEach((m) => m.classList.add("line-mask"));
        // returning the tween lets SplitText revert it and sync its time on re-split
        // 120 not 100: the padded mask (motion.css) would otherwise show the top
        // 0.12em of a hidden line with tight leading
        return gsap.from(self.lines, {
          yPercent: 120, duration: 1.1, stagger: 0.09, ease: DRIFT, delay: (parseFloat(el.dataset.delay) || 0) + introDelayFor(el),
          scrollTrigger: { trigger: el, start: "top 90%", once: true },
        });
      },
    });
  });

  // data-clip[="scrub"] → clip-path inset curtain + inner media scale
  Motion.effect("clip", (el) => {
    const media = el.querySelector(":scope > img, :scope > picture > img, :scope > video");
    const scrub = el.dataset.clip === "scrub";
    const tl = gsap.timeline({
      defaults: { ease: scrub ? "none" : EASE, duration: scrub ? 1 : 1.4 },
      scrollTrigger: scrub
        ? { trigger: el, start: "top bottom", end: "top 25%", scrub: true }
        : { trigger: el, start: "top 85%", once: true },
      delay: scrub ? 0 : introDelayFor(el),
      // once-mode final state: no clip left behind (scrub mode must keep reversing)
      onComplete: scrub ? undefined : () => gsap.set(el, { clipPath: "none" }),
    });
    tl.fromTo(el, { clipPath: "inset(100% 0% 0% 0%)" }, { clipPath: "inset(0% 0% 0% 0%)" }, 0);
    if (media) tl.fromTo(media, { scale: 1.25 }, { scale: 1 }, 0);
  });

  // data-parallax="0.15" → drift within its (overflow:clip) frame, scrubbed
  Motion.effect("parallax", (el) => {
    const s = parseFloat(el.dataset.parallax) || 0.15;
    gsap.fromTo(el, { yPercent: -s * 100 }, {
      yPercent: s * 100, ease: "none",
      scrollTrigger: { trigger: el.parentElement, start: "top bottom", end: "bottom top", scrub: true },
    });
  });

  function applyEffects(scope, env) {
    const offs = [];
    for (const [name, fn] of Object.entries(Motion.effects)) {
      scope.querySelectorAll(`[data-${name}]`).forEach((el) => {
        try {
          const off = fn(el, env);
          if (typeof off === "function") offs.push(off);
        } catch (err) {
          // fail open: show the element in its final state and keep booting
          el.style.opacity = ""; el.style.clipPath = "none"; el.setAttribute("data-revealed", "");
          if (w.console) console.warn("[motion] effect", name, "failed on", el, err);
        }
      });
    }
    return () => offs.forEach((f) => f());
  }

  // ------------------------------------------------------------------ refresh
  // ScrollTrigger already refreshes on DOMContentLoaded, load and (debounced) resize.
  // Add: fonts (line heights change), and any later body-height change (lazy
  // content, accordions) — guarded so a refresh can't retrigger itself.
  // Keyboard and screen-reader users: focusing anything inside a pending one-shot
  // reveal finishes that reveal at once (scrubbed timelines are left to the scroll).
  function onFocusReveal(e) {
    const t = e.target;
    if (!t || !t.closest || t === d.body) return;
    ST.getAll().forEach((st) => {
      const a = st.animation;
      if (!a || st.vars.scrub || !st.vars.once || !st.trigger || !st.trigger.contains(t)) return;
      if (a.progress() < 1) a.progress(1);
    });
  }

  function refreshStrategy() {
    let lastH = d.body.scrollHeight, timer;
    const ro = new ResizeObserver(() => {
      const h = d.body.scrollHeight;
      if (Math.abs(h - lastH) < 2) return;
      clearTimeout(timer);
      timer = setTimeout(() => { ST.refresh(); lastH = d.body.scrollHeight; }, 150);
    });
    ro.observe(d.body);
    if (d.fonts && d.fonts.status !== "loaded") d.fonts.ready.then(() => ST.refresh());
    // hash deep-link: pins/spacers change the document after the browser's own
    // jump, so re-land on the target once after the first full refresh.
    if (location.hash.length > 1) {
      const id = decodeURIComponent(location.hash.slice(1));
      let done = false;
      const land = () => {
        if (done) return; done = true;
        const el = d.getElementById(id);
        if (el) Motion.scrollTo(el, { immediate: true });
      };
      if (d.readyState === "complete") requestAnimationFrame(land);
      else w.addEventListener("load", () => requestAnimationFrame(land), { once: true });
    }
  }

  // ------------------------------------------------------------------ page transitions
  // Cross-document View Transitions are pure CSS (@view-transition in motion.css).
  // Browsers without them get a JS curtain. Never both → no double animation.
  // Feature test verified in Chromium 141 (true) and Firefox 155 (false; Firefox
  // has same-document startViewTransition only and drops @view-transition).
  const HAS_XDOC_VT = "CSSViewTransitionRule" in w;
  Motion.hasCrossDocVT = HAS_XDOC_VT;
  function curtainFallback(motion) {
    let c = d.querySelector(".curtain");
    if (!c) { c = d.createElement("div"); c.className = "curtain"; c.setAttribute("aria-hidden", "true"); d.body.appendChild(c); }
    const KEY = "ts-curtain";
    // incoming: the inline head script added .curtain-in, so we start covered
    if (root.classList.contains("curtain-in")) {
      try { sessionStorage.removeItem(KEY); } catch (_) {}
      gsap.fromTo(c, { scaleY: 1, transformOrigin: "50% 0%" }, {
        scaleY: 0, duration: 0.7, ease: "ts.inOut", delay: 0.05,
        onComplete: () => { root.classList.remove("curtain-in"); gsap.set(c, { clearProps: "all" }); },
      });
    }
    // back/forward cache: the page was frozen mid-curtain — reset it
    const onShow = (e) => { if (e.persisted) { root.classList.remove("curtain-in"); gsap.set(c, { clearProps: "all" }); } };
    w.addEventListener("pageshow", onShow);
    const onClick = (e) => {
      if (!motion || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a || a.target === "_blank" || a.hasAttribute("download") || a.dataset.noTransition != null) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return; // same page / hash
      e.preventDefault();
      try { sessionStorage.setItem(KEY, "1"); } catch (_) {}
      const go = () => { location.href = url.href; };
      const safety = setTimeout(go, 900);                 // never trap the user
      gsap.fromTo(c, { scaleY: 0, transformOrigin: "50% 100%" }, {
        scaleY: 1, duration: 0.5, ease: "ts.inOut", onComplete: () => { clearTimeout(safety); go(); },
      });
    };
    d.addEventListener("click", onClick);
    return () => { d.removeEventListener("click", onClick); w.removeEventListener("pageshow", onShow); };
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    if (Motion.booted) return;
    Motion.booted = true;
    Motion.booting = true;
    // w.__vt is set by the inline head script's `pagereveal` listener
    Motion.introDelay = (Motion.config.introDelay || 0) + (w.__vt ? 0.35 : root.classList.contains("curtain-in") ? 0.45 : 0);
    const pageName = d.body.dataset.page;
    if (Motion.config.anchors) d.addEventListener("click", onAnchorClick);
    d.addEventListener("focusin", onFocusReveal);
    Motion.mm = gsap.matchMedia();
    Motion.mm.add({ motion: MQ.motion, reduce: MQ.reduce, fine: MQ.fine }, (ctx) => {
      const { motion, fine } = ctx.conditions;
      root.classList.toggle("js-motion", !!motion);
      const env = { motion: !!motion, fine: !!fine, ctx, get lenis() { return Motion.lenis; } };
      const offs = [];
      if (motion) {
        offs.push(startLenis());
        offs.push(applyEffects(d, env));
      }
      (Motion.globals || []).forEach((fn) => offs.push(fn(env)));
      const page = Motion.pages[pageName];
      if (page) offs.push(page(env));
      return () => offs.forEach((f) => typeof f === "function" && f());
    });
    if (!HAS_XDOC_VT) {
      Motion.mm.add({ motion: MQ.motion, reduce: MQ.reduce }, (ctx) => curtainFallback(!!ctx.conditions.motion));
    } else {
      root.classList.remove("curtain-in");
    }
    refreshStrategy();
    Motion.booting = false;
    root.classList.add("motion-ready");
    d.dispatchEvent(new CustomEvent("motion:ready"));
  }
  Motion.boot = boot;

  // PITFALL (hit): defer/module scripts execute while readyState is already
  // "interactive" — NOT "loading" — so `readyState === "loading" ? wait : boot()`
  // boots before the page scripts that follow us have registered. Always wait
  // for DOMContentLoaded (fires after every defer/module script has run);
  // `load` is the idempotent fallback for a script injected after DCL.
  if (d.readyState === "complete") queueMicrotask(boot);
  else {
    d.addEventListener("DOMContentLoaded", boot, { once: true });
    w.addEventListener("load", boot, { once: true });
  }
})(window, document);
