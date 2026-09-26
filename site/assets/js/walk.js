/*!
 * Two Squares — the walk (home) + the café sequence and the menu card.
 * Needs motion.js; the scrubbed clips need scrub.js (Motion.ScrubVideo).
 *
 * The walk: one tall .walk__track (height in CSS: --walk-len) holding a
 * position:sticky 100svh .walk__stage. ONE master timeline, scrubbed across
 * the track, tweens plain numbers (street position, zoom, door, clip progress,
 * captions). render() turns those numbers into transform / opacity /
 * clip-path writes. Geometry is measured only on ScrollTrigger refresh, never
 * inside the scrub. Only the room you are in scrubs its video; the next one is
 * fetched just before it's needed and far ones are released.
 *
 * Reduced motion / no JS: CSS lays the same DOM out as three stills. The café
 * button then opens the dialog straight on the seated frame, menu on the table.
 */
(function (w, d) {
  "use strict";
  const M = w.Motion;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const mqSmall = w.matchMedia("(max-width: 900px)");
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
  const ext = (v) => (!isSafari && v.canPlayType('video/webm; codecs="vp9"') === "probably" ? "webm" : "mp4");
  const TS = () => w.TS || {};

  // style writes with a per-element cache, so an unchanged frame writes nothing
  const touched = new Set();
  function css(el, prop, val) {
    if (!el) return;
    const c = el.__wc || (el.__wc = {});
    if (c[prop] === val) return;
    if (!touched.has(el)) { touched.add(el); el.__worig = el.getAttribute("style"); }
    c[prop] = val;
    el.style[prop] = val;
  }
  function resetTouched() {
    touched.forEach((el) => {
      if (el.__worig == null) el.removeAttribute("style"); else el.setAttribute("style", el.__worig);
      el.__wc = null;
    });
    touched.clear();
  }

  /* ================================================================ the café sequence */
  function makeCafe(dlg) {
    if (dlg.__cafe) return dlg.__cafe;
    const frames = $$(".cafe-seq__frame", dlg);
    const table = frames[3];
    const media = $(".cafe-seq__table-media", dlg);
    const video = $(".cafe-seq__video", dlg);
    const drop = $(".menu-card__drop", dlg);
    const card = $(".menu-card", dlg);
    const shadow = $(".menu-card__shadow", dlg);
    const skipBtn = $(".cafe-seq__skip", dlg);
    const closeBtn = $("button.cafe-seq__close", dlg);
    const live = $("[data-cafe-live]", dlg);
    const links = $$(".menu-card__link", dlg);
    let opener = null, isOpen = false, menu = false, motion = false, env = null;
    let tl = null, inerted = [], landTimer = 0, rvfc = 0, leaving = false, offTilt = null;
    const gsap = () => w.gsap;
    const MEDIA_SM = { yPercent: -12 }, MEDIA_LG = { xPercent: -6, scale: 1.1 };

    if (dlg.parentElement !== d.body) d.body.appendChild(dlg);   // so the rest of the page can go inert

    const announce = (msg) => { live.textContent = ""; setTimeout(() => { live.textContent = msg; }, 60); };
    const focusables = () => $$("a[href], button:not([disabled])", dlg).filter((el) => el.offsetParent !== null && getComputedStyle(el).visibility !== "hidden");

    function setVideo() {
      if (video.dataset.loaded === (mqSmall.matches ? "sm" : "lg")) return;
      video.dataset.loaded = mqSmall.matches ? "sm" : "lg";
      video.muted = true; video.playsInline = true;
      video.src = (mqSmall.matches ? video.dataset.srcSm : video.dataset.src) + "." + ext(video);
      video.preload = "auto";
    }
    // the settled frame: cup down, hands gone
    function settle() {
      const go = () => { try { video.currentTime = Math.min(4.7, (video.duration || 7.6) - 0.4); } catch (_) {} };   // cup down, hands still on the saucer
      if (video.readyState >= 1) go(); else video.addEventListener("loadedmetadata", go, { once: true });
    }

    function inert(on) {
      if (on) {
        inerted = Array.from(d.body.children).filter((el) => el !== dlg && !el.inert && !/^(SCRIPT|TEMPLATE|STYLE|LINK)$/.test(el.tagName));
        inerted.forEach((el) => { el.inert = true; });
      } else { inerted.forEach((el) => { el.inert = false; }); inerted = []; }
    }

    function showMenu(fast) {
      if (menu) return;
      menu = true;
      clearTimeout(landTimer);
      dlg.classList.add("has-menu");
      dlg.classList.remove("is-loading");
      const hadSkipFocus = d.activeElement === skipBtn || d.activeElement === dlg || !dlg.contains(d.activeElement);
      skipBtn.classList.add("is-gone");
      const g = gsap();
      const small = mqSmall.matches;
      if (g && motion) {
        g.fromTo(drop, { autoAlpha: 0, y: -70, rotationX: 26, rotationZ: -6, scale: 1.1 },
          { autoAlpha: 1, y: 0, rotationX: 0, rotationZ: 0, scale: 1, duration: fast ? 0.75 : 1.15, ease: M && M.EASE || "expo.out", clearProps: "transform" });
        g.fromTo(shadow, { opacity: 0, scale: 0.82 }, { opacity: 1, scale: 1, duration: fast ? 0.75 : 1.15, ease: "power2.out", clearProps: "opacity,transform" });
        // the camera makes room for the card: up a little on phones, a slow pan and push on desktop
        g.to(media, { ...(small ? MEDIA_SM : MEDIA_LG), duration: 1.4, ease: M && M.DRIFT || "power3.out" });
      } else if (g) g.set(media, small ? MEDIA_SM : MEDIA_LG);
      else media.style.transform = small ? "translateY(-12%)" : "translateX(-6%) scale(1.1)";
      announce(dlg.dataset.announce || "");
      if (hadSkipFocus) setTimeout(() => links[0] && links[0].focus({ preventScroll: true }), fast ? 80 : 450);
      if (env && env.fine && motion && g) offTilt = tilt();
    }

    function tilt() {
      const g = gsap();
      const rx = g.quickTo(card, "rotationX", { duration: 0.7, ease: "power3" });
      const ry = g.quickTo(card, "rotationY", { duration: 0.7, ease: "power3" });
      g.set(card, { transformPerspective: 1200 });
      const move = (e) => { if (e.pointerType && e.pointerType !== "mouse") return; ry((e.clientX / innerWidth - 0.5) * 8); rx(-(e.clientY / innerHeight - 0.5) * 8); };
      const out = () => { rx(0); ry(0); };
      dlg.addEventListener("pointermove", move, { passive: true });
      dlg.addEventListener("pointerleave", out);
      return () => { dlg.removeEventListener("pointermove", move); dlg.removeEventListener("pointerleave", out); g.set(card, { clearProps: "transform" }); };
    }

    function playTable(from) {
      setVideo();
      const g = gsap();
      if (g) g.to(table, { opacity: 1, duration: 0.5, ease: "none" }); else table.style.opacity = 1;
      try { if (from != null) video.currentTime = from; } catch (_) {}
      const p = video.play();
      if (p && p.catch) p.catch(() => { landTimer = setTimeout(() => showMenu(false), 900); });
      if (video.readyState < 3) dlg.classList.add("is-loading");
      video.addEventListener("playing", () => dlg.classList.remove("is-loading"), { once: true });
      // the menu lands as the cup settles (≈4.3s into the clip); a timer covers a stalled video
      const LAND = 4.3;
      const check = () => { if (!isOpen || menu) return; if (video.currentTime >= LAND) showMenu(false); else rvfc = requestAnimationFrame(check); };
      rvfc = requestAnimationFrame(check);
      landTimer = setTimeout(() => showMenu(false), 7000);
    }

    function skip() {
      if (!isOpen || menu) return;
      if (tl) { tl.kill(); tl = null; }
      const g = gsap();
      frames.slice(0, 3).forEach((f) => (g ? g.to(f, { opacity: 0, duration: 0.35, overwrite: true }) : (f.style.opacity = 0)));
      $$(".cafe-seq__cap", dlg).forEach((c) => g && g.set(c, { clearProps: "opacity,transform" }));
      playTable(video.currentTime > 4.6 ? null : 4.6);
      showMenu(true);
    }

    function sequence() {
      const g = gsap();
      const DRIFT = (M && M.DRIFT) || "power3.out";
      tl = g.timeline();
      tl.fromTo(dlg, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.5, ease: "none" }, 0);
      const step = 1.15;
      frames.slice(0, 3).forEach((f, i) => {
        const t = i * step;
        const img = $(".cafe-seq__img", f), cap = $(".cafe-seq__cap", f);
        tl.fromTo(f, { opacity: 0 }, { opacity: 1, duration: i ? 0.6 : 0.01, ease: "none" }, t);
        tl.fromTo(img, { scale: 1.02 }, { scale: 1.1, duration: step + 0.9, ease: "none" }, t);
        tl.fromTo(cap, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.55, ease: DRIFT }, t + 0.18);
        if (i < 2) tl.to(cap, { opacity: 0, duration: 0.25, ease: "none" }, t + step + 0.05);
        if (i > 0) tl.set(frames[i - 1], { opacity: 0 }, t + 0.62);
      });
      const tTable = 3 * step + 0.2;
      tl.to(frames[2], { opacity: 0, duration: 0.55, ease: "none" }, tTable - 0.3);
      tl.call(() => playTable(0.6), null, tTable);   // skip most of the black lead-in
      const cap3 = $(".cafe-seq__cap", table);
      tl.fromTo(cap3, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.55, ease: DRIFT }, tTable + 0.5);
      setVideo();   // start fetching the clip while the photographs run
    }

    function open(e, ctx) {
      if (isOpen) return;
      env = ctx || { motion: false, fine: false };
      motion = !!(env.motion && gsap());
      isOpen = true; menu = false; leaving = false;
      opener = d.activeElement && d.activeElement !== d.body ? d.activeElement : (e && e.currentTarget) || null;
      dlg.classList.add("is-open");
      dlg.classList.toggle("is-static", !motion);
      skipBtn.classList.remove("is-gone");
      inert(true);
      M && M.stop && M.stop();
      TS().hideHeader && TS().hideHeader(true);
      d.addEventListener("keydown", onKey, true);
      dlg.addEventListener("wheel", onWheel, { passive: true });
      dlg.addEventListener("touchmove", onWheel, { passive: true });
      if (motion) {
        sequence();
        setTimeout(() => skipBtn.focus({ preventScroll: true }), 60);
      } else {
        setVideo(); settle();
        table.style.opacity = 1;
        showMenu(true);
        setTimeout(() => links[0] && links[0].focus({ preventScroll: true }), 30);
      }
    }

    function close() {
      if (!isOpen || leaving) return;
      leaving = true;
      const g = gsap();
      const done = () => {
        isOpen = false; leaving = false; menu = false;
        if (tl) { tl.kill(); tl = null; }
        clearTimeout(landTimer); cancelAnimationFrame(rvfc);
        if (offTilt) { offTilt(); offTilt = null; }
        if (g) { g.killTweensOf([dlg, drop, shadow, media, card, ...frames, ...$$(".cafe-seq__img, .cafe-seq__cap", dlg)]); g.set([dlg, drop, shadow, media, ...frames, ...$$(".cafe-seq__img, .cafe-seq__cap", dlg)], { clearProps: "all" }); }
        [media, table, ...frames].forEach((el) => { el.style.opacity = ""; el.style.transform = ""; });
        dlg.classList.remove("is-open", "has-menu", "is-static", "is-loading");
        $$(".menu-card__item.is-ticked", dlg).forEach((li) => li.classList.remove("is-ticked"));
        try { video.pause(); video.currentTime = 0; } catch (_) {}
        live.textContent = "";
        inert(false);
        d.removeEventListener("keydown", onKey, true);
        dlg.removeEventListener("wheel", onWheel);
        dlg.removeEventListener("touchmove", onWheel);
        M && M.start && M.start();
        TS().hideHeader && TS().hideHeader(false);
        if (opener && opener.focus && d.contains(opener)) opener.focus({ preventScroll: true });
      };
      if (g && motion) g.to(dlg, { autoAlpha: 0, duration: 0.4, ease: "none", onComplete: done });
      else done();
    }

    function onWheel() { if (!menu) skip(); }
    function onKey(e) {
      if (!isOpen) return;
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (!menu && (e.key === " " || e.key === "Enter" || e.key === "PageDown" || e.key === "ArrowDown") && !(e.target.closest && e.target.closest("button, a"))) {
        e.preventDefault(); skip(); return;
      }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (!dlg.contains(d.activeElement)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }

    // choosing a dish: tick it, say so, then bring the form
    let going = false;
    links.forEach((a) => a.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      if (going) return;
      going = true;
      const li = a.closest(".menu-card__item");
      li.classList.add("is-ticked");
      const name = ($(".menu-card__name", a) || a).textContent.trim();
      announce((dlg.dataset.chosen || "{name}").replace("{name}", name));
      const reduce = w.matchMedia("(prefers-reduced-motion: reduce)").matches;
      setTimeout(() => { location.href = a.href; }, reduce ? 450 : 750);
      setTimeout(() => { going = false; }, 2500);
    }));
    skipBtn.addEventListener("click", skip);
    closeBtn.addEventListener("click", close);
    // back from the form (bfcache): still at the table, nothing ticked yet
    w.addEventListener("pageshow", (e) => {
      if (!e.persisted) return;
      going = false;
      $$(".menu-card__item.is-ticked", dlg).forEach((li) => li.classList.remove("is-ticked"));
    });

    const api = { open, close, get isOpen() { return isOpen; } };
    dlg.__cafe = api;
    return api;
  }

  function wireCafeButtons(dlg, env) {
    const cafe = makeCafe(dlg);
    const btns = $$("[data-cafe-open]");
    const onClick = (e) => { e.preventDefault(); cafe.open(e, env); };
    btns.forEach((b) => b.addEventListener("click", onClick));
    return () => { btns.forEach((b) => b.removeEventListener("click", onClick)); if (cafe.isOpen) cafe.close(); };
  }

  /* ================================================================ the walk */
  function initWalk(root, env) {
    const gsap = w.gsap, ST = w.ScrollTrigger;
    const stage = $(".walk__stage", root), track = $(".walk__track", root);
    const cams = $$(".walk__camera", stage);
    const washAm = $(".walk__wash--am", stage), washPm = $(".walk__wash--pm", stage), washNight = $(".walk__wash--night", stage);
    const glows = $$(".walk__glow", stage);
    const doorEls = $$(".walk__door", stage);
    const frames = doorEls.map((el) => $(".walk__frame", el));
    const plaques = doorEls.map((el) => $(".walk__plaque", el));
    const outro = $(".walk__outro", stage), outroLink = $(".walk__outro-link", stage);
    const hudStreet = $(".walk__street", stage), dayFill = $(".walk__day-fill", stage), dayTs = $$(".walk__day-t", stage), hint = $(".walk__hint", stage);
    const skipLink = $(".walk__skip", stage);
    const Scrub = M.ScrubVideo;

    const gates = $$(".walk__gate", stage).map((el, i) => ({
      el, i, id: el.dataset.gate, door: el.classList.contains("walk__gate--door"),
      scene: $(".walk__scene", el), room: $(".walk__room", el), video: $(".walk__video", el),
      facade: $(".walk__facade", el), leaves: $$(".walk__leaf", el), leafShades: $$(".walk__leaf-shade", el),
      shade: $(".walk__shade", el), vignette: $(".walk__vignette", el), end: $(".walk__end", el),
      caption: $(".walk__caption", el), title: $(".walk__title", el),
      cta: $(".walk__cta:not(.walk__cta--nojs)", el),
      st: { z: 0, open: 0, push: 0, facade: 1, vid: 0, cap: 0, ttl: 0 },
      player: null, want: false, token: 0, geo: {},
    }));
    const S = { walk: 0, am: 1, pm: 0, night: 0, outro: 0, hint: 1 };
    const geo = {};
    const offs = [];

    /* ---- sources: 4:5 files on phones, full files elsewhere */
    function setSources() {
      const sm = mqSmall.matches;
      gates.forEach((g) => {
        const v = g.video, base = sm ? v.dataset.srcSm : v.dataset.src;
        v.dataset.srcWebm = base + ".webm"; v.dataset.srcMp4 = base + ".mp4";
      });
    }
    setSources();
    // ScrubVideo (gated seeks, blob fetch, iOS unlock) with a cancellable fetch and
    // without the second video.load() after src is set (it aborts the first blob read)
    const Clip = Scrub && class extends Scrub {
      async load() {
        const ac = (this.ac = new AbortController());
        const v = this.v, src = this.pickSrc();
        let url = src;
        try {
          const res = await fetch(src, { signal: ac.signal });
          if (!res.ok) throw new Error(res.status);
          const blob = await res.blob();
          if (ac.signal.aborted) throw new Error("aborted");
          url = URL.createObjectURL(blob); this.objectURL = url;
        } catch (e) { if (ac.signal.aborted) throw e; }
        v.preload = "auto";
        v.src = url;
        if (v.readyState < 2) {
          await new Promise((res, rej) => {
            v.addEventListener("loadeddata", res, { once: true });
            ac.signal.addEventListener("abort", () => rej(new Error("aborted")), { once: true });
          });
        }
        this.duration = v.duration;
        this.unlock();
        this.ready = true;
      }
      cancel() { if (this.ac) this.ac.abort(); this.ac = null; }
    };
    if (Clip) gates.forEach((g) => { g.player = new Clip(g.video); });

    function want(g) {
      if (g.want) return;
      g.want = true;
      const v = g.video;
      const poster = mqSmall.matches ? v.dataset.posterSm : v.dataset.poster;
      if (v.getAttribute("poster") !== poster) v.setAttribute("poster", poster);
      if (!g.player) return;
      const token = ++g.token;
      g.player.load().then(() => {
        if (token !== g.token) { drop(g, true); return; }
        render(true);
      }).catch(() => {});
    }
    function drop(g, force) {
      if (!g.want && !force) return;
      if (!force) { g.want = false; g.token++; }
      const p = g.player;
      if (!p) return;
      p.ready = false;
      p.cancel();
      try { g.video.pause(); } catch (_) {}
      if (g.video.hasAttribute("src")) { g.video.removeAttribute("src"); g.video.load(); }
      if (p.objectURL) { URL.revokeObjectURL(p.objectURL); p.objectURL = null; }
    }

    /* ---- geometry: read on refresh only */
    function measure() {
      const W = stage.clientWidth, H = stage.clientHeight;
      const f0 = frames[0];
      const fw = f0.offsetWidth, fh = f0.offsetHeight;
      const ft = doorEls[0].offsetTop + f0.offsetTop;
      const cy = ft + fh / 2;
      Object.assign(geo, { W, H, fw, fh, ft, cy });
      geo.cx = doorEls.map((el, i) => el.offsetLeft + frames[i].offsetLeft + fw / 2);
      const xs = [0];
      geo.cx.forEach((c) => xs.push(W / 2 - c));
      const gap = geo.cx[1] - geo.cx[0];
      xs.push(xs[3] - Math.max(gap * 0.62, W / 2 + fw / 2 + 48));   // walk on until the last door has left the frame
      geo.xs = xs;
      geo.kEnd = Math.max(W / fw, cy / Math.max(1, cy - ft), (H - cy) / Math.max(1, ft + fh - cy)) * 1.002;
      const sm = mqSmall.matches;
      gates.forEach((g) => {
        const arStr = (sm && g.facade.dataset.arSm) || g.facade.dataset.ar;
        const [a, b] = arStr.split("/").map(Number);
        const ar = a / b;
        const bw = Math.max(W, H * ar), bh = bw / ar;
        const x0 = (W - bw) / 2, y0 = (H - bh) / 2;
        css(g.facade, "width", bw.toFixed(1) + "px");
        css(g.facade, "height", bh.toFixed(1) + "px");
        const gg = (g.geo = { bw, bh, x0, y0, s0: Math.max(fw / bw, fh / bh) });
        if (!g.door) {
          // the clip gets the picture's box, so it can shrink back into the frame exactly
          css(g.room, "right", "auto"); css(g.room, "bottom", "auto");
          css(g.room, "width", bw.toFixed(1) + "px"); css(g.room, "height", bh.toFixed(1) + "px");
          css(g.room, "transformOrigin", "0 0");
        }
        if (g.door) {
          const [dx, dy, dw, dh] = g.facade.dataset.door.split(" ").map(Number);
          const L = x0 + dx * bw, T = y0 + dy * bh, R = L + dw * bw, B = T + dh * bh;
          const Dx = (L + R) / 2, Dy = (T + B) / 2;
          gg.D = [Dx, Dy];
          gg.P = Math.max(1, Dx / Math.max(1, Dx - L), (W - Dx) / Math.max(1, R - Dx), Dy / Math.max(1, Dy - T), (H - Dy) / Math.max(1, B - Dy)) * 1.1;
          css(g.room, "transformOrigin", `${Dx.toFixed(1)}px ${Dy.toFixed(1)}px`);
        }
      });
    }

    /* ---- render: numbers → styles (writes only) */
    let lastTone = "", lastDay = -1, lastLoading = null, lastLive = [];
    function render(force) {
      if (force === true) touched.forEach((el) => { el.__wc = {}; });
      const { W, H, fw, fh, ft, cy, xs, kEnd } = geo;
      // the street
      const wi = clamp(S.walk, 0, xs.length - 1), i0 = Math.min(xs.length - 2, Math.floor(wi));
      const x = lerp(xs[i0], xs[i0 + 1], wi - i0);
      css(washAm, "opacity", S.am.toFixed(3)); css(washPm, "opacity", S.pm.toFixed(3)); css(washNight, "opacity", S.night.toFixed(3));
      glows.forEach((gl) => css(gl, "opacity", (0.28 + 0.72 * S.night).toFixed(3)));   // the sconces are on all day
      // which gate is open (only one at a time)
      let act = null, zmax = 0;
      gates.forEach((g) => { const s = g.st; const on = s.z > 0.0005 || s.ttl > 0.001 || s.cap > 0.001; if (on && (!act || s.z > act.st.z)) act = g; zmax = Math.max(zmax, s.z); });
      // the plaque steps aside as the camera goes in (it would sail over the HUD)
      plaques.forEach((pl, j) => css(pl, "opacity", act && act.i === j ? (1 - smooth(0.04, 0.3, act.st.z)).toFixed(3) : "1"));
      // camera
      let k = 1;
      if (act) k = Math.pow(kEnd, act.st.z);
      // walk (x) then zoom about the eye point (W/2, cy): one compositor transform per camera layer
      const camT = `translate3d(${((W / 2) * (1 - k) + k * x).toFixed(1)}px,${(cy * (1 - k)).toFixed(1)}px,0) scale(${k.toFixed(4)})`;
      cams.forEach((c) => css(c, "transform", camT));
      gates.forEach((g) => {
        const s = g.st;
        const on = g === act;
        css(g.el, "visibility", on ? "visible" : "hidden");
        // (inline visibility:visible on a child would show through the hidden gate)
        if (!on) { css(g.el, "zIndex", ""); css(g.room, "visibility", "hidden"); css(g.facade, "visibility", "hidden"); g.roomOn = false; return; }
        css(g.el, "zIndex", "1");
        const gg = g.geo;
        // window: the frame's picture, pushed by the camera
        const t = Math.max(0, cy - (cy - ft) * k), b = Math.max(0, H - (cy + (ft + fh - cy) * k));
        const l = Math.max(0, W / 2 - (fw / 2) * k);
        const full = t < 0.5 && b < 0.5 && l < 0.5;
        css(g.scene, "clipPath", full ? "none" : `inset(${t.toFixed(1)}px ${l.toFixed(1)}px ${b.toFixed(1)}px ${l.toFixed(1)}px)`);
        // the picture covers the visible window (the frame, clipped by the stage),
        // so it is locked to the frame at k = 1 and to the stage at full zoom
        const wcx = W / 2, wcy = (t + H - b) / 2;
        const c = Math.min(1, Math.max((W - 2 * l) / gg.bw, (H - b - t) / gg.bh));
        let zx = wcx - (gg.bw * c) / 2, zy = wcy - (gg.bh * c) / 2, sc = c;
        if (g.door && s.push > 0) {
          const P = lerp(1, gg.P, s.push), [Dx, Dy] = gg.D;
          zx = Dx + (zx - Dx) * P; zy = Dy + (zy - Dy) * P; sc = c * P;
        }
        const picT = `translate3d(${zx.toFixed(1)}px,${zy.toFixed(1)}px,0) scale(${sc.toFixed(4)})`;
        css(g.facade, "transform", picT);
        let roomOn;
        if (g.door) {
          css(g.facade, "opacity", (1 - smooth(0.55, 1, s.push)).toFixed(3));
          // through the doorway: keep the facade's raster while it grows and fades (no re-raster per frame)
          css(g.facade, "willChange", s.push > 0.001 ? "transform, opacity" : "");
          const opening = s.open > 0.001 && s.open < 0.999;
          if (g.__opening !== opening) { g.__opening = opening; g.el.classList.toggle("is-open", opening); }
          const ang = s.open * 84;
          g.leaves.forEach((lf, j) => css(lf, "transform", `rotateY(${(j ? -ang : ang).toFixed(2)}deg)`));
          g.leafShades.forEach((sh) => css(sh, "opacity", (s.open * 0.78).toFixed(3)));
          roomOn = s.open > 0.001 || s.push > 0.001;
          css(g.room, "transform", `scale(${lerp(1.22, 1, s.push).toFixed(4)})`);
        } else {
          css(g.facade, "opacity", s.facade.toFixed(3));
          roomOn = s.facade < 0.999;
          // the clip itself shrinks back into the frame on the way out
          css(g.room, "transform", picT);
        }
        css(g.room, "visibility", roomOn ? "visible" : "hidden");
        g.roomOn = roomOn;
        css(g.facade, "visibility", (g.door ? s.push < 0.999 : s.facade > 0.001) ? "visible" : "hidden");
        // text
        css(g.shade, "opacity", smooth(0.65, 1, s.z).toFixed(3));
        css(g.vignette, "opacity", s.ttl.toFixed(3));
        css(g.caption, "opacity", s.cap.toFixed(3));
        css(g.caption, "transform", `translate3d(0,${((1 - s.cap) * 22).toFixed(1)}px,0)`);
        css(g.end, "opacity", s.ttl.toFixed(3));
        css(g.end, "transform", `translate3d(0,${((1 - s.ttl) * 30).toFixed(1)}px,0)`);
        // the clip
        if (g.player) g.player.setProgress(s.vid);
      });
      gates.forEach((g) => {
        const liveNow = g === act && g.st.ttl > 0.6;
        if (lastLive[g.i] !== liveNow) { lastLive[g.i] = liveNow; g.el.classList.toggle("is-cta", liveNow); }
      });
      activeGate = act && act.roomOn ? act : null;   // the clip seeks whenever its room is on screen
      // outro, HUD
      css(outro, "opacity", S.outro.toFixed(3));
      css(outro, "transform", `translate3d(0,${((1 - S.outro) * 24).toFixed(1)}px,0)`);
      const outroLive = S.outro > 0.6;
      if (outro.__live !== outroLive) { outro.__live = outroLive; outro.classList.toggle("is-cta", outroLive); }
      css(hint, "opacity", S.hint.toFixed(3));
      css(hudStreet, "opacity", ((1 - smooth(0, 0.4, zmax)) * (1 - S.outro) * 0.8).toFixed(3));
      css(dayFill, "transform", `scaleX(${clamp((S.walk - 1) / 2, 0, 1).toFixed(4)})`);
      const day = Math.round(clamp(S.walk - 1, 0, 2));
      if (day !== lastDay) { lastDay = day; dayTs.forEach((el, j) => el.classList.toggle("is-on", j === day)); }
      const tone = zmax > 0.55 || S.night > 0.5 ? "dark" : "light";
      if (tone !== lastTone) { lastTone = tone; stage.dataset.tone = tone; }
      const loading = !!(activeGate && activeGate.player && activeGate.want && !activeGate.player.ready);
      if (loading !== lastLoading) { lastLoading = loading; stage.classList.toggle("is-loading", loading); }
      if (near) updateWants();
    }
    let activeGate = null;

    /* ---- the master timeline */
    const T = { walkIn: [], zoomIn: [], zoomEnd: [], scrub: [], hold: [], exitEnd: [] };
    const DUR = { walk0: 1.1, walk: 1.25, zoom: 1.05, open: 0.85, push: 0.85, hold: 0.8, back: 0.8, close: 0.6, out: 1.0, rewind: 1.5, outro: 1.4 };
    const SCRUB = { cafe: 2.3, restaurant: 2.7, bar: 2.0 };
    const tl = gsap.timeline({ defaults: { ease: "none", duration: 1 }, onUpdate: render, paused: true });
    let t = 0;
    tl.to(S, { walk: 1, duration: DUR.walk0, ease: "sine.inOut" }, 0);
    tl.to(S, { hint: 0, duration: 0.45 }, 0.55);
    t = DUR.walk0;
    gates.forEach((g, i) => {
      const s = g.st;
      if (i > 0) {
        T.walkIn[i] = t;
        tl.to(S, { walk: i + 1, duration: DUR.walk, ease: "sine.inOut" }, t);
        if (i === 1) tl.to(S, { am: 0, pm: 1, duration: DUR.walk }, t);
        if (i === 2) tl.to(S, { night: 1, pm: 0.4, duration: DUR.walk }, t);
        t += DUR.walk;
      } else T.walkIn[0] = 0;
      T.zoomIn[i] = t;
      tl.to(s, { z: 1, duration: DUR.zoom, ease: "power2.inOut" }, t);
      t += DUR.zoom;
      T.zoomEnd[i] = t;
      if (g.door) {
        tl.to(s, { open: 1, duration: DUR.open, ease: "power1.inOut" }, t);
        t += DUR.open * 0.65;
        tl.to(s, { push: 1, duration: DUR.push, ease: "power2.in" }, t);
        t += DUR.push;
      } else {
        tl.to(s, { facade: 0, duration: 0.2 }, t);
      }
      T.scrub[i] = t;
      const sd = SCRUB[g.id] || 2;
      tl.to(s, { vid: 1, duration: sd }, t);
      tl.to(s, { cap: 1, duration: 0.4, ease: "power2.out" }, t + 0.12);
      tl.to(s, { cap: 0, duration: 0.3, ease: "power1.in" }, t + sd * 0.56);
      tl.to(s, { ttl: 1, duration: 0.5, ease: "power3.out" }, t + sd * 0.74);
      t += sd;
      T.hold[i] = t + DUR.hold * 0.3;
      t += DUR.hold;
      tl.to(s, { ttl: 0, duration: 0.3, ease: "power1.in" }, t);
      t += 0.25;
      if (g.door) {
        tl.to(s, { push: 0, duration: DUR.back, ease: "power2.out" }, t);
        tl.to(s, { open: 0, duration: DUR.close, ease: "power1.inOut" }, t + DUR.back * 0.55);
        t += DUR.back * 0.55 + DUR.close * 0.8;
      } else {
        // walk back out: the clip rewinds to the doorway while the camera backs off
        tl.to(s, { vid: 0, duration: DUR.rewind, ease: "sine.inOut" }, t);
        t += DUR.rewind - DUR.out * 0.7;
      }
      tl.to(s, { z: 0, duration: DUR.out, ease: "power2.inOut" }, t);
      t += DUR.out;
      T.exitEnd[i] = t;
    });
    tl.to(S, { walk: 4, duration: DUR.outro, ease: "sine.inOut" }, t);
    tl.to(S, { outro: 1, duration: 0.6, ease: "power2.out" }, t + DUR.outro * 0.45);
    T.outro = t + DUR.outro * 0.8;
    t += DUR.outro + 0.5;
    tl.set({}, {}, t);

    /* ---- which clips to hold: the room you're in, the next one just before it's needed */
    let near = false;
    function updateWants() {
      const now = tl.time();
      gates.forEach((g, i) => {
        const from = i === 0 ? -Infinity : T.scrub[i - 1];
        const to = i < gates.length - 1 ? T.zoomEnd[i + 1] : Infinity;
        if (now >= from && now <= to) want(g); else drop(g);
      });
    }

    measure();
    render(true);

    const st = ST.create({
      trigger: track, start: "top top", end: "bottom bottom",
      animation: tl, scrub: 0.7,
      onToggle: (self) => setLive(self.isActive),
      onRefresh: () => { measure(); render(true); },
    });

    let live = false, headerHidden = false;
    function setLive(on) {
      if (on === live) return;
      live = on;
      stage.classList.toggle("is-live", on);
      if (on !== headerHidden && TS().hideHeader) { headerHidden = on; TS().hideHeader(on); }
    }

    // fetch the café clip as the street comes near; let go of everything far away
    const io = new IntersectionObserver((es) => {
      const e = es[es.length - 1];
      near = e.isIntersecting;
      if (near) updateWants(); else gates.forEach((g) => drop(g));
    }, { rootMargin: "100% 0px 100% 0px" });
    io.observe(track);

    // only the room you're in scrubs (gated seeks, one per frame at most)
    const tick = () => { if (activeGate && activeGate.player && live) activeGate.player.tick(); };
    gsap.ticker.add(tick);

    /* ---- controls */
    const timeToY = (time) => st.start + (st.end - st.start) * (time / tl.duration());
    const jumpTo = (time) => M.scrollTo(Math.round(timeToY(time)), { immediate: true });
    // keyboard: tabbing to a room's button walks you to that room
    gates.forEach((g, i) => {
      if (!g.cta) return;
      const onFocus = () => { if (g.st.ttl < 0.6 && live || !live) jumpTo(T.hold[i]); };
      const onTitle = () => { if (g.el.classList.contains("is-cta")) g.cta.click(); };
      g.cta.addEventListener("focus", onFocus);
      g.title.addEventListener("click", onTitle);
      if (g.cta.dataset.cursor) g.title.dataset.cursor = g.cta.dataset.cursor;
      offs.push(() => { g.cta.removeEventListener("focus", onFocus); g.title.removeEventListener("click", onTitle); delete g.title.dataset.cursor; });
    });
    const onOutroFocus = () => { if (S.outro < 0.6) jumpTo(T.outro); };
    outroLink.addEventListener("focus", onOutroFocus);
    offs.push(() => outroLink.removeEventListener("focus", onOutroFocus));
    // skip the walk
    const onSkip = (e) => {
      const target = d.getElementById("after-walk") || track.nextElementSibling || root.nextElementSibling;
      if (!target) return;
      e.preventDefault();
      gates.forEach((g) => drop(g));
      // a number, measured from the live page (Lenis may not have synced a native scroll yet)
      const pad = parseFloat(getComputedStyle(d.documentElement).scrollPaddingTop) || 0;
      const y = Math.max(st.end + 1, Math.round(target.getBoundingClientRect().top + w.scrollY - pad));
      M.scrollTo(y, { immediate: true });
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    };
    skipLink.addEventListener("click", onSkip);
    offs.push(() => skipLink.removeEventListener("click", onSkip));

    // phone ↔ desktop sources
    const onMQ = () => { gates.forEach((g) => drop(g)); setSources(); ST.refresh(); };
    mqSmall.addEventListener("change", onMQ);
    offs.push(() => mqSmall.removeEventListener("change", onMQ));

    // debug / QA handle
    root.__walk = { tl, st, S, gates, geo, T, get active() { return activeGate; } };

    return () => {
      offs.forEach((f) => f());
      gsap.ticker.remove(tick);
      io.disconnect();
      st.kill(); tl.kill();
      setLive(false);
      gates.forEach((g) => { drop(g); if (g.player) g.player.destroy(); g.video.removeAttribute("poster"); g.el.classList.remove("is-cta", "is-open"); g.__opening = false; });
      stage.classList.remove("is-loading");
      stage.dataset.tone = "light";
      outro.classList.remove("is-cta");
      resetTouched();
      delete root.__walk;
    };
  }

  /* ================================================================ boot */
  function boot(env) {
    const root = d.querySelector("[data-walk]");
    const dlg = d.querySelector("[data-cafe-seq]");
    const offs = [];
    if (dlg) offs.push(wireCafeButtons(dlg, env));
    if (root && env.motion && w.gsap && w.ScrollTrigger) offs.push(initWalk(root, env));
    return () => offs.forEach((f) => f && f());
  }

  if (M && M.global && w.gsap) {
    M.global((env) => boot(env));
  } else {
    // motion engine missing: stills (CSS), and the café dialog opens straight on the table
    const go = () => boot({ motion: false, fine: false });
    if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", go, { once: true }); else go();
  }
})(window, document);
