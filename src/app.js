const BASE_MODEL = JSON.parse(document.getElementById("planner-data").textContent);
const OFFLINE_LOCALES = JSON.parse(document.getElementById("offline-locales").textContent);
let MODEL;
let C;
let ROW_BY_ID;
let PLAN_BY_ID;
let CHARACTER_BY_ID;
let ROUTE_BY_ID;
const IS_OFFLINE = document.body.dataset.offline === "true";
let searchText = "";
let noticeMessage = "";
let noticeFallbackUrl = "";
let expansionVisited = false;

function bindModel(model) {
  MODEL = model;
  C = MODEL.copy;
  ROW_BY_ID = new Map(MODEL.rows.map((row) => [row.id, row]));
  PLAN_BY_ID = new Map(MODEL.plans.map((plan) => [plan.id, plan]));
  CHARACTER_BY_ID = new Map(MODEL.characters.map((character) => [character.id, character]));
  ROUTE_BY_ID = new Map(MODEL.routes.map((route) => [route.id, route]));
}

bindModel(BASE_MODEL);
if (IS_OFFLINE && OFFLINE_LOCALES[BASE_MODEL.language]) {
  OFFLINE_LOCALES[BASE_MODEL.language].content = document.getElementById("page-content").innerHTML;
}

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);
const personName = (person) => person.names[MODEL.language];
const routeName = (route) => route.names[MODEL.language];
const formatWeight = (weightQ) => (weightQ / 4).toFixed(weightQ % 4 === 0 ? 0 : weightQ % 2 === 0 ? 1 : 2);

function loadInitialState() {
  const defaults = createDefaultPayload(MODEL);
  const url = new URL(location.href);
  const explicit = url.searchParams.get("plan");
  let initial = defaults;
  let validExplicit = false;
  if (explicit !== null) {
    try {
      initial = validatePayload(decodePlanPayload(explicit), MODEL);
      expansionVisited = true;
      validExplicit = true;
    } catch (_error) {
      noticeMessage = C.invalidLink;
    }
  } else {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        initial = validatePayload(JSON.parse(saved), MODEL);
        expansionVisited = storedExpansionVisited(initial, localStorage.getItem(EXPANSION_VISITED_KEY));
      }
    } catch (_error) {
      noticeMessage = C.invalidSaved;
    }
  }
  const route = url.searchParams.get("route");
  return applyNavigationRoute(initial, route, MODEL, validExplicit);
}

let state = loadInitialState();

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    localStorage.setItem(EXPANSION_VISITED_KEY, expansionVisited ? "1" : "0");
  } catch (_error) {
    noticeMessage = C.savedFailed;
  }
}

function currentResult() {
  if (state.mode === "expand") {
    const base = PLAN_BY_ID.get(state.expand.basePlanId);
    const expanded = expandPlan(MODEL.rows, base.pairIds, MODEL.routeIds, state.expand);
    return { kind: "expand", base, planId: base.id, pairIds: expanded.pairIds, metrics: expanded, expanded };
  }
  const scope = state.mode;
  const planId = selectPlanId(MODEL, scope, state[scope]);
  const plan = PLAN_BY_ID.get(planId);
  return { kind: scope, plan, planId, pairIds: plan.pairIds, metrics: plan.metrics };
}

function statusText(row) {
  if (row.status === "story") return C.story;
  if (row.status === "free") return `${C.renown} ${row.renown} · ${C.free}`;
  if (row.status === "recruit") return `${C.renown} ${row.renown} · ${C.supportLevel} ${row.support}`;
  return C.no;
}

function conditionText(row) {
  return row.details?.[MODEL.language] || "";
}

