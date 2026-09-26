/*!
 * Two Squares — the café sequence (the corner table) and the paper menu card.
 * Shared component: partials/cafe-seq.html + assets/css/cafe-seq.css. Loads after site.js.
 *
 * Contract (both home versions rely on it):
 *   - any button[data-cafe-seq-open] opens it (one delegated click handler)
 *   - TS.openCafeSeq(openerEl) does the same from code; TS.closeCafeSeq() closes it
 *   - focus returns to the opener on close
 * Frames → seated-cup video → the menu card lands; Esc / Stand up / Skip to the menu;
 * focus trap; Motion.stop/start; TS.hideHeader; reduced motion opens straight on the
 * seated frame with the menu on the table. Without JS, #corner-table:target shows it.
 */
(function (w, d) {
  "use strict";
  const M = w.Motion;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const mqSmall = w.matchMedia("(max-width: 900px)");
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
  const ext = (v) => (!isSafari && v.canPlayType('video/webm; codecs="vp9"') === "probably" ? "webm" : "mp4");
  const TS = () => w.TS || {};

  /* ================================================================ the sequence */
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
    // the stacked table (cup above, card below): phones and portrait tablets (see cafe-seq.css)
    const mqStack = w.matchMedia("(max-width: 900px), (max-aspect-ratio: 4/5)");

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
      const small = mqStack.matches;
      if (g && motion) {
        g.fromTo(drop, { autoAlpha: 0, y: -70, rotationX: 26, rotationZ: -6, scale: 1.1 },
          { autoAlpha: 1, y: 0, rotationX: 0, rotationZ: 0, scale: 1, duration: fast ? 0.75 : 1.15, ease: M && M.EASE || "expo.out", clearProps: "transform" });
        g.fromTo(shadow, { opacity: 0, scale: 0.82 }, { opacity: 1, scale: 1, duration: fast ? 0.75 : 1.15, ease: "power2.out", clearProps: "opacity,transform" });
        // the camera makes room for the card: up a little on phones, a slow pan and push on desktop
        g.to(media, { ...(small ? MEDIA_SM : MEDIA_LG), duration: 1.4, ease: M && M.DRIFT || "power3.out" });
      } else if (g) g.set(media, small ? MEDIA_SM : MEDIA_LG);
      else media.style.transform = small ? "translateY(-12%)" : "translateX(-6%) scale(1.1)";
      // phones: the seated caption sits over the cup, so it steps out once the card is down
      if (small) $$(".cafe-seq__cap", dlg).forEach((c) => (g ? g.to(c, { opacity: 0, duration: 0.4, ease: "none", overwrite: true }) : (c.style.opacity = 0)));
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

    function open(from, ctx) {
      if (isOpen) return;
      env = ctx || { motion: false, fine: false };
      motion = !!(env.motion && gsap());
      isOpen = true; menu = false; leaving = false;
      // focus goes back to whoever opened it (Safari doesn't focus a clicked button, so the button is passed in)
      opener = (from && from.focus && from) || (d.activeElement && d.activeElement !== d.body ? d.activeElement : null);
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

  /* ================================================================ wiring */
  let env = { motion: false, fine: false };
  let cafe = null;
  const get = () => {
    if (cafe) return cafe;
    const dlg = d.querySelector("[data-cafe-seq]");
    return (cafe = dlg ? makeCafe(dlg) : null);
  };
  function openSeq(opener) { const c = get(); if (c) c.open(opener || null, env); return !!c; }
  const ts = (w.TS = w.TS || {});
  ts.openCafeSeq = openSeq;
  ts.closeCafeSeq = () => { if (cafe && cafe.isOpen) cafe.close(); };

  // one delegated handler: buttons can be added or re-rendered at any time
  d.addEventListener("click", (e) => {
    const b = e.target && e.target.closest && e.target.closest("button[data-cafe-seq-open]");
    if (!b || b.disabled || e.defaultPrevented) return;
    e.preventDefault();
    openSeq(b);
  });

  if (M && M.global && w.gsap) {
    // runs for motion and for reduced motion; a switch closes an open dialog, the next one opens in the new mode
    M.global((ctx) => {
      env = ctx;
      get();
      return () => { if (cafe && cafe.isOpen) cafe.close(); env = { motion: false, fine: false }; };
    });
  } else {
    // motion engine missing: the dialog opens straight on the table
    const go = () => get();
    if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", go, { once: true }); else go();
  }
})(window, document);
