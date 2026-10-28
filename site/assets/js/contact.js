/*!
 * Two Squares — contact.html: the enquiry form.
 * What an arrival preselects (venue, service, stage, from, item, message; the room remembered on the
 * last sector page / case study when the link names none) is worked out by the inline script at the
 * top of <main> in contact.html, which also draws the banner and sets the fields before first paint
 * (window.__tsPrefill), so nothing moves. This file wires the behaviour: the banner's pills, "Start
 * from scratch", inline validation on blur + submit with an error summary, Netlify Forms submission
 * (urlencoded fetch), sending / success / network-error states.
 * Plain DOM code: it works with reduced motion and even if GSAP never loads.
 */
(function (w, d) {
  "use strict";
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const form = $("#enquiry");
  if (!form) return;

  /* ---------------------------------------------------------------- copy (verbatim from the deck) */
  const MSG = {
    name: { required: "We’ll need a name to reply to." },
    email: { required: "We’ll need an email to reply to.", invalid: "That email doesn’t look quite right. Check for a missing @ or a typo." },
    phone: { invalid: "That number doesn’t look right. Add the country code if you’re outside India." },
    city: { required: "Tell us roughly where the site is, even if it’s just the city." },
    message: { tooLong: "That’s a lot of detail, and we like it. Trim it to 2,000 characters, or attach it as a file." },
  };
  const SUMMARY = { one: "One thing needs a look before this can go.", many: "{n} things need a look before this can go." };
  const SEND = "Send it over", SENDING = "Sending…";
  const NETWORK = "That didn’t send, and it’s our end, not yours. Your details are still here. Try again, or email hello@twosquares.studio.";
  const BUDGET = {
    INR: [["not-sure", "Not sure yet"], ["under-25l", "Under ₹25 lakh"], ["25-60l", "₹25–60 lakh"], ["60l-1.5cr", "₹60 lakh – ₹1.5 crore"], ["over-1.5cr", "Over ₹1.5 crore"]],
    USD: [["not-sure", "Not sure yet"], ["under-50k", "Under US$50k"], ["50-150k", "US$50k–150k"], ["150-400k", "US$150k–400k"], ["over-400k", "Over US$400k"]],
  };

  /* ---------------------------------------------------------------- elements */
  const summary = $("#form-errors"), summaryTitle = $("#form-errors-title"), summaryList = $("#form-errors-list");
  const banner = $("#prefill"), clearBtn = $("#prefill-clear"), picksEl = $("#prefill-picks");
  const done = $("#enquiry-done"), netErr = $("#enquiry-neterr"), status = $("#enquiry-status");
  const submit = $(".enquiry__submit", form), submitLabel = $(".enquiry__submit-label", form);
  const reqNote = $(".enquiry__req", form);
  const state = { from: "", itemName: "", sending: false };
  const reduce = () => w.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scrollToEl = (el) => {
    const L = w.Motion && w.Motion.lenis;
    // showing the summary / success grows or shrinks the page above the viewport; the
    // browser's scroll anchoring moves the page before Lenis hears of it, so sync first
    if (L && Math.abs(L.animatedScroll - w.scrollY) > 1) L.scrollTo(w.scrollY, { immediate: true, force: true });
    if (w.Motion && w.Motion.scrollTo) w.Motion.scrollTo(el, { duration: 0.9 });
    else el.scrollIntoView({ block: "start", behavior: reduce() ? "auto" : "smooth" });
  };
  const fmt = (n) => n.toLocaleString("en-IN");

  /* ---------------------------------------------------------------- controls */
  // budget currency toggle: same five bands, so the chosen position carries across
  const budget = $("#f-budget"), currencyInput = $("#f-currency");
  function setCurrency(cur) {
    if (!budget || !BUDGET[cur]) return;
    const idx = budget.selectedIndex;
    const first = budget.options[0];
    budget.replaceChildren(first, ...BUDGET[cur].map(([v, l]) => new Option(l, v)));
    budget.selectedIndex = idx;
    if (currencyInput) currencyInput.value = cur;
    $$(".currency__opt", form).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.currency === cur)));
  }
  $$(".currency__opt", form).forEach((b) => b.addEventListener("click", () => setCurrency(b.dataset.currency)));

  // message counter
  const message = $("#f-message"), countNow = $("[data-count-now]", form), countEl = $(".field__count", form);
  const MAX = 2000;
  function updateCount() {
    if (!message || !countNow) return;
    const n = message.value.length;
    countNow.textContent = fmt(n);
    countEl.classList.toggle("is-over", n > MAX);
  }
  message && message.addEventListener("input", updateCount);

  /* ---------------------------------------------------------------- the preselected arrival */
  // contact.html has already drawn the banner and set the fields (window.__tsPrefill). Here: make
  // sure the fields are set (harmless if they are), check the pills against what the form really
  // holds, and make each pill jump to its field.
  const P = w.__tsPrefill || null;
  const MEMORY = ["ts-venue", "ts-venue-from", "ts-venue-item"];   // site.js venue memory (sessionStorage)
  const picked = [];                  // the fields filled in on arrival: [{ field, ctl, text }]
  function prefill() {
    if (!P) return;
    if (P.apply) P.apply();
    if (P.show && banner.hidden && P.render) P.render();
    state.from = P.from || ""; state.itemName = P.itemName || "";
    markPicked();
    // the pills were written from the same data before first paint; redraw them only if the form disagrees
    const have = $$(".prefill__pick", picksEl).map((a) => a.textContent).join("|");
    if (!banner.hidden && have !== picked.map((p) => p.text).join("|")) renderPicks();
  }

  // make the preselected state obvious: each prefilled field wears a tick and a green edge until
  // it is changed, and the banner lists the choices as small filled pills that jump to their field
  function markPicked() {
    picked.length = 0;
    const v = form.querySelector('input[name="venue"]:checked');
    if (v) picked.push({ field: v.closest("[data-field]"), ctl: v, text: v.nextElementSibling ? v.nextElementSibling.textContent.trim() : v.value });
    ["service", "stage"].forEach((id) => {
      const s = form.querySelector("#f-" + id);
      if (s && s.value && s.value !== "not-sure") picked.push({ field: s.closest("[data-field]"), ctl: s, text: s.options[s.selectedIndex].text.trim() });
    });
    picked.forEach((p) => p.field && p.field.classList.add("is-prefilled"));
  }
  function renderPicks() {
    if (!picksEl) return;
    picksEl.replaceChildren(...picked.map((p) => {
      const li = d.createElement("li"), a = d.createElement("a");
      a.className = "prefill__pick"; a.href = "#" + (p.field && p.field.id ? p.field.id : p.ctl.id);
      a.textContent = p.text;
      li.appendChild(a); return li;
    }));
    picksEl.hidden = !picked.length;
  }
  // a pill jumps to its field and focuses the chosen control (without JS it is a plain anchor)
  picksEl && picksEl.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a.prefill__pick");
    const target = a && d.getElementById(decodeURIComponent(a.hash.slice(1)));
    if (!target) return;
    e.preventDefault();
    const field = target.closest("[data-field]") || target;
    // the chosen chip, not the first one (a selector list would match in document order)
    const ctl = target.matches("input, select, textarea") ? target
      : field.querySelector("input:checked") || field.querySelector("select, textarea, input:not([type=hidden])") || target;
    scrollToEl(field);
    ctl.focus({ preventScroll: true });
  });
  // a prefilled field that the visitor changes is simply theirs now
  form.addEventListener("change", (e) => {
    const f = e.target.closest && e.target.closest(".is-prefilled");
    if (f) f.classList.remove("is-prefilled");
  });

  clearBtn && clearBtn.addEventListener("click", () => {
    form.reset();
    $("#f-from").value = ""; $("#f-item").value = "";   // hidden inputs keep programmatic values through reset()
    setCurrency("INR");
    updateCount();
    $$("[data-field]", form).forEach((f) => { setError(f, ""); delete f.dataset.dirty; });
    hideSummary();
    state.from = ""; state.itemName = "";
    banner.hidden = true;
    d.documentElement.classList.remove("has-prefill");
    $$(".is-prefilled", form).forEach((f) => f.classList.remove("is-prefilled"));
    // from scratch means from scratch: forget the remembered room too (a reload stays blank)
    MEMORY.forEach((k) => { try { sessionStorage.removeItem(k); } catch (_) {} });
    try { history.replaceState(history.state, "", location.pathname); } catch (_) {}
    const name = $("#f-name");
    name && name.focus();
  });

  /* ---------------------------------------------------------------- validation */
  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const phoneOk = (v) => /^[+()\-.\s\d]+$/.test(v) && (v.match(/\d/g) || []).length >= 8 && (v.match(/\d/g) || []).length <= 15;

  function check(field) {
    const id = field.dataset.field;
    const rules = (field.dataset.rules || "").split(",").filter(Boolean);
    const ctl = $(".field__control", field);
    if (!rules.length || !ctl) return "";
    const v = ctl.value.trim(), m = MSG[id] || {};
    if (rules.includes("required") && !v) return m.required;
    if (rules.includes("email") && v && !EMAIL.test(v)) return m.invalid;
    if (rules.includes("phone") && v && !phoneOk(v)) return m.invalid;
    const max = rules.find((r) => r.startsWith("max:"));
    if (max && ctl.value.length > +max.slice(4)) return m.tooLong;
    return "";
  }

  function setError(field, msg) {
    const ctl = $(".field__control", field), err = $(".field__error", field);
    if (!ctl || !err) return;
    const ids = (ctl.getAttribute("aria-describedby") || "").split(/\s+/).filter((x) => x && x !== err.id);
    field.classList.toggle("is-invalid", !!msg);
    if (msg) {
      err.textContent = msg; err.hidden = false;
      ctl.setAttribute("aria-invalid", "true");
      ids.unshift(err.id);
    } else {
      err.textContent = ""; err.hidden = true;
      ctl.removeAttribute("aria-invalid");
    }
    if (ids.length) ctl.setAttribute("aria-describedby", ids.join(" "));
    else ctl.removeAttribute("aria-describedby");
  }

  const validated = () => $$("[data-field][data-rules]", form).filter((f) => f.dataset.rules);

  function renderSummary(errors) {
    summaryTitle.textContent = errors.length === 1 ? SUMMARY.one : SUMMARY.many.replace("{n}", errors.length);
    summaryList.replaceChildren(...errors.map(({ field, msg }) => {
      const ctl = $(".field__control", field);
      const li = d.createElement("li"), a = d.createElement("a");
      a.href = "#" + ctl.id; a.textContent = msg; a.dataset.for = ctl.id;
      li.appendChild(a); return li;
    }));
    summary.hidden = false;
  }
  function hideSummary() { summary.hidden = true; summaryList.replaceChildren(); }
  // keep an open summary honest as fields are fixed
  function refreshSummary() {
    if (summary.hidden) return;
    const errors = validated().map((field) => ({ field, msg: check(field) })).filter((e) => e.msg);
    if (!errors.length) hideSummary(); else renderSummary(errors);
  }

  // blur: validate anything the visitor has touched (don't shout at a field just tabbed past)
  form.addEventListener("focusout", (e) => {
    const field = e.target.closest && e.target.closest("[data-field]");
    if (!field || !field.dataset.rules) return;
    if (field.dataset.dirty || field.classList.contains("is-invalid")) { setError(field, check(field)); refreshSummary(); }
  });
  // typing: once a field is marked wrong, clear it the moment it's right
  form.addEventListener("input", (e) => {
    const field = e.target.closest && e.target.closest("[data-field]");
    if (!field) return;
    if (e.target.value && e.target.value.trim()) field.dataset.dirty = "1";
    if (field.classList.contains("is-invalid") || (field.dataset.field === "message" && check(field))) {
      setError(field, check(field)); refreshSummary();
    }
  });

  // summary links: focus the control itself (not a scroll-to-anchor, which would break the tab order)
  summary.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-for]");
    if (!a) return;
    e.preventDefault();
    const ctl = d.getElementById(a.dataset.for);
    if (!ctl) return;
    scrollToEl(ctl.closest("[data-field]") || ctl);
    ctl.focus({ preventScroll: true });
  });

  /* ---------------------------------------------------------------- submit */
  function setSending(on) {
    state.sending = on;
    form.classList.toggle("is-sending", on);
    form.setAttribute("aria-busy", String(on));
    submitLabel.textContent = on ? SENDING : SEND;
    if (on) submit.setAttribute("aria-disabled", "true"); else submit.removeAttribute("aria-disabled");
    if (status) status.textContent = on ? SENDING : "";
  }

  function showSuccess(preview) {
    const nameVal = ($("#f-name") && $("#f-name").value.trim()) || "";
    const first = nameVal.split(/\s+/)[0] || "there";
    const fromMenu = !!state.itemName && (state.from === "menu-card" || state.from === "services");
    const title = $("#done-title"), body = $("#done-body");
    if (fromMenu) {
      title.innerHTML = "Order’s <em>in</em>.";
      body.textContent = `Thanks, ${first}. ${state.itemName}, noted. We’ll reply within two working days with a few questions and a time to talk.`;
      $("#done-secondary").hidden = true;
      $("#done-button-label").textContent = "Back to the street";
      $("#done-button").setAttribute("href", "index.html");
    } else {
      body.textContent = `Thanks, ${first}. We read every enquiry ourselves, and you’ll hear from one of the team within two working days — sooner if you mentioned a lease deadline.`;
    }
    $("#done-preview").hidden = !preview;
    form.hidden = true; banner.hidden = true;
    done.hidden = false;
    setSending(false);
    if (status) status.textContent = "";
    const wrapTop = done.closest(".contact-body__form") || done;
    if (wrapTop.getBoundingClientRect().top < 0 || wrapTop.getBoundingClientRect().top > innerHeight * 0.6) scrollToEl(wrapTop);
    title.focus({ preventScroll: true });
    if (w.ScrollTrigger) requestAnimationFrame(() => w.ScrollTrigger.refresh());
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.sending) return;
    netErr.textContent = "";

    const errors = [];
    validated().forEach((field) => {
      const msg = check(field);
      setError(field, msg);
      if (msg) errors.push({ field, msg });
    });
    if (errors.length) {
      renderSummary(errors);
      scrollToEl(summary);
      summary.focus({ preventScroll: true });
      return;
    }
    hideSummary();

    // the honeypot caught something: look sent, send nothing
    const hp = form.querySelector('input[name="bot-field"]');
    if (hp && hp.value) { showSuccess(false); return; }

    setSending(true);
    const body = new URLSearchParams(new FormData(form)).toString();
    const local = location.protocol === "file:";
    try {
      let ok = false;
      if (!local) {
        const ctrl = "AbortController" in w ? new AbortController() : null;
        const timer = ctrl && setTimeout(() => ctrl.abort(), 15000);
        // Netlify Forms: an urlencoded POST (with form-name) to the site root, as its docs do for AJAX
        const res = await fetch("/", {
          method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
          signal: ctrl ? ctrl.signal : undefined,
        });
        clearTimeout(timer);
        ok = res.ok;
      }
      // not ok = no Netlify behind this preview (e.g. a local server): still show the success state
      showSuccess(!ok);
    } catch (err) {
      setSending(false);
      netErr.textContent = NETWORK;
    }
  });

  /* ---------------------------------------------------------------- boot */
  prefill();
  updateCount();
  // arrived back from a no-JS Netlify post (action="contact.html?sent=1")
  if (new URLSearchParams(location.search).get("sent") === "1") showSuccess(false);
})(window, document);