function conditionNote(row, context = "route") {
  const detail = row.details?.[MODEL.language];
  if (context === "matrix" && !detail) return "";
  const person = CHARACTER_BY_ID.get(row.characterId);
  const aliases = Object.entries(person.names).filter(([lang]) => lang !== MODEL.language).map(([, name]) => name).join(" · ");
  const id = `condition-${context}-${row.id.replace("@", "-")}`;
  const title = `${personName(CHARACTER_BY_ID.get(row.characterId))} · ${routeName(ROUTE_BY_ID.get(row.routeId))}`;
  return `<button type="button" class="condition-trigger" popovertarget="${id}" aria-label="${escapeHtml(`${C.openCharacter}: ${title}`)}"><span aria-hidden="true">ⓘ</span></button>
    <div class="condition-popover" id="${id}" popover><header><strong>${escapeHtml(title)}</strong><button type="button" popovertarget="${id}" popovertargetaction="hide" aria-label="${escapeHtml(C.close)}">×</button></header><p class="name-translations">${escapeHtml(aliases)}</p>${detail ? `<p class="condition-note">${escapeHtml(detail)}</p>` : ""}</div>`;
}

function avatar(person) {
  return `<img class="portrait" src="${person.portrait}" width="48" height="48" alt="">`;
}

function guideUrl(routeId) {
  const prefix = MODEL.language === "zh" ? "" : `${MODEL.language}/`;
  return IS_OFFLINE ? "#original" : `${prefix}routes/${routeId}.html`;
}

function renderModes() {
  const content = [
    ["once", "modeOnce", "modeOnceDescription"],
    ["expand", "modeExpand", "modeExpandDescription"],
    ["twice", "modeTwice", "modeTwiceDescription"],
  ].map(([mode, title, description]) => `<button class="choice-card" type="button" data-mode="${mode}" data-focus-key="mode-${mode}" aria-pressed="${state.mode === mode}">
    <strong>${escapeHtml(C[title])}</strong><span>${escapeHtml(C[description])}</span></button>`).join("");
  document.getElementById("mode-controls").innerHTML = content;
}

function goalButton(goal, settings, advanced = false) {
  const selected = settings.goal === goal || (settings.goal === "custom" && settings.preference === goal);
  return `<button class="choice-card" type="button" data-goal="${goal}" data-focus-key="goal-${goal}" aria-pressed="${selected}">
    <strong>${escapeHtml(C[goal])}</strong>${advanced ? `<span>${escapeHtml(C[`${goal}Note`])}</span>` : ""}</button>`;
}

