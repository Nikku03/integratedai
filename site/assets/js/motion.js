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
 *
 * ROUND 3 — LIQUID FLOATING (v1.2). Motion only; nothing runs under reduced motion.
 *   Float     every .media figure, and every element with data-float, drifts slowly
 *             and organically (y ±6–10px, x ±2px, rotation ±0.25–0.4°, 6–9 s, its own
 *             phase) like something floating in water. Text columns drift less
 *             (±4px, ±0.12°). data-float="0.5" is calmer, "1.4" livelier; "off" (on
 *             the element or any ancestor) opts out.
 *             Auto-skipped .media: fills (position absolute/fixed), anything inside a
 *             sticky or fixed stage, anything wider than 90% of the viewport.
 *             An explicit data-float is honoured anywhere (e.g. a pop-up card inside
 *             a sticky stage).
 *   Liquid    the same elements answer Lenis's scroll velocity with a springy lag
 *   scroll    (they trail the scroll by up to ±24px and spring back with a little
 *             overshoot); images lag more than text, each by its own amount.
 *   Cost      ONE gsap.ticker listener updates only the elements an
 *             IntersectionObserver reports near the viewport, and writes only the
 *             CSS `translate` + `rotate` properties (compositor-only, .is-afloat
 *             promotes the element while it is on screen). Never `transform`, so it
 *             composes with any GSAP tween on the same element. If a later GSAP tween
 *             bakes the float into its transform (GSAP folds translate/rotate into
 *             transform when it parses an element), the float pauses on that element
 *             and eases back in once the tween clears its transform.
 *   Hover     fine pointers: a floating .media softens / morphs its corners (CSS,
 *             base.css) and runs a ~0.85 s SVG liquid ripple (feTurbulence +
 *             feDisplacementMap, applied only while it runs). Skipped on Safari, on
 *             very large figures, and for the session if frames get slow.
 *   Blob      .blob figures get .is-inview while on screen (their border-radius
 *             morph runs only then; see base.css).
 *   API       Motion.float(el[, strength]) / Motion.unfloat(el) for elements added
 *             after boot. Floating elements carry .is-float.
 */
