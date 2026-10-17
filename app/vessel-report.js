/* Vessel report UI layer. Reorganises the existing elements; does not alter scores/data. */
(() => {
  "use strict";
  const $v = s => document.querySelector(s);
  const isPreview = () => window.SFP_PREVIEW === true;
  const escapeV = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const hasLiveAI = () => typeof sample !== "undefined" && !!sample;
  let intro, details, evidenceGrid, supportSide, chat, chatNote, suggestion, messages, askInput;
  function initialise() {
    const main = $v("#vessel");
    if (!main || $v("#vessel-intro")) return;
    $v("#back").textContent = "← All vessels";
    intro = document.createElement("div");
    intro.id = "vessel-intro";
    intro.className = "vessel-intro";
    intro.innerHTML = '<div><div class="eyebrow">SotonShip / Vessel intelligence</div><h2>Vessel risk report</h2><p>A clearer decision, with the evidence one step away.</p></div><span class="intro-status">90-day outlook · Analyst review</span>';
    main.querySelector(".grid-vessel").before(intro);
    const actions = document.createElement("div");
    actions.className = "vessel-actions";
    actions.innerHTML = '<button type="button" id="vessel-watch" aria-pressed="false">☆ Save to watchlist</button><button type="button" id="vessel-export">↗ Save as PDF</button><span id="watch-notice" class="watch-notice" role="status" aria-live="polite"></span>';
    intro.append(actions);
    const watchKey = "sfp_vessel_watchlist_v1";
    const readWatch = () => { try { const x = JSON.parse(localStorage.getItem(watchKey) || "[]"); return Array.isArray(x) ? x : []; } catch { return []; } };
    const refreshWatch = () => {
      const saved = readWatch().includes(location.hash.slice(8));
      const btn = $v("#vessel-watch");
      if (!btn) return;
      btn.textContent = saved ? "★ Saved to watchlist" : "☆ Save to watchlist";
      btn.setAttribute("aria-pressed", String(saved));
    };
    $v("#vessel-watch").addEventListener("click", () => {
      const imo = location.hash.slice(8), list = readWatch();
      const next = list.includes(imo) ? list.filter(x=>x!==imo) : [...list,imo];
      try { localStorage.setItem(watchKey, JSON.stringify(next)); refreshWatch(); $v("#watch-notice").textContent = next.includes(imo) ? "Saved in this browser" : "Removed from watchlist"; }
      catch { $v("#watch-notice").textContent = "Unable to save on this device"; }
    });
    $v("#vessel-export").addEventListener("click", () => window.print());
    window.addEventListener("beforeprint", () => {
      const d=$v("#vessel-details");
      if(d && !d.open){ d.open=true; d.dataset.printOpened="true"; }
    });
    window.addEventListener("afterprint", () => {
      const d=$v("#vessel-details");
      if(d?.dataset.printOpened==="true"){ d.open=false; delete d.dataset.printOpened; }
    });
    window.addEventListener("hashchange", refreshWatch);
    refreshWatch();
    $v("#card").classList.add("vessel-left");
    $v("#chat").parentElement.classList.add("vessel-right");
    const section = document.createElement("section");
    section.className = "evidence-section";
    section.innerHTML = '<details class="evidence-details" id="vessel-details"><summary><span><strong>Supporting evidence & vessel details</strong><span class="small">Movement map, model drivers, dated events, history, coverage and financial exposure</span></span><span class="evidence-toggle" aria-hidden="true"></span></summary><div class="evidence-inner" id="evidence-grid"><section class="stack support-side" id="vessel-support"></section></div></details>';
    main.querySelector(".grid-vessel").after(section);
    evidenceGrid = section.querySelector("#evidence-grid");
    supportSide = section.querySelector("#vessel-support");
    const report = $v("#report");
    evidenceGrid.insertBefore(report, supportSide);
    chat = $v("#chat"); chat.hidden = false;
    chat.querySelector("h2")?.remove();
    chatNote = $v("#chatNote");
    suggestion = $v("#suggest");
    messages = $v("#msgs");
    askInput = $v("#askBox");
    const top = document.createElement("div");
    top.className = "chat-topline";
    top.innerHTML = '<div><div class="chat-kicker">Your research copilot</div><h2>Ask the vessel analyst</h2></div><div class="chat-mode" id="chat-mode">Checking access</div>';
    const body = document.createElement("div");
    body.className = "chat-body";
    const compose = document.createElement("div");
    compose.className = "chat-input-wrap";
    compose.append($v("#askForm"));
    compose.insertAdjacentHTML("beforeend",'<p class="chat-disclaimer">Decision support only · Always verify dates, sources and sanctions lists.</p>');
    chatNote.classList.add("chat-helper");
    body.append(chatNote, messages, suggestion, compose);
    chat.append(top, body);
    const form = $v("#askForm");
    form.addEventListener("submit", e => {
      if (isPreview() || !hasLiveAI()) {
        e.preventDefault(); e.stopImmediatePropagation();
        answerOffline();
      }
    }, true);
    askInput.addEventListener("keydown", e => {
      if ((isPreview() || !hasLiveAI()) && e.key === "Enter" && !e.shiftKey) {
        e.preventDefault(); e.stopImmediatePropagation(); answerOffline();
      }
    }, true);
    new MutationObserver(() => { if (chat.hidden) chat.hidden = false; }).observe(chat, { attributes:true, attributeFilter:["hidden"] });
  }
  function shortReason(r) {
    if (r?.title) return {title:String(r.title),description:String(r.text || "See detailed evidence below.")};
    return {title:String(r?.label || "Behavioural signal"),description:r?.value != null ? "Observed value: " + String(r.value) + ". See the model drivers below." : "See the model drivers below."};
  }
  function keyReasons(v) {
    if (v.status === "sanctioned") return [{title:"Appears on a sanctions list",description:"Review the dated list entries and check current restrictions before proceeding."}];
    if (v.status === "no_ais") return [{title:"Insufficient movement data",description:"A reliable behavioural score cannot be computed from the sampled AIS data."}];
    const items = (v.reasons || []).slice(0,3).map(shortReason);
    if (items.length) return items;
    const positives = (v.drivers || []).filter(d => d.contrib > 0).sort((a,b)=>b.contrib-a.contrib);
    if (positives.length) return positives.slice(0,3).map(shortReason);
    return [{title:"No dominant positive risk signal",description:"Available sampled evidence does not identify a leading model driver. This does not imply compliance."}];
  }
  function enhance(imo) {
    const current = location.hash.slice(8);
    if (current !== String(imo)) return;
    const v = byImo.get(String(imo));
    if (!v || !$v("#card")?.querySelector(".panel") || !$v("#report")) return;
    initialise();
    const card = $v("#card"), panels = [...card.children];
    const hero = panels.shift();
    if (!hero) return;
    hero.classList.add("vessel-hero");
    const reasons = keyReasons(v), [decision, next] = action(v);
    const list = '<div class="vessel-subheading"><h2>Key risk indicators</h2><a href="#vessel-details" class="small" id="jump-evidence">Review evidence ↓</a></div>' +
      '<ul class="reason-list">' + reasons.map((r,i) => '<li><span class="reason-icon" aria-hidden="true">'+(i+1)+'</span><div><strong>'+escapeV(r.title)+'</strong><span class="reason-desc">'+escapeV(r.description)+'</span></div></li>').join("")+'</ul>' +
      '<div class="decision"><span class="decision-label">Recommended next step</span><strong>'+escapeV(decision)+'</strong><p>'+escapeV(next)+'</p></div>';
    hero.insertAdjacentHTML("beforeend",list);
    const evidenceLink = hero.querySelector("#jump-evidence");
    evidenceLink.addEventListener("click", e => {
      e.preventDefault();
      const drawer = $v("#vessel-details");
      drawer.open = true;
      drawer.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});
    });
    supportSide.replaceChildren(...panels);
    const title = intro.querySelector("p");
    title.textContent = (v.status === "unsanctioned" ? "90-day sanctions-risk estimate" : "Sanctions and vessel-evidence review") + " · Snapshot " + (D.snapshot || "unspecified");
    const preview = isPreview();
    const mode = $v("#chat-mode");
    mode.textContent = preview ? "Guided demo · no AI" : hasLiveAI() ? "AI available" : "AI connection required";
    chatNote.textContent = preview ? "Choose a question to explore this fictional vessel. Replies below are scripted from demo data, not produced by a live AI model." :
      hasLiveAI() ? "Ask follow-up questions grounded in this vessel's dated evidence and sources." :
      "The analyst assistant requires a supported Claude runtime. The report and evidence below remain available.";
    if (!messages.children.length) {
      const hi = document.createElement("div");
      hi.className = "msg bot";
      hi.textContent = preview ? "Hello! I'm a guided demo of the vessel analyst. Choose a suggested question, or ask about the fictional risk signals, voyage history or next steps." :
        "Welcome. Ask about this vessel's risk indicators, movement history or what to investigate next.";
      messages.append(hi);
    }
    suggestion.querySelectorAll("button").forEach(b => {
      if (!hasLiveAI() || preview) b.onclick = () => { askInput.value = b.textContent; answerOffline(); };
    });
  }
  function scriptedReply(v, q) {
    const reasons=keyReasons(v), [decision,next]=action(v);
    const proof=(v.evidence||[]).slice(0,3);
    if (/history|route|movement|ais|map|location|where|port|track/i.test(q)) {
      const last = v.last_pos ? "Last recorded position in this fictional data: "+String(v.last_pos.lat)+", "+String(v.last_pos.lon)+" ("+String(v.last_pos.ts||"date unknown")+"). " : "";
      return last + (proof.length ? "Illustrative dated events:\n"+proof.map(e=>"- "+e.date+": "+e.type+" — "+e.text).join("\n") :
        "The demo provides no notable dated movement events for this case.")+"\n\nOpen Supporting evidence for the map and history.";
    }
    if (/expos|cost|bank|finance|insur|commercial|recommend|action|do next/i.test(q)) {
      const x = exposure(v);
      return "Suggested analyst action: "+decision+". "+next+(x ? "\n\nIllustrative cargo value: "+fmtUsd(x.cargo)+". Illustrative hull value: "+fmtUsd(x.hull)+". These are assumptions, not verified valuations." : "")+
        "\n\nConsult the exposure panel below for the audience-specific breakdown.";
    }
    if (/reliab|trust|accuracy|limit|confidence|certain|probab/i.test(q)) {
      return "This risk estimate is not a finding of wrongdoing and not a guarantee of a future designation. The original model depends on the coverage and timing of its AIS and sanctions datasets. This public preview uses fictional inputs, so its percentages cannot establish predictive performance. Review the original backtests and source coverage separately.";
    }
    return (v.status === "unsanctioned" ? "Fictional 90-day model estimate: "+pct(v.p90)+". " : "Screening status: "+(STATUS_LABEL[keyOf(v)]||v.status)+". ")+
      "Main indicators:\n"+reasons.map(r=>"- "+r.title+": "+r.description).join("\n")+
      "\n\nRecommended next step: "+decision+".\n\nThese responses are scripted from fictional demo data, not live AI.";
  }
  function answerOffline() {
    const question=askInput?.value.trim();
    if (!question) return;
    const v = byImo.get(location.hash.slice(8));
    if (!v) return;
    askInput.value = "";
    addMsg("user",question);
    addMsg("bot",isPreview() ? scriptedReply(v,question) : "AI responses aren't available in this browser session. Open the evidence section for dated records and model explanations, or use the supported Claude runtime for live analysis.");
  }
  const originalRender = renderVessel;
  renderVessel = async function(imo) {
    await originalRender(imo);
    enhance(imo);
  };
  initialise();
  if (location.hash.startsWith("#vessel-")) {
    setTimeout(() => renderVessel(location.hash.slice(8)), 0);
  }
})();