function renderNormalControls(advancedOpen = false) {
  const settings = state[state.mode];
  const balanceOptions = [
    ["cost", C.unlimited],
    ["0", state.mode === "twice" ? C.evenTwice : C.even],
    ["2", C.spread2],
  ].map(([value, label]) => `<option value="${value}"${settings.balance === value ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
  return `<h3>${escapeHtml(C.goalHeading)}</h3>
    <div class="goal-grid">${["early", "support", "compromise"].map((goal) => goalButton(goal, settings)).join("")}</div>
    <details class="advanced"${advancedOpen ? " open" : ""}><summary>${escapeHtml(C.advanced)}</summary>
      <div class="goal-grid">${goalButton("product", settings, true)}${goalButton("gate", settings, true)}</div>
      <div class="control-row">
        <label class="field"><span>${escapeHtml(C.balanceLabel)}</span><select data-setting="balance" data-focus-key="balance">${balanceOptions}</select></label>
        <label class="field"><span>${escapeHtml(C.weightQuarter)} × <output data-weight-output>${formatWeight(settings.weightQ)}</output></span>
          <input type="range" min="1" max="24" step="1" value="${settings.weightQ}" data-setting="weightQ" data-focus-key="weight"></label>
        ${settings.goal === "custom" ? `<button class="button secondary" type="button" data-action="restore-goal" data-focus-key="restore-goal">${escapeHtml(C.restoreRecommendation)}</button>` : ""}
      </div><p>${escapeHtml(C[`${settings.preference}Note`])}</p></details>`;
}

function renderExpansionControls(result, advancedOpen = false) {
  const maxBudget = MODEL.upper - result.base.pairIds.length;
  const settings = selectPlanId(MODEL, "once", state.once) === result.base.id ? state.once : null;
  const choices = [settings ? C[settings.goal] : C.custom];
  if (settings && ["early", "support", "compromise"].includes(settings.goal)) {
    choices.push(settings.balance === "cost" ? C.unlimited : settings.balance === "0" ? C.even : C.spread2);
  }
  if (settings && ["compromise", "gate"].includes(settings.goal) && settings.weightQ !== 4) {
    choices.push(`${C.weightQuarter} × ${formatWeight(settings.weightQ)}`);
  }
  const counts = MODEL.routes.map((route, index) => `<span>${escapeHtml(routeName(route))} ${result.base.metrics.recruitCounts[index]}</span>`).join("");
  return `<div class="expansion-main">
    <div class="baseline-box"><div><strong>${escapeHtml(C.baseSummary)}</strong><span class="baseline-choice">${choices.map(escapeHtml).join(" · ")}</span><div class="baseline-counts"><span>${escapeHtml(C.routeCounts)}:</span>${counts}</div></div>
      <button type="button" class="button secondary" data-action="change-baseline" data-focus-key="change-baseline">${escapeHtml(C.changeBaseline)}</button></div>
    <label class="field budget-field"><span>${escapeHtml(C.extraBudget)} (0–${maxBudget})</span>
      <input type="number" min="0" max="${maxBudget}" step="1" value="${state.expand.budget}" data-setting="budget" data-focus-key="budget"></label>
    </div>
    <details class="advanced expansion-options"${advancedOpen ? " open" : ""}><summary>${escapeHtml(C.extraOptions)}</summary>
      <label class="check"><input type="checkbox" data-setting="keepGate" data-focus-key="keep-gate"${state.expand.keepGate ? " checked" : ""}><span>${escapeHtml(C.keepGate)}</span></label>
      <label class="field"><span>${escapeHtml(C.extraWeight)} × <output data-weight-output>${formatWeight(state.expand.weightQ)}</output></span>
        <input type="range" min="1" max="24" step="1" value="${state.expand.weightQ}" data-setting="expandWeightQ" data-focus-key="expand-weight"></label>
      <p>${escapeHtml(C.extraWeightHelp)}</p>
      <details class="compact-disclosure"><summary>${escapeHtml(C.extraRules)}</summary><p>${escapeHtml(C.secondCostReason)} ${escapeHtml(C.proxyWarning)}</p><p>${escapeHtml(C.baselineLimitNote)}</p></details>
    </details>
    ${state.expand.excludedPairIds.length ? `<div><button type="button" class="button secondary" data-action="restore-extras" data-focus-key="restore-extras">${escapeHtml(C.restoreExtras)} (${state.expand.excludedPairIds.length})</button></div>` : ""}`;
}

function renderControls(result, advancedOpen = false) {
  document.getElementById("planner-controls").innerHTML = state.mode === "expand" ? renderExpansionControls(result, advancedOpen) : renderNormalControls(advancedOpen);
}

function metricCard(value, label) {
  return `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function renderSummary(result) {
  const metrics = result.metrics;
  document.getElementById("summary").innerHTML = result.kind === "expand"
    ? `<div class="join-equation"><span><strong>${result.base.pairIds.length}</strong>${escapeHtml(C.baseJoins)}</span><b aria-hidden="true">＋</b><span><strong>${metrics.added}</strong>${escapeHtml(C.extraJoins)}</span><b aria-hidden="true">＝</b><span><strong>${metrics.total}</strong>${escapeHtml(C.totalJoins)}</span></div><p class="join-count-note">${escapeHtml(C.joinCountNote)}</p>`
    : `<p class="plan-summary">${escapeHtml(C.coverageMetric)} <strong>${metrics.coverage}</strong> · ${escapeHtml(C.totalJoins)} <strong>${metrics.total}</strong></p>`;
  let stateNote = "";
  if (result.kind === "expand") {
    if (state.expand.budget === 0) stateNote = C.zeroBudget;
    else if (metrics.eligibleCount === 0) stateNote = C.noCandidates;
    else if (metrics.added === 0 && metrics.automaticIds.length) stateNote = C.allRemoved;
  }
  if (stateNote) document.getElementById("summary").insertAdjacentHTML("beforeend", `<p class="notice">${escapeHtml(stateNote)}</p>`);
}

function renderRouteTabs() {
  document.getElementById("route-tabs").innerHTML = `<div class="route-tabs" role="tablist" aria-label="Routes">
    <button type="button" role="tab" data-route="all" data-focus-key="route-all" aria-selected="${state.view.route === "all"}">${escapeHtml(C.allRoutes)}</button>
    ${MODEL.routes.map((route) => `<button type="button" role="tab" data-route="${route.id}" data-focus-key="route-${route.id}" aria-selected="${state.view.route === route.id}">${escapeHtml(routeName(route))}</button>`).join("")}</div>`;
}

function renderRoutes(result) {
  const selected = new Set(result.pairIds);
  const extraSet = result.kind === "expand" ? new Set(result.expanded.addedIds) : new Set();
  const cards = MODEL.routes.map((route) => {
    const rows = MODEL.rows.filter((row) => row.routeId === route.id && selected.has(row.id)).sort((a, b) => {
      const statusRank = { story: 0, free: 1, recruit: 2 };
      return statusRank[a.status] - statusRank[b.status] || a.renown - b.renown || a.support - b.support || a.rank - b.rank;
    });
    const items = rows.map((row) => {
      const person = CHARACTER_BY_ID.get(row.characterId);
      const isExtra = extraSet.has(row.id);
      return `<li class="route-row">${avatar(person)}<div><div class="row-title"><strong>${escapeHtml(personName(person))}</strong>
        ${isExtra ? `<span class="tag extra">${escapeHtml(C.extraTag)}</span>` : ""}</div>
        <div class="row-facts"><span class="row-copy">${escapeHtml(statusText(row))}</span>${conditionNote(row)}</div></div>
        ${isExtra ? `<button type="button" class="button danger" data-remove-extra="${row.id}" data-focus-key="remove-${row.id}" aria-label="${escapeHtml(`${C.removeExtra}: ${personName(person)} · ${routeName(route)}`)}"><span aria-hidden="true">×</span></button>` : ""}</li>`;
    }).join("");
    const routeIndex = route.index;
    const gate = result.metrics.gates[routeIndex];
    const gateDelta = result.kind === "expand" ? gate - result.expanded.baseGates[routeIndex] : 0;
    const gateLabel = `${C.maxGate} ${gate}${gateDelta > 0 ? ` (${C.previousGate} ${result.expanded.baseGates[routeIndex]})` : ""}`;
    const filtered = state.view.route !== "all" && state.view.route !== route.id;
    return `<article class="route-card" data-route-card="${route.id}" data-route-hidden="${filtered}" style="--route-color:${route.color}">
      <header><div><h3>${escapeHtml(routeName(route))}</h3><p>${escapeHtml(C.routeCounts)}: ${result.metrics.recruitCounts[routeIndex]}</p>
      <p><a href="${escapeHtml(guideUrl(route.id))}">${escapeHtml(C.routeGuide)}</a></p></div><span class="tag">${escapeHtml(gateLabel)}</span></header>
      <ul class="route-rows">${items}</ul></article>`;
  }).join("");
  const grid = document.getElementById("routes");
  grid.dataset.filtered = state.view.route !== "all";
  grid.innerHTML = cards;
}

function rosterConditions(person, selected) {
  if (person.scope === "reference") {
    return `<p>${escapeHtml(person.notes[MODEL.language])}</p>
      ${person.portraitSource ? `<p><a href="${escapeHtml(person.portraitSource)}">${escapeHtml(C.viewSource)}</a></p>` : ""}`;
  }
  return `<div class="condition-grid">${MODEL.routes.map((route) => {
    const row = MODEL.rows.find((candidate) => candidate.characterId === person.id && candidate.routeId === route.id);
    return `<div class="condition${selected.has(row.id) ? " selected" : ""}" style="--route-color:${route.color}"><strong>${selected.has(row.id) ? "✓ " : ""}${escapeHtml(routeName(route))} · ${escapeHtml(statusText(row))}</strong>
      ${conditionText(row) ? `<p>${escapeHtml(conditionText(row))}</p>` : ""}</div>`;
  }).join("")}</div>`;
}

function renderRoster(result) {
  const selected = new Set(result.pairIds);
  const needle = searchText.trim().toLocaleLowerCase();
  const visible = MODEL.characters.filter((person) => Object.values(person.names).some((value) => value.toLocaleLowerCase().includes(needle)));
  document.getElementById("roster-tools").innerHTML = `<label class="field search-field"><span>${escapeHtml(C.searchLabel)}</span>
    <input type="search" data-search data-focus-key="search" value="${escapeHtml(searchText)}" placeholder="${escapeHtml(C.searchPlaceholder)}"></label>
    <button type="button" class="button quiet" data-action="clear-search" data-focus-key="clear-search"${searchText ? "" : " disabled"}>${escapeHtml(C.clearSearch)}</button>
    <div class="segmented" aria-label="Roster view"><button type="button" data-roster-view="cards" data-focus-key="view-cards" aria-pressed="${state.view.roster === "cards"}">${escapeHtml(C.cardsView)}</button>
    <button type="button" data-roster-view="matrix" data-focus-key="view-matrix" aria-pressed="${state.view.roster === "matrix"}">${escapeHtml(C.matrixView)}</button></div>`;
  document.getElementById("roster-count").textContent = `${C.showing} ${visible.length} ${C.of} ${MODEL.characters.length}`;
  const content = document.getElementById("roster-content");
  if (!visible.length) {
    content.className = "";
    content.innerHTML = `<p class="notice" role="status">${escapeHtml(C.noResults)}</p>`;
    return;
  }
  if (state.view.roster === "cards") {
    content.className = "roster-grid";
    content.innerHTML = visible.map((person) => {
      const aliases = Object.entries(person.names).filter(([lang]) => lang !== MODEL.language).map(([, value]) => value).join(" · ");
      const badge = person.scope === "part1" ? `${[...selected].filter((id) => id.startsWith(`${person.id}@`)).length}×` : C.referenceOnly;
      return `<details class="person-card" id="character-${person.id}" data-character-card="${person.id}"><summary>${avatar(person)}<span><strong>${escapeHtml(personName(person))}</strong>
        <span class="aliases">${escapeHtml(aliases)}</span></span><span class="tag">${escapeHtml(badge)}</span></summary><div class="person-body">${rosterConditions(person, selected)}</div></details>`;
    }).join("");
  } else {
    content.className = "matrix-wrap";
    const headings = MODEL.routes.map((route) => `<th scope="col">${escapeHtml(routeName(route))}</th>`).join("");
    const rows = visible.map((person) => {
      if (person.scope === "reference") return `<tr id="character-${person.id}"><th scope="row"><span class="matrix-person">${avatar(person)}<span>${escapeHtml(personName(person))}<small class="aliases">${escapeHtml(Object.entries(person.names).filter(([lang]) => lang !== MODEL.language).map(([, name]) => name).join(" · "))}</small></span></span></th><td colspan="4">${escapeHtml(person.notes[MODEL.language])}</td></tr>`;
      const cells = MODEL.routes.map((route) => {
        const row = MODEL.rows.find((candidate) => candidate.characterId === person.id && candidate.routeId === route.id);
        return `<td class="${selected.has(row.id) ? "selected" : ""} ${row.status === "no" ? "status-no" : ""}"><strong>${selected.has(row.id) ? "✓ " : ""}${escapeHtml(statusText(row))}</strong>
          ${conditionNote(row, "matrix")}</td>`;
      }).join("");
      return `<tr id="character-${person.id}"><th scope="row"><span class="matrix-person">${avatar(person)}<span>${escapeHtml(personName(person))}<small class="aliases">${escapeHtml(Object.entries(person.names).filter(([lang]) => lang !== MODEL.language).map(([, name]) => name).join(" · "))}</small></span></span></th>${cells}</tr>`;
    }).join("");
    content.innerHTML = `<table class="matrix"><thead><tr><th scope="col">${escapeHtml(C.character)}</th>${headings}</tr></thead><tbody>${rows}</tbody></table>`;
  }
}

function renderNotice() {
  const notice = document.getElementById("planner-notice");
  notice.innerHTML = noticeMessage ? `${escapeHtml(noticeMessage)}${noticeFallbackUrl ? `<input class="fallback-url" value="${escapeHtml(noticeFallbackUrl)}" readonly aria-label="URL">` : ""}` : "";
}

function shareUrlFor(targetUrl = location.href) {
  const url = new URL(targetUrl, location.href);
  url.searchParams.delete("route");
  const encoded = encodePlanPayload(validatePayload(state, MODEL));
  if (encoded.length > MAX_ENCODED_PAYLOAD) throw new Error("payload too long");
  url.searchParams.set("plan", encoded);
  url.hash = location.hash || "#optimizer";
  return url.href;
}

function updateLocaleLinks() {
  document.querySelectorAll("[data-locale]").forEach((link) => {
    try {
      link.href = shareUrlFor(link.getAttribute("href"));
    } catch (_error) {
      // Static language links remain useful if the payload cannot be encoded.
    }
  });
}

function focusKey() {
  return document.activeElement?.dataset?.focusKey || null;
}

function restoreFocus(key) {
  if (!key) return;
  const target = [...document.querySelectorAll("[data-focus-key]")].find((element) => element.dataset.focusKey === key);
  target?.focus({ preventScroll: true });
}

function revealHash() {
  if (!location.hash.startsWith("#character-")) return;
  let target = document.querySelector(location.hash);
  if (!(target instanceof HTMLDetailsElement)) {
    state.view.roster = "cards";
    renderRoster(currentResult());
    persist();
    target = document.querySelector(location.hash);
  }
  if (target instanceof HTMLDetailsElement) target.open = true;
}

function switchOfflineLanguage(language) {
  if (!IS_OFFLINE || !OFFLINE_LOCALES[language] || language === MODEL.language) return;
  const locale = OFFLINE_LOCALES[language];
  bindModel({ ...BASE_MODEL, ...locale.model });
  state = validatePayload(state, MODEL);
  document.documentElement.lang = MODEL.htmlLanguage;
  document.body.dataset.language = language;
  document.title = locale.title;
  const description = document.querySelector('meta[name="description"]');
  if (description) description.content = locale.description;
  document.getElementById("page-content").innerHTML = locale.content;
  noticeMessage = "";
  noticeFallbackUrl = "";
  renderAll({ announce: false });
}

function renderAll({ controls = true, announce = true, focus = focusKey() } = {}) {
  const advancedOpen = document.querySelector("#planner-controls .advanced")?.open || false;
  const result = currentResult();
  renderModes();
  if (controls) renderControls(result, advancedOpen);
  renderSummary(result);
  renderRouteTabs();
  renderRoutes(result);
  renderRoster(result);
  renderNotice();
  updateLocaleLinks();
  persist();
  restoreFocus(focus);
  revealHash();
  if (announce) document.getElementById("live-region").textContent = `${C.planUpdated}: ${C.coverageMetric} ${result.metrics.coverage}/50, ${C.totalJoins} ${result.metrics.total}`;
}

function setMode(mode) {
  if (mode === state.mode) return;
  const transitioned = transitionMode(state, mode, MODEL, expansionVisited);
  state = transitioned.state;
  expansionVisited = transitioned.expansionVisited;
  renderAll();
}

function selectGoal(goal) {
  const settings = state[state.mode];
  settings.goal = goal;
  settings.preference = goal;
  settings.selectedPlanId = null;
  renderAll();
}

function selectCustomPlan(planId) {
  if (state.mode === "expand") return;
  if (!MODEL.selectors[state.mode].all.includes(planId)) return;
  const settings = state[state.mode];
  settings.goal = "custom";
  settings.selectedPlanId = planId;
  renderAll();
}

async function copyShareLink() {
  let url;
  try {
    url = shareUrlFor();
    await navigator.clipboard.writeText(url);
    noticeMessage = C.copied;
    noticeFallbackUrl = "";
  } catch (_error) {
    noticeMessage = C.copyFailed;
    noticeFallbackUrl = url || location.href;
  }
  renderNotice();
}

function resetPlan() {
  state = createDefaultPayload(MODEL);
  expansionVisited = false;
  searchText = "";
  noticeMessage = "";
  noticeFallbackUrl = "";
  try {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(EXPANSION_VISITED_KEY);
  } catch (_error) { /* best effort */ }
  const url = new URL(location.href);
  url.searchParams.delete("plan");
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  renderAll();
}

document.addEventListener("click", (event) => {
  const language = event.target.closest("[data-switch-language]");
  if (language) return switchOfflineLanguage(language.dataset.switchLanguage);
  const mode = event.target.closest("[data-mode]");
  if (mode) return setMode(mode.dataset.mode);
  const goal = event.target.closest("[data-goal]");
  if (goal && state.mode !== "expand") return selectGoal(goal.dataset.goal);
  const plan = event.target.closest("[data-plan-id]");
  if (plan) return selectCustomPlan(plan.dataset.planId);
  const route = event.target.closest("[data-route]");
  if (route) {
    state.view.route = route.dataset.route;
    return renderAll({ controls: false });
  }
  const rosterView = event.target.closest("[data-roster-view]");
  if (rosterView) {
    state.view.roster = rosterView.dataset.rosterView;
    return renderAll({ controls: false });
  }
  const remove = event.target.closest("[data-remove-extra]");
  if (remove) {
    const removeButtons = [...document.querySelectorAll("[data-remove-extra]")].filter((button) => button.offsetParent !== null);
    const removeIndex = removeButtons.indexOf(remove);
    const focus = (removeButtons[removeIndex + 1] || removeButtons[removeIndex - 1])?.dataset.focusKey || "restore-extras";
    if (!state.expand.excludedPairIds.includes(remove.dataset.removeExtra)) state.expand.excludedPairIds.push(remove.dataset.removeExtra);
    return renderAll({ focus });
  }
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "share") return copyShareLink();
  if (action === "reset") return resetPlan();
  if (action === "clear-search") {
    searchText = "";
    return renderAll({ controls: false, announce: false });
  }
  if (action === "restore-goal") {
    const settings = state[state.mode];
    settings.goal = settings.preference;
    settings.selectedPlanId = null;
    return renderAll();
  }
  if (action === "change-baseline") {
    if (selectPlanId(MODEL, "once", state.once) !== state.expand.basePlanId) {
      state.once.goal = "custom";
      state.once.selectedPlanId = state.expand.basePlanId;
    }
    state.mode = "once";
    return renderAll();
  }
  if (action === "restore-extras") {
    state.expand.excludedPairIds = [];
    return renderAll();
  }
});

document.addEventListener("change", (event) => {
  const setting = event.target.dataset.setting;
  if (!setting) return;
  if (setting === "balance") state[state.mode].balance = event.target.value;
  if (setting === "weightQ") state[state.mode].weightQ = Number(event.target.value);
  if (setting === "expandWeightQ") state.expand.weightQ = Number(event.target.value);
  if (setting === "budget") {
    const max = MODEL.upper - PLAN_BY_ID.get(state.expand.basePlanId).pairIds.length;
    state.expand.budget = Math.max(0, Math.min(max, Number.parseInt(event.target.value, 10) || 0));
  }
  if (setting === "keepGate") state.expand.keepGate = event.target.checked;
  renderAll({ focus: event.target.dataset.focusKey });
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-search]")) {
    searchText = event.target.value;
    return renderAll({ controls: false, announce: false });
  }
  const setting = event.target.dataset.setting;
  if (setting === "budget") {
    const max = MODEL.upper - PLAN_BY_ID.get(state.expand.basePlanId).pairIds.length;
    state.expand.budget = Math.max(0, Math.min(max, Number.parseInt(event.target.value, 10) || 0));
    return renderAll({ controls: false });
  }
  if (setting === "weightQ" || setting === "expandWeightQ") {
    const value = Number(event.target.value);
    if (setting === "weightQ") state[state.mode].weightQ = value;
    else state.expand.weightQ = value;
    document.querySelectorAll("[data-weight-output]").forEach((output) => { output.textContent = formatWeight(value); });
    renderAll({ controls: false });
  }
});

