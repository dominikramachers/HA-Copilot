"use strict";
// Updatepläne (ab 0.69.0): ein Zeitplan mit Zeitfenster für mehrere Server, Reiter „Automatische Updates“ der Seite „Server“.
// Nutzt die Hilfen aus servers.js (srvUi, srvAuSwitch, srvAuSelect, srvAuWhen, srvDot, srvAgo …) und app.js (node, api, tr, toast, openSheet, closeSheet).
//
// Ein Plan legt Umfang, Tag, Zeitfenster und Karenzzeit für alle seine Server fest. Die Server kommen nacheinander dran, gleichmäßig über das
// Fenster verteilt. Ein Server gehört zu höchstens einem Plan; solange er drin ist, ruht sein eigener Zeitplan (er bleibt gespeichert).
// Eingeschaltet wird nur hier (die KI im Chat kann es nicht).

const srvPlan = { data: null, error: "", open: new Set() }; // open: aufgeklappte Serverlisten (bleiben bei der Aktualisierung offen)

// Einklappbare Liste: zu ist nur eine Zeile (Titel, Anzahl, Kurzfassung) zu sehen.
function srvPlanFold(key, title, count, brief, list) {
  const box = node("details", "srv-plan-fold");
  box.open = srvPlan.open.has(key);
  box.addEventListener("toggle", () => { if (box.open) srvPlan.open.add(key); else srvPlan.open.delete(key); });
  const head = node("summary", "srv-plan-foldhead");
  head.append(node("span", "srv-plan-foldtitle", title), node("span", "srv-count", String(count)));
  if (brief) head.append(node("span", "srv-plan-foldbrief", brief));
  box.append(head, list);
  return box;
}

async function srvPlansFetch() {
  try {
    srvPlan.data = await api("api/servers/update-plans");
    srvPlan.error = "";
  } catch (err) {
    srvPlan.error = errorText(err, tr("Die Updatepläne sind gerade nicht erreichbar."));
  }
}