(function (w, d) {
  "use strict";
  const root = d.documentElement;
  const gsap = w.gsap, ST = w.ScrollTrigger, SplitText = w.SplitText;
  const Motion = (w.Motion = w.Motion || {});
  Motion.version = "1.2.0";
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
  // rounded curtains: the clip keeps the figure's own corner radius (px), so reveals are soft-edged
  const R_FALLBACK = "28px";
  const radiusOf = (el) => {
    const r = getComputedStyle(el).borderTopLeftRadius || "";
    return /^[\d.]+px$/.test(r) && parseFloat(r) > 0 ? r : (getComputedStyle(root).getPropertyValue("--r-lg").trim() || R_FALLBACK);
  };
  Motion.radiusOf = radiusOf;

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
      const R = radiusOf(el);
      gsap.fromTo(el, { clipPath: `inset(8% 8% 8% 8% round ${R})` }, { clipPath: `inset(0% 0% 0% 0% round ${R})`, duration: 1.2, ease: DRIFT, delay,
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
    const R = radiusOf(el);
    tl.fromTo(el, { clipPath: `inset(100% 0% 0% 0% round ${R})` }, { clipPath: `inset(0% 0% 0% 0% round ${R})` }, 0);
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

  // ------------------------------------------------------------------ liquid floating (see the header)
  const LIQ = {
    amp: [6, 10], ampText: 4,          // px, vertical drift
    rot: [0.2, 0.35], rotText: 0,      // deg (text never rotates: it would soften the glyphs)
    period: [6, 9],                    // s
    lag: 0.9, lagText: 0.45, lagMax: 24,
    k: 150, c: 13,                     // spring: stiffness, damping (ζ ≈ 0.53: a little overshoot)
    margin: "15% 0px 15% 0px",
  };
  if (Motion.config.liquidOpts) Object.assign(LIQ, Motion.config.liquidOpts);   // per-page tuning
  const SAFARI = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
  const rand = (i) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
  const lerp = (a, b, t) => a + (b - a) * t;
  Motion.float = () => {}; Motion.unfloat = () => {};

  function liquid(env) {
    const items = new Map();                 // el → state
    const live = new Set();                  // states near the viewport
    let seq = 0, t0 = 0, lastScroll = null, vel = 0;

    const offStage = (el) => {
      for (let n = el.parentElement; n && n !== d.body; n = n.parentElement) {
        const p = getComputedStyle(n).position;
        if (p === "sticky" || p === "fixed") return true;
      }
      return false;
    };
    const autoOK = (el) => {
      if (el.closest('[data-float="off"]')) return false;
      const p = getComputedStyle(el).position;
      if (p === "absolute" || p === "fixed") return false;
      if (el.offsetWidth > innerWidth * 0.9) return false;
      return !offStage(el);
    };

    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      const el = e.target, st = items.get(el);
      if (el.classList.contains("blob")) el.classList.toggle("is-inview", e.isIntersecting);
      if (!st) return;
      if (e.isIntersecting) { live.add(st); el.classList.add("is-afloat"); }
      else { live.delete(st); el.classList.remove("is-afloat"); }
    }), { rootMargin: LIQ.margin });

    function add(el, strength) {
      if (items.has(el)) return;
      const i = ++seq, r1 = rand(i), r2 = rand(i + 7.31), r3 = rand(i + 13.7);
      const f = strength != null ? strength : (el.dataset.float && el.dataset.float !== "on" ? parseFloat(el.dataset.float) : 1);
      const s = isFinite(f) ? Math.max(0, Math.min(f, 2)) : 1;
      const text = !el.classList.contains("media") && !el.querySelector("img, video");
      const st = {
        el, text,
        amp: (text ? LIQ.ampText : lerp(LIQ.amp[0], LIQ.amp[1], r1)) * s,
        rot: (text ? LIQ.rotText : lerp(LIQ.rot[0], LIQ.rot[1], r2)) * s * (r3 < 0.5 ? -1 : 1),
        w: (Math.PI * 2) / lerp(LIQ.period[0], LIQ.period[1], r3),
        ph: r1 * Math.PI * 2,
        lag: (text ? LIQ.lagText : LIQ.lag) * lerp(0.75, 1.3, r2) * Math.min(s, 1.4),
        k: LIQ.k * lerp(0.8, 1.2, r3),
        y: 0, v: 0, ramp: 0, baked: false, wrote: false,
      };
      items.set(el, st);
      el.classList.add("is-float");
      io.observe(el);
      if (st.text === false && env.fine && el.classList.contains("media")) el.addEventListener("pointerenter", onHover);
    }
    function remove(el) {
      const st = items.get(el);
      if (!st) return;
      io.unobserve(el); live.delete(st); items.delete(el);
      el.classList.remove("is-float", "is-afloat");
      el.removeEventListener("pointerenter", onHover);
      if (st.wrote) { el.style.removeProperty("translate"); el.style.removeProperty("rotate"); }
    }

    // candidates: explicit data-float anywhere; .media automatically (with the skips above);
    // the outermost one wins, so a floating column never double-floats the figure inside it
    const cands = [];
    d.querySelectorAll("[data-float]").forEach((el) => { if (el.dataset.float !== "off" && !el.parentElement.closest('[data-float="off"]')) cands.push(el); });
    d.querySelectorAll(".media").forEach((el) => { if (!el.hasAttribute("data-float") && autoOK(el)) cands.push(el); });
    cands.filter((el) => !cands.some((o) => o !== el && o.contains(el))).forEach((el) => add(el));
    d.querySelectorAll(".blob").forEach((el) => { if (!items.has(el)) io.observe(el); });

    const tick = (time, dt) => {
      if (!t0) t0 = time;
      const L = Motion.lenis;
      const sc = L ? L.animatedScroll : null;
      const sec = Math.min(Math.max(dt / 1000, 1 / 240), 1 / 30);
      if (sc != null && lastScroll != null) {
        const raw = (sc - lastScroll) / (sec * 60);                  // px per 60 fps frame
        vel += (raw - vel) * 0.5;                                     // light smoothing of wheel steps
      } else vel = 0;
      lastScroll = sc;
      if (!live.size) return;
      const t = time - t0;
      live.forEach((st) => {
        const el = st.el, stl = el.style;
        // a GSAP tween folded our translate/rotate into its transform: hold until it clears
        if (stl.translate === "none") { st.baked = true; return; }
        if (st.baked) {
          if (stl.transform && stl.transform !== "none") return;
          st.baked = false; st.ramp = 0; st.y = 0; st.v = 0;
        }
        st.ramp = Math.min(1, st.ramp + sec / 1.2);
        const a = st.ramp * st.ramp * (3 - 2 * st.ramp);             // smoothstep in
        const wt = st.w * t + st.ph;
        const fy = st.amp * (0.72 * Math.sin(wt) + 0.28 * Math.sin(2.13 * wt + 1.7));
        const fx = st.amp * 0.25 * Math.sin(0.63 * wt + 2.1);
        const fr = st.rot * Math.sin(0.81 * wt + 0.6);
        const target = Math.max(-LIQ.lagMax, Math.min(LIQ.lagMax, vel * st.lag));
        st.v += (st.k * (target - st.y) - LIQ.c * st.v) * sec;
        st.y += st.v * sec;
        stl.translate = `${(fx * a).toFixed(2)}px ${((fy + st.y) * a).toFixed(2)}px`;
        stl.rotate = `${(fr * a).toFixed(3)}deg`;
        st.wrote = true;
      });
    };
    gsap.ticker.add(tick);

    // ---- liquid hover ripple (fine pointers): one shared SVG filter, applied only while it runs
    let svg = null, disp = null, turb = null, cur = null, rip = null, slow = 0;
    let rippleOK = env.fine && !SAFARI && !Motion.config.noRipple;
    // only a pointer that really moves onto a figure ripples it: never content scrolling under a
    // resting pointer (browsers send synthetic hover events after a scroll), never mid-scroll
    let px = -1, py = -1;
    const onMove = (e) => { px = e.clientX; py = e.clientY; };
    if (rippleOK) w.addEventListener("pointermove", onMove, { passive: true });
    if (rippleOK) {
      const NS = "http://www.w3.org/2000/svg";
      svg = d.createElementNS(NS, "svg");
      svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
      svg.setAttribute("width", "0"); svg.setAttribute("height", "0");
      svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none";
      svg.innerHTML = '<filter id="ts-liquid" x="-4%" y="-4%" width="108%" height="108%" color-interpolation-filters="sRGB">' +
        '<feTurbulence type="fractalNoise" baseFrequency="0.0065 0.0095" numOctaves="1" seed="4" result="n"/>' +
        '<feDisplacementMap in="SourceGraphic" in2="n" scale="0" xChannelSelector="R" yChannelSelector="G"/></filter>';
      d.body.appendChild(svg);
      turb = svg.querySelector("feTurbulence"); disp = svg.querySelector("feDisplacementMap");
    }
    function onHover(e) {
      const el = e.currentTarget;
      if (!rippleOK || e.pointerType === "touch") return;
      const still = Math.abs(e.clientX - px) + Math.abs(e.clientY - py) < 1;
      if (still || Math.abs(vel) > 0.3 || (Motion.lenis && Motion.lenis.isScrolling)) return;
      const r = el.getBoundingClientRect();
      if (r.width * r.height > 1.1e6 || r.width < 60) return;       // huge figures: the corner morph only
      if (cur && cur !== el) cur.style.removeProperty("filter");
      if (rip) rip.kill();
      cur = el;
      turb.setAttribute("seed", String(1 + Math.floor(Math.random() * 90)));
      el.style.filter = "url(#ts-liquid)";
      let last = performance.now(), frames = 0, sum = 0;
      const end = () => { el.style.removeProperty("filter"); if (cur === el) cur = null; };
      rip = gsap.timeline({ onComplete: end, onInterrupt: end, onUpdate: () => {
        const now = performance.now(); sum += now - last; last = now; frames++;
        // graceful fallback: a slow filter (software raster, big figure) is switched off for the session
        if (frames === 8 && sum / frames > 34 && ++slow >= 2) { rippleOK = false; }
      } })
        .fromTo(disp, { attr: { scale: 0 } }, { attr: { scale: 11 }, duration: 0.32, ease: "sine.out" })
        .to(disp, { attr: { scale: 0 }, duration: 0.6, ease: "sine.inOut" });
    }

    Motion.float = (el, strength) => { if (el && !items.has(el)) add(el, strength); };
    Motion.unfloat = (el) => remove(el);
    return () => {
      gsap.ticker.remove(tick);
      w.removeEventListener("pointermove", onMove);
      io.disconnect();
      if (rip) rip.kill();
      [...items.keys()].forEach(remove);
      d.querySelectorAll(".blob.is-inview").forEach((el) => el.classList.remove("is-inview"));
      if (svg) svg.remove();
      Motion.float = () => {}; Motion.unfloat = () => {};
    };
  }
  Motion.liquidConfig = LIQ;

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
      // last: the float must start after every boot-time tween has parsed its element
      if (motion && Motion.config.liquid !== false) {       // Motion.config = { liquid: false } turns it off for a page
        try { offs.push(liquid(env)); } catch (err) { if (w.console) console.warn("[motion] liquid failed", err); }
      }
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