document.addEventListener("keydown", (event) => {
  const plan = event.target.closest("[data-plan-id]");
  if (plan && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    selectCustomPlan(plan.dataset.planId);
  }
});

let conditionCloseTimer;
let conditionOpening = false;
function openCondition(panel) {
  if (conditionOpening || panel.matches(":popover-open")) return;
  conditionOpening = true;
  try { panel.showPopover(); } finally { setTimeout(() => { conditionOpening = false; }, 0); }
}
function conditionPanel(target) {
  const trigger = target.closest?.(".condition-trigger");
  return trigger ? document.getElementById(trigger.getAttribute("popovertarget")) : target.closest?.(".condition-popover");
}
function previewCondition(event) {
  if (event.type === "pointerover" && event.pointerType !== "mouse") return;
  const panel = conditionPanel(event.target);
  if (!panel) return;
  const pinned = document.querySelector(".condition-popover[data-pinned]:popover-open");
  if (pinned && pinned !== panel) return;
  clearTimeout(conditionCloseTimer);
  openCondition(panel);
}
function leaveCondition(event) {
  const panel = conditionPanel(event.target);
  if (!panel || conditionPanel(event.relatedTarget || {}) === panel) return;
  clearTimeout(conditionCloseTimer);
  conditionCloseTimer = setTimeout(() => {
    if (panel.isConnected && panel.matches(":popover-open") && !panel.dataset.pinned) panel.hidePopover();
  }, 180);
}
document.addEventListener("pointerover", previewCondition);
document.addEventListener("pointerout", leaveCondition);
document.addEventListener("focusin", previewCondition);
document.addEventListener("focusout", leaveCondition);
document.addEventListener("click", (event) => {
  const trigger = event.target.closest(".condition-trigger");
  if (!trigger) return;
  event.preventDefault();
  const panel = conditionPanel(trigger);
  if (panel.dataset.pinned) { panel.hidePopover(); delete panel.dataset.pinned; }
  else { panel.dataset.pinned = "true"; openCondition(panel); }
});
document.addEventListener("toggle", (event) => {
  if (event.target.matches?.(".condition-popover") && event.newState === "closed") delete event.target.dataset.pinned;
}, true);