async function srvPlanAct(path, method, body, done) {
  try {
    await api(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (done) toast(done);
  } catch (err) {
    toast(errorText(err, tr("Das hat nicht geklappt.")));
  }
  await srvPlansFetch();
  if (state.view === "servers") renderServers();
}

function srvPlanDay(weekday) {
  return (SRV_AU_DAYS().find(([value]) => value === weekday) || [0, ""])[1];
}

function srvPlanSchedule(p) {
  const parts = [`${srvPlanDay(p.weekday)} ${p.window_start}–${p.window_end}`, p.mode === "all" ? tr("Alle Updates") : tr("Nur Sicherheit")];
  if (p.grace_days) parts.push(tr("Karenzzeit {0} Tage", p.grace_days));
  return parts.join(" · ");
}

// Wie viel Zeit hat jeder Server im Fenster?
function srvPlanSpacing(start, end, count) {
  if (!/^\d\d:\d\d$/.test(start) || !/^\d\d:\d\d$/.test(end)) return "";
  const minutes = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
  const length = (minutes(end) - minutes(start) + 1440) % 1440;
  if (length < 10 || length > 720) return tr("Das Zeitfenster muss zwischen 10 Minuten und 12 Stunden lang sein.");
  const text = length >= 120 ? tr("{0} Std. {1} Min.", Math.floor(length / 60), length % 60) : tr("{0} Min.", length);
  if (!count) return tr("Zeitfenster: {0}, die Server kommen nacheinander dran, gleichmäßig verteilt.", text);
  return tr("Zeitfenster: {0}, {1} Server kommen nacheinander dran, etwa alle {2} Min.", text, count, Math.floor(length / count));
}

// ------------------------------------------------------------- Reiter

function renderServerUpdates(wrap) {
  const d = srvPlan.data;
  const intro = node("p", "srv-note", tr("Ein Updateplan aktualisiert mehrere Server nacheinander in einem Zeitfenster, zum Beispiel jede Nacht zwischen 2 und 3 Uhr. Server ohne Plan behalten ihren eigenen Zeitplan."));
  wrap.append(intro);
  if (srvPlan.error) wrap.append(node("p", "srv-au-banner bad", srvPlan.error));
  if (!d) {
    if (!srvPlan.error) wrap.append(node("p", "skills-status", tr("Wird geladen …")));
    return;
  }

  const head = node("div", "srv-plan-head");
  head.append(node("h3", "", tr("Updatepläne")));
  const add = node("button", "pill primary", tr("Neuer Plan"));
  add.type = "button";
  add.disabled = d.plans.length >= d.limits.plans_max || !d.servers.length;
  add.addEventListener("click", () => { srvPlanSheet(null).catch(() => {}); });
  head.append(add);
  wrap.append(head);

  if (!d.servers.length) wrap.append(node("p", "srv-note", tr("Es gibt noch keinen bestätigten Server. Sobald einer da ist, kannst du hier einen Plan anlegen.")));
  else if (!d.plans.length) {
    const empty = node("section", "srv-plan srv-plan-empty");
    empty.append(node("h3", "", tr("Noch kein Updateplan")),
      node("span", "srv-hint", tr("Lege einen Plan an, wähle seine Server und das Zeitfenster. Ich aktualisiere sie dann nacheinander.")));
    wrap.append(empty);
  }
  for (const plan of d.plans) wrap.append(srvPlanCard(plan, d));

  const free = d.servers.filter((s) => !s.plan);
  if (free.length) {
    const box = node("section", "srv-plan srv-plan-free");
    const title = node("div", "srv-plan-title");
    const h = node("h3", "", tr("Server ohne Plan"));
    h.append(node("span", "srv-count", String(free.length)));
    title.append(h, node("span", "srv-hint", tr("Sie folgen ihrem eigenen Zeitplan oder aktualisieren sich nicht automatisch.")));
    const top = node("div", "srv-plan-top");
    top.append(title);
    const list = node("ul", "srv-plan-list");
    for (const s of free) list.append(srvPlanFreeRow(s, d));
    box.append(top, list);
    wrap.append(box);
  }
}

function srvPlanCard(plan, d) {
  const card = node("section", `srv-plan${plan.enabled ? "" : " off"}`);
  card.dataset.plan = plan.id;
  const top = node("div", "srv-plan-top");
  const title = node("div", "srv-plan-title");
  title.append(node("h3", "", plan.name), node("span", "srv-hint", srvPlanSchedule(plan)));
  const edit = node("button", "pill ghost small", tr("Bearbeiten"));
  edit.type = "button";
  edit.addEventListener("click", () => { srvPlanSheet(plan).catch(() => {}); });
  const controls = node("div", "srv-plan-controls");
  controls.append(edit, srvAuSwitch(plan.enabled, tr("Plan {0} einschalten", plan.name), false, () => srvPlanAct(`api/servers/update-plans/${plan.id}`, "PUT", { enabled: !plan.enabled })));
  top.append(title, controls);
  card.append(top);

  if (plan.enabled) {
    const next = node("div", "srv-au-next");
    next.append(node("span", "", plan.skip_next ? tr("Nächster Lauf: {0} (wird übersprungen)", srvAuWhen(plan.next_start)) : tr("Nächster Lauf: {0}", srvAuWhen(plan.next_start))));
    const skip = node("button", "pill ghost small", plan.skip_next ? tr("Wieder einplanen") : tr("Diesen Lauf überspringen"));
    skip.type = "button";
    skip.addEventListener("click", () => srvPlanAct(`api/servers/update-plans/${plan.id}/skip`, "POST", { skip: !plan.skip_next }));
    next.append(skip);
    card.append(next);
  } else {
    card.append(node("p", "srv-hint", tr("Der Plan ist aus: Es wird nichts automatisch installiert.")));
  }

  if (!plan.members.length) card.append(node("p", "srv-hint", tr("Noch keine Server im Plan. Mit „Bearbeiten“ fügst du welche hinzu.")));
  else {
    const list = node("ul", "srv-plan-list");
    for (const m of plan.members) list.append(srvPlanMember(plan, m));
    const problems = plan.members.filter((m) => m.paused || ["failed", "attention"].includes(m.autoupdate?.last?.status)).length;
    const brief = plan.members.map((m) => m.name).join(", ") + (problems ? ` · ${tr("{0} mit Hinweis", problems)}` : "");
    const inner = node("div", "srv-plan-foldbody");
    inner.append(list);
    const spacing = srvPlanSpacing(plan.window_start, plan.window_end, plan.members.filter((m) => !m.paused).length);
    if (spacing) inner.append(node("p", "srv-hint", spacing));
    card.append(srvPlanFold(`plan:${plan.id}`, tr("Server im Plan"), plan.members.length, brief, inner));
  }
  return card;
}

function srvPlanMember(plan, m) {
  const li = node("li", `srv-plan-row${m.paused ? " paused" : ""}`);
  li.append(node("span", "srv-plan-time", m.paused ? "–" : m.slot));
  const main = node("div", "srv-plan-main");
  const name = node("button", "srv-plan-name");
  name.type = "button";
  name.append(srvDot(m.status), node("span", "", m.name));
  name.title = tr("Automatische Updates dieses Servers öffnen");
  name.addEventListener("click", () => { srvAuOpen({ id: m.id, name: m.name }).catch(() => {}); });
  main.append(name);
  const chips = node("span", "srv-chips");
  if (m.paused) chips.append(node("span", "srv-chip warn", tr("pausiert")));
  if (m.autoupdate?.running) chips.append(node("span", "srv-chip", SRV_AU_PHASES()[m.autoupdate.running.phase] || tr("läuft")));
  else if (m.autoupdate?.last) {
    const [text, tone] = SRV_AU_STATUS()[m.autoupdate.last.status] || SRV_AU_STATUS().ok;
    const chip = node("span", `srv-chip ${tone}`, `${tr("Zuletzt")}: ${text}`);
    chip.title = `${m.autoupdate.last.summary} (${srvAgo(m.autoupdate.last.at)})`;
    chips.append(chip);
  }
  if (m.denied_locally) chips.append(node("span", "srv-chip bad", tr("lokal gesperrt")));
  else if (!m.can_change) chips.append(node("span", "srv-chip bad", tr("nur lesen")));
  if (chips.childNodes.length) main.append(chips);
  const actions = node("div", "srv-plan-actions");
  const pause = node("button", "pill ghost small", m.paused ? tr("Fortsetzen") : tr("Pausieren"));
  pause.type = "button";
  pause.title = m.paused ? tr("Diesen Server im Plan wieder aktualisieren") : tr("Diesen Server im Plan aussetzen, ohne ihn herauszunehmen");
  pause.addEventListener("click", () => srvPlanAct(`api/servers/${m.id}/update-plan/pause`, "POST", { paused: !m.paused }));
  const leave = node("button", "pill ghost small", tr("Herausnehmen"));
  leave.type = "button";
  leave.title = tr("Den Server aus dem Plan nehmen; sein eigener Zeitplan gilt dann wieder");
  leave.addEventListener("click", () => srvPlanAct(`api/servers/${m.id}/update-plan/leave`, "POST", { use_own: false }, tr("{0} ist nicht mehr im Plan.", m.name)));
  actions.append(pause, leave);
  li.append(main, actions);
  return li;
}

function srvPlanFreeRow(s, d) {
  const li = node("li", "srv-plan-row");
  const main = node("div", "srv-plan-main");
  const name = node("button", "srv-plan-name");
  name.type = "button";
  name.append(srvDot(s.status), node("span", "", s.name));
  name.title = tr("Automatische Updates dieses Servers öffnen");
  name.addEventListener("click", () => { srvAuOpen({ id: s.id, name: s.name }).catch(() => {}); });
  main.append(name);
  const chips = node("span", "srv-chips");
  chips.append(node("span", "srv-plan-state", srvAuBrief(s.autoupdate)));
  if (s.denied_locally) chips.append(node("span", "srv-chip bad", tr("lokal gesperrt")));
  else if (!s.can_change) chips.append(node("span", "srv-chip bad", tr("nur lesen")));
  main.append(chips);
  const actions = node("div", "srv-plan-actions");
  if (d.plans.length && !s.denied_locally && s.can_change) {
    const pick = srvAuSelect(tr("Zu einem Plan hinzufügen"), [["", tr("Zu Plan hinzufügen …")], ...d.plans.map((p) => [p.id, p.name])], "", (value) => {
      if (value) srvPlanAct(`api/servers/${s.id}/update-plan/join`, "POST", { plan_id: value }, tr("{0} ist jetzt im Plan.", s.name));
    });
    pick.classList.add("srv-plan-pick");
    actions.append(pick);
  }
  const setup = node("button", "pill ghost small", tr("Eigener Zeitplan"));
  setup.type = "button";
  setup.addEventListener("click", () => { srvAuOpen({ id: s.id, name: s.name }).catch(() => {}); });
  actions.append(setup);
  li.append(main, actions);
  return li;
}

// ------------------------------------------------------------- Plan anlegen und bearbeiten

async function srvPlanSheet(plan) {
  if (!srvPlan.data) await srvPlansFetch();
  const d = srvPlan.data;
  if (!d) return;
  const draft = plan
    ? { name: plan.name, enabled: plan.enabled, mode: plan.mode, weekday: plan.weekday, window_start: plan.window_start, window_end: plan.window_end, grace_days: plan.grace_days, servers: plan.members.map((m) => m.id) }
    : { name: "", enabled: false, mode: "security", weekday: 7, window_start: "02:00", window_end: "03:00", grace_days: 0, servers: [] };
  const planOf = Object.fromEntries(d.servers.map((s) => [s.id, s.plan]));
  const paused = new Set((plan?.members || []).filter((m) => m.paused).map((m) => m.id)); // pausierte Server bekommen keinen Platz im Fenster
  let hint = null;
  let list = null;
  let error = null;
  let nameInput = null;
  let armed = 0;

  const drawHint = () => {
    const text = srvPlanSpacing(draft.window_start, draft.window_end, draft.servers.filter((id) => !paused.has(id)).length);
    hint.textContent = text;
  };
  const drawServers = () => {
    list.replaceChildren();
    const chosen = draft.servers.map((id) => d.servers.find((s) => s.id === id)).filter(Boolean);
    const others = d.servers.filter((s) => !draft.servers.includes(s.id));
    const active = chosen.filter((s) => !paused.has(s.id));
    const slotOf = (s) => {
      const m = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
      const length = (m(draft.window_end) - m(draft.window_start) + 1440) % 1440;
      const at = (m(draft.window_start) + Math.floor((length * active.indexOf(s)) / Math.max(1, active.length))) % 1440;
      return `${String(Math.floor(at / 60)).padStart(2, "0")}:${String(at % 60).padStart(2, "0")}`;
    };
    const row = (s, index) => {
      const selected = index >= 0;
      const li = node("li", `srv-plan-row${selected ? "" : " free"}`);
      const blocked = !selected && (s.denied_locally || !s.can_change);
      const sw = srvAuSwitch(selected, tr("{0} gehört zum Plan", s.name), blocked, () => {
        if (selected) draft.servers = draft.servers.filter((id) => id !== s.id);
        else draft.servers = [...draft.servers, s.id];
        drawServers();
        drawHint();
      });
      li.append(sw);
      const main = node("div", "srv-plan-main");
      const name = node("span", "srv-plan-name static");
      name.append(srvDot(s.status), node("span", "", s.name));
      main.append(name);
      const other = planOf[s.id];
      if (!selected && other && other.id !== plan?.id) main.append(node("span", "srv-hint", tr("Ist jetzt in „{0}“ und wird hierher verschoben.", other.name)));
      if (blocked) main.append(node("span", "srv-hint", s.denied_locally ? tr("Auf dem Server gesperrt (auto_update=deny).") : tr("Der Server erlaubt keine Änderungen (lokale Richtlinie).")));
      li.append(main);
      if (selected) {
        li.append(node("span", "srv-plan-time", paused.has(s.id) ? tr("pausiert") : slotOf(s)));
        const order = node("div", "srv-plan-actions");
        for (const [dir, glyph, label] of [[-1, "↑", tr("Früher")], [1, "↓", tr("Später")]]) {
          const b = node("button", "pill ghost small", glyph);
          b.type = "button";
          b.setAttribute("aria-label", `${s.name}: ${label}`);
          b.title = label;
          b.disabled = index + dir < 0 || index + dir >= draft.servers.length;
          b.addEventListener("click", () => {
            const next = [...draft.servers];
            [next[index], next[index + dir]] = [next[index + dir], next[index]];
            draft.servers = next;
            drawServers();
          });
          order.append(b);
        }
        li.append(order);
      }
      return li;
    };
    chosen.forEach((s, i) => list.append(row(s, i)));
    if (others.length) {
      const more = node("li", "srv-plan-morefold");
      const inner = node("ul", "srv-plan-list");
      for (const s of others) inner.append(row(s, -1));
      more.append(srvPlanFold("sheet-more", tr("Weitere Server hinzufügen"), others.length, "", inner));
      list.append(more);
    }
    if (!d.servers.length) list.append(node("li", "srv-hint", tr("Es gibt noch keinen bestätigten Server.")));
  };

  const closed = openSheet({
    title: plan ? tr("Updateplan bearbeiten") : tr("Neuer Updateplan"), sub: plan ? plan.name : "", ok: tr("Speichern"), wide: true,
    panel: (body) => {
      body.classList.add("srv-au", "srv-plan-sheet");
      const nameField = node("label", "srv-au-field");
      nameField.append(node("span", "srv-au-label", tr("Name")));
      nameInput = node("input", "field");
      nameInput.type = "text";
      nameInput.maxLength = 60;
      nameInput.value = draft.name;
      nameInput.placeholder = tr("z. B. Nachts, Mo–Fr");
      nameInput.addEventListener("input", () => { draft.name = nameInput.value; });
      nameField.append(nameInput);
      body.append(nameField);

      const head = node("div", "srv-au-switchrow");
      const label = node("div", "srv-au-switchtext");
      label.append(node("b", "", tr("Plan eingeschaltet")), node("span", "srv-hint", tr("Aus: Der Plan ist angelegt, aber es wird nichts automatisch installiert.")));
      const sw = srvAuSwitch(draft.enabled, tr("Plan eingeschaltet"), false, () => {
        draft.enabled = !draft.enabled;
        sw.setAttribute("aria-checked", String(draft.enabled));
      });
      head.append(label, sw);
      body.append(head);

      const grid = node("div", "srv-au-grid srv-plan-grid");
      grid.append(srvAuSelect(tr("Umfang"), [["security", tr("Nur Sicherheit")], ["all", tr("Alle Updates")]], draft.mode, (v) => { draft.mode = v; }));
      grid.append(srvAuSelect(tr("Tag"), SRV_AU_DAYS(), draft.weekday, (v) => { draft.weekday = Number(v); }));
      for (const [key, text] of [["window_start", tr("Fenster von")], ["window_end", tr("Fenster bis")]]) {
        const f = node("label", "srv-au-field");
        f.append(node("span", "srv-au-label", text));
        const input = node("input", "field");
        input.type = "time";
        input.value = draft[key];
        input.addEventListener("change", () => { if (/^\d\d:\d\d$/.test(input.value)) { draft[key] = input.value; drawHint(); drawServers(); } });
        f.append(input);
        grid.append(f);
      }
      grid.append(srvAuSelect(tr("Karenzzeit"), SRV_AU_GRACE.map((n) => [n, n ? tr("{0} Tage", n) : tr("keine")]), draft.grace_days, (v) => { draft.grace_days = Number(v); }));
      body.append(grid);
      hint = node("p", "srv-hint");
      body.append(hint);
      body.append(node("p", "srv-hint", tr("Die Karenzzeit gilt nur für normale Updates. Sicherheitsupdates warten nie. Was ein Server nicht automatisch bekommen soll, stellst du weiter an dem Server ein.")));

      body.append(node("h4", "", tr("Server im Plan")));
      body.append(node("p", "srv-hint", tr("Die Reihenfolge bestimmt die Uhrzeit: Der erste Server kommt zuerst dran. Es läuft immer nur einer gleichzeitig.")));
      list = node("ul", "srv-plan-list");
      body.append(list);
      error = node("p", "srv-au-banner bad");
      error.hidden = true;
      body.append(error);
      if (plan) {
        const del = node("button", "pill ghost danger-text", tr("Plan löschen"));
        del.type = "button";
        del.addEventListener("click", async () => {
          if (!armed) {
            del.textContent = tr("Wirklich löschen?");
            del.classList.add("danger");
            armed = setTimeout(() => { armed = 0; del.textContent = tr("Plan löschen"); del.classList.remove("danger"); }, 3500);
            return;
          }
          clearTimeout(armed);
          try {
            await api(`api/servers/update-plans/${plan.id}`, { method: "DELETE" });
            toast(tr("Der Plan wurde gelöscht. Seine Server haben wieder ihren eigenen Zeitplan."));
            closeSheet(null);
            await srvPlansFetch();
            await srvLoad(true);
          } catch (err) {
            error.textContent = errorText(err, tr("Das hat nicht geklappt."));
            error.hidden = false;
          }
        });
        body.append(del);
      }
      drawHint();
      drawServers();
    },
    onOk: async () => {
      error.hidden = true;
      if (!draft.name.trim()) {
        error.textContent = tr("Der Plan braucht einen Namen.");
        error.hidden = false;
        nameInput.focus();
        return false;
      }
      try {
        await api(plan ? `api/servers/update-plans/${plan.id}` : "api/servers/update-plans", { method: plan ? "PUT" : "POST", body: JSON.stringify({ ...draft, name: draft.name.trim() }) });
      } catch (err) {
        error.textContent = errorText(err, tr("Das hat nicht geklappt."));
        error.hidden = false;
        return false;
      }
      toast(plan ? tr("Der Plan wurde gespeichert.") : tr("Der Plan wurde angelegt."));
      await srvPlansFetch();
      await srvLoad(true);
      return true;
    },
  });
  await closed;
  clearTimeout(armed);
}

// Vom Fenster eines Servers aus zum Plan springen: Reiter öffnen, dann die Einzelheiten des Plans.
async function srvOpenPlan(planId) {
  closeSheet(null);
  await openServers("updates");
  const plan = srvPlan.data?.plans.find((p) => p.id === planId);
  if (!plan) return;
  document.querySelector(`.srv-plan[data-plan="${planId}"]`)?.scrollIntoView({ block: "center" });
  await srvPlanSheet(plan);
}

// ------------------------------------------------------------- Im Fenster eines Servers (srvAuDraw)

async function srvAuPlanAct(action, body, done) {
  const id = srvAu.id;
  if (!id || srvAu.busy) return;
  srvAu.busy = true;
  srvAuDraw();
  try {
    await api(`api/servers/${id}/update-plan/${action}`, { method: "POST", body: JSON.stringify(body) });
    if (done) toast(done);
    srvAu.error = "";
  } catch (err) {
    srvAu.error = errorText(err, tr("Das hat nicht geklappt."));
  }
  srvAu.busy = false;
  if (srvAu.id === id) await srvAuLoad();
}

// Der Server folgt einem Plan: Hinweis mit Link zum Plan, Pause, „Aus dem Plan nehmen“ und „Eigenen Zeitplan nutzen“.
function srvAuPlanBox(d, locked) {
  const plan = d.plan;
  const box = node("section", "srv-au-set srv-au-plan");
  const head = node("div", "srv-au-switchrow");
  const label = node("div", "srv-au-switchtext");
  label.append(node("b", "", tr("Dieser Server folgt dem Updateplan „{0}“", plan.name)), node("span", "srv-hint", srvPlanSchedule(plan)));
  const open = node("button", "pill ghost small", tr("Plan ansehen"));
  open.type = "button";
  open.addEventListener("click", () => { srvOpenPlan(plan.id).catch(() => {}); });
  head.append(label, open);
  box.append(head);

  if (d.denied_locally) box.append(node("p", "srv-au-banner", tr("Auf dem Server ist die automatische Aktualisierung gesperrt (auto_update=deny in der lokalen Richtlinie). Das lässt sich nur dort ändern.")));
  else if (!d.can_change) box.append(node("p", "srv-au-banner", tr("Der Server erlaubt keine Änderungen (lokale Richtlinie ki_access=read). Ohne Erlaubnis dort kann ich nichts installieren.")));
  if (plan.paused) box.append(node("p", "srv-au-banner", tr("In diesem Plan pausiert: Der Plan lässt diesen Server aus, bis du ihn fortsetzt.")));
  else if (!plan.enabled) box.append(node("p", "srv-au-banner", tr("Der Plan ist ausgeschaltet. Es wird nichts automatisch installiert.")));
  else {
    const next = node("div", "srv-au-next");
    next.append(node("span", "", d.skip_next ? tr("Nächster Lauf: {0} (wird übersprungen)", srvAuWhen(d.next_run)) : tr("Nächster Lauf: {0}", srvAuWhen(d.next_run))));
    const skip = node("button", "pill ghost small", d.skip_next ? tr("Wieder einplanen") : tr("Diesen Lauf überspringen"));
    skip.type = "button";
    skip.disabled = locked;
    skip.addEventListener("click", () => srvAuAct("/skip", "POST", { skip: !d.skip_next }));
    next.append(skip);
    box.append(next);
    box.append(node("p", "srv-hint", tr("Dein Zeitpunkt im Plan: {0} (Platz {1} von {2}). Die Server kommen nacheinander dran.", plan.slot, plan.position + 1, plan.count)));
  }

  const own = d.settings;
  box.append(node("p", "srv-hint", own.enabled
    ? tr("Dein eigener Zeitplan ({0}, {1}) ruht, solange der Server im Plan ist.", SRV_AU_DAYS().find(([v]) => v === own.weekday)?.[1] || "", own.at_time)
    : tr("Dein eigener Zeitplan ist aus und bleibt es, wenn du den Server aus dem Plan nimmst.")));

  const foot = node("div", "sched-foot");
  const action = (text, cls, title, run) => {
    const b = node("button", `pill ${cls}`, text);
    b.type = "button";
    b.title = title;
    b.disabled = locked;
    b.addEventListener("click", run);
    return b;
  };
  foot.append(
    action(plan.paused ? tr("Im Plan fortsetzen") : tr("Im Plan pausieren"), "ghost", tr("Diesen Server im Plan aussetzen, ohne ihn herauszunehmen"), () => srvAuPlanAct("pause", { paused: !plan.paused })),
    action(tr("Aus dem Plan nehmen"), "ghost", tr("Den Server aus dem Plan nehmen; sein eigener Zeitplan gilt dann wieder"), () => srvAuPlanAct("leave", { use_own: false }, tr("Der Server ist nicht mehr im Plan."))),
    action(tr("Eigenen Zeitplan nutzen"), "primary", tr("Aus dem Plan nehmen und den eigenen Zeitplan einschalten"), () => srvAuPlanAct("leave", { use_own: true }, tr("Der Server nutzt jetzt seinen eigenen Zeitplan."))),
  );
  box.append(foot);
  return box;
}

// Der Server hat keinen Plan: einem Plan hinzufügen (nur wenn es Pläne gibt und der Server es erlaubt).
function srvAuJoinRow(d, locked) {
  if (!d.plans?.length || d.denied_locally || !d.can_change) return null;
  const row = node("div", "srv-au-joinrow");
  const pick = srvAuSelect(tr("Zu einem Updateplan hinzufügen"), [["", tr("Plan wählen …")], ...d.plans.map((p) => [p.id, p.name])], "",
    (value) => { if (value) srvAuPlanAct("join", { plan_id: value }, tr("Der Server ist jetzt im Plan. Sein eigener Zeitplan ruht.")); }, locked);
  row.append(pick, node("span", "srv-hint", tr("Im Plan kommt der Server nacheinander mit den anderen dran. Dein eigener Zeitplan bleibt gespeichert.")));
  return row;
}