// Popovers occupy the top layer so opening conditions never reflows the roster.
function positionCondition(panel) {
  const trigger = [...document.querySelectorAll(".condition-trigger")].find((button) => button.getAttribute("popovertarget") === panel.id);
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth;
  const width = Math.min(360, viewportWidth - 24);
  const below = window.innerHeight - rect.bottom - 12;
  const above = rect.top - 12;
  const useBelow = below >= Math.min(240, above);
  panel.style.width = `${width}px`;
  panel.style.left = `${Math.max(12, Math.min(rect.right - width, viewportWidth - width - 12))}px`;
  panel.style.top = useBelow ? `${rect.bottom + 6}px` : "auto";
  panel.style.bottom = useBelow ? "auto" : `${window.innerHeight - rect.top + 6}px`;
  panel.style.maxHeight = `${Math.max(100, (useBelow ? below : above) - 6)}px`;
}
document.addEventListener("beforetoggle", (event) => {
  if (!event.target.matches?.(".condition-popover")) return;
  conditionOpening = true;
  setTimeout(() => { conditionOpening = false; }, 0);
  if (event.newState === "open") positionCondition(event.target);
}, true);
let conditionFrame;
function repositionConditions() {
  cancelAnimationFrame(conditionFrame);
  conditionFrame = requestAnimationFrame(() => document.querySelectorAll(".condition-popover:popover-open").forEach(positionCondition));
}
document.addEventListener("scroll", repositionConditions, true);
window.addEventListener("resize", repositionConditions);

window.addEventListener("hashchange", revealHash);
renderAll({ announce: false });
