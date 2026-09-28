export const STORAGE_KEY = "fw-recruitment:v1";
export const EXPANSION_VISITED_KEY = `${STORAGE_KEY}:expansion-visited`;
export const PAYLOAD_VERSION = 1;
export const MAX_ENCODED_PAYLOAD = 8192;

const GOALS = new Set(["early", "support", "compromise", "product", "gate", "custom"]);
const PREFERENCES = new Set(["early", "support", "compromise", "product", "gate"]);
const BALANCES = new Set(["cost", "0", "2"]);
const MODES = new Set(["once", "expand", "twice"]);
const ROSTER_VIEWS = new Set(["cards", "matrix"]);

export function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function supportCost(row) {
  return row.status === "recruit" ? Math.max(0, (row.support || 0) - 1) : 0;
}

export function costQ(row, weightQ) {
  return row.status === "story" ? 0 : 4 * row.renown + weightQ * supportCost(row);
}

export function computeMetrics(rows, pairIds, routeIds) {
  const wanted = new Set(pairIds);
  const selected = rows.filter((row) => wanted.has(row.id));
  const frequency = {};
  const people = new Map();
  for (const row of selected) people.set(row.characterId, (people.get(row.characterId) || 0) + 1);
  for (const count of people.values()) frequency[count] = (frequency[count] || 0) + 1;
  const gates = routeIds.map((routeId) => Math.max(2, ...selected
    .filter((row) => row.routeId === routeId)
    .map((row) => row.renown || 0)));
  const recruitCounts = routeIds.map((routeId) => selected.filter(
    (row) => row.routeId === routeId && row.status !== "story",
  ).length);
  return {
    coverage: people.size,
    total: selected.length,
    frequency,
    r: selected.reduce((sum, row) => sum + (row.renown || 0), 0),
    s: selected.reduce((sum, row) => sum + supportCost(row), 0),
    gates,
    recruitCounts,
    delta: Math.max(...recruitCounts) - Math.min(...recruitCounts),
  };
}

export function expandPlan(rows, baseIds, routeIds, options = {}) {
  const weightQ = options.weightQ ?? 4;
  const budget = options.budget ?? 43;
  const keepGate = options.keepGate ?? false;
  const excluded = new Set(options.excludedPairIds || []);
  if (!Number.isInteger(weightQ) || weightQ < 1 || weightQ > 24) throw new Error("invalid weightQ");
  if (!Number.isInteger(budget) || budget < 0) throw new Error("invalid budget");
  const byId = new Map(rows.map((row) => [row.id, row]));
  if (byId.size !== rows.length || new Set(baseIds).size !== baseIds.length) throw new Error("duplicate identity");
  const base = baseIds.map((id) => byId.get(id));
  if (base.some((row) => !row || row.status === "no")) throw new Error("invalid baseline pair");
  const partOnePeople = [...new Set(rows.map((row) => row.characterId))];
  const occurrences = new Map();
  for (const row of base) occurrences.set(row.characterId, (occurrences.get(row.characterId) || 0) + 1);
  if (occurrences.size !== partOnePeople.length || [...occurrences.values()].some((count) => count !== 1)) {
    throw new Error("baseline must cover each Part I character exactly once");
  }
  const storyIds = new Set(rows.filter((row) => row.status === "story").map((row) => row.id));
  const baseSet = new Set(baseIds);
  if ([...storyIds].some((id) => !baseSet.has(id))) throw new Error("baseline must include every fixed story join");
  const available = new Map(partOnePeople.map((id) => [id, rows.filter(
    (row) => row.characterId === id && row.status !== "no",
  )]));
  const upper = [...available.values()].reduce((sum, optionsForPerson) => sum + Math.min(2, optionsForPerson.length), 0);
  if (budget > upper - base.length) throw new Error("budget exceeds global cap");
  const baseGates = routeIds.map((routeId) => Math.max(2, ...base
    .filter((row) => row.routeId === routeId)
    .map((row) => row.renown || 0)));
  const gateByRoute = new Map(routeIds.map((routeId, index) => [routeId, baseGates[index]]));
  const counts = new Map(routeIds.map((routeId) => [routeId, base.filter(
    (row) => row.routeId === routeId && row.status !== "story",
  ).length]));
  const thresholdByCharacter = {};
  const candidates = [];
  for (const [characterId, choices] of available.entries()) {
    if (choices.length < 2) continue;
    const threshold = choices.map((row) => costQ(row, weightQ)).sort((a, b) => a - b)[1];
    thresholdByCharacter[characterId] = threshold;
    for (const row of choices) {
      if (baseSet.has(row.id) || costQ(row, weightQ) > threshold) continue;
      if (keepGate && row.renown > gateByRoute.get(row.routeId)) continue;
      candidates.push(row);
    }
  }
  const routeRank = new Map(routeIds.map((routeId, index) => [routeId, index]));
  const remaining = [...candidates];
  const automatic = [];
  const compare = (a, b) => {
    const aKey = [costQ(a, weightQ), counts.get(a.routeId), a.renown, a.support, a.rank, routeRank.get(a.routeId)];
    const bKey = [costQ(b, weightQ), counts.get(b.routeId), b.renown, b.support, b.rank, routeRank.get(b.routeId)];
    for (let index = 0; index < aKey.length; index += 1) {
      if (aKey[index] !== bKey[index]) return aKey[index] - bKey[index];
    }
    return a.id.localeCompare(b.id);
  };
  while (remaining.length && automatic.length < budget) {
    remaining.sort(compare);
    const chosen = remaining.shift();
    automatic.push(chosen);
    counts.set(chosen.routeId, counts.get(chosen.routeId) + 1);
  }
  const added = automatic.filter((row) => !excluded.has(row.id));
  const pairIds = [...baseIds, ...added.map((row) => row.id)];
  const metrics = computeMetrics(rows, pairIds, routeIds);
  if (new Set(pairIds).size !== pairIds.length || pairIds.length > upper || metrics.coverage !== partOnePeople.length) {
    throw new Error("invalid expansion result");
  }
  return {
    ...metrics,
    upper,
    baseIds: [...baseIds].sort(),
    baseGates,
    eligibleCount: candidates.length,
    added: added.length,
    candidateIds: candidates.map((row) => row.id).sort(),
    automaticIds: automatic.map((row) => row.id),
    addedIds: added.map((row) => row.id),
    pairIds,
    thresholdByCharacter,
    addedCostQ: added.reduce((sum, row) => sum + costQ(row, weightQ), 0),
  };
}

function planById(model, id) {
  return model.plans.find((plan) => plan.id === id);
}

function tupleCompare(a, b) {
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return 0;
}

export function selectableFrontier(model, scope, balance) {
  const selector = model.selectors[scope];
  if (!selector) throw new Error("unknown scope");
  let choices = selector.frontier.map((id) => planById(model, id));
  if (balance === "0") choices = choices.filter((plan) => plan.metrics.delta <= selector.minDelta);
  if (balance === "2") choices = choices.filter((plan) => plan.metrics.delta <= 2);
  return choices.filter((plan) => !choices.some((other) => other.id !== plan.id && (
    (other.r <= plan.r && other.s <= plan.s && (other.r < plan.r || other.s < plan.s))
    || (other.r === plan.r && other.s === plan.s && other.metrics.delta < plan.metrics.delta)
  )));
}

export function selectPlanId(model, scope, settings) {
  const selector = model.selectors[scope];
  if (!selector) throw new Error("unknown scope");
  if (settings.goal === "custom") {
    if (!settings.selectedPlanId || !selector.all.includes(settings.selectedPlanId)) throw new Error("invalid custom plan");
    return settings.selectedPlanId;
  }
  if (settings.goal === "product") return selector.product;
  if (settings.goal === "gate") {
    return [...selector.threshold].sort((aId, bId) => {
      const a = planById(model, aId);
      const b = planById(model, bId);
      const aGateR = a.metrics.gates.reduce((sum, value) => sum + value, 0);
      const bGateR = b.metrics.gates.reduce((sum, value) => sum + value, 0);
      return tupleCompare(
        [aGateR * 4 + settings.weightQ * a.s, a.s, a.metrics.delta],
        [bGateR * 4 + settings.weightQ * b.s, b.s, b.metrics.delta],
      );
    })[0];
  }
  const choices = selectableFrontier(model, scope, settings.balance);
  if (!choices.length) throw new Error("no selectable plans");
  const preference = settings.goal;
  const sorted = [...choices].sort((a, b) => {
    if (preference === "early") return tupleCompare([a.r, a.s, a.metrics.delta], [b.r, b.s, b.metrics.delta]);
    if (preference === "support") return tupleCompare([a.s, a.r, a.metrics.delta], [b.s, b.r, b.metrics.delta]);
    return tupleCompare(
      [4 * a.r + settings.weightQ * a.s, a.metrics.delta, a.s, a.r],
      [4 * b.r + settings.weightQ * b.s, b.metrics.delta, b.s, b.r],
    );
  });
  return sorted[0].id;
}

export function createDefaultPayload(model) {
  return {
    v: PAYLOAD_VERSION,
    dataVersion: model.dataVersion,
    mode: "once",
    once: { goal: "compromise", preference: "compromise", balance: "cost", weightQ: 4, selectedPlanId: null },
    twice: { goal: "compromise", preference: "compromise", balance: "cost", weightQ: 4, selectedPlanId: null },
    expand: {
      basePlanId: model.defaultBasePlanId,
      weightQ: 4,
      budget: model.upper - 50,
      keepGate: false,
      excludedPairIds: [],
    },
    view: { route: "all", roster: "cards" },
  };
}

export function transitionMode(currentState, targetMode, model, expansionVisited = false) {
  if (!MODES.has(targetMode)) throw new Error("invalid target mode");
  const next = deepClone(currentState);
  let visited = expansionVisited;
  if (targetMode === "expand" && (next.mode === "once" || !visited)) {
    const baselineId = selectPlanId(model, "once", next.once);
    if (baselineId !== next.expand.basePlanId) {
      next.expand.basePlanId = baselineId;
      next.expand.excludedPairIds = [];
      next.expand.budget = Math.min(next.expand.budget, model.upper - planById(model, baselineId).pairIds.length);
    }
    if (!visited) next.expand.weightQ = next.once.weightQ;
  }
  next.mode = targetMode;
  if (targetMode === "expand") visited = true;
  return { state: next, expansionVisited: visited };
}

export function storedExpansionVisited(payload, marker) {
  return payload.mode === "expand" || marker === "1";
}

export function applyNavigationRoute(payload, route, model, hasValidExplicitPlan = false) {
  const next = deepClone(payload);
  if (!hasValidExplicitPlan && model.routeIds.includes(route)) next.view.route = route;
  return next;
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

export function encodePlanPayload(payload) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  return bytesToBase64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function decodePlanPayload(encoded) {
  if (!encoded || encoded.length > MAX_ENCODED_PAYLOAD || !/^[A-Za-z0-9_-]+$/.test(encoded)) throw new Error("invalid encoded payload");
  const padded = encoded.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((encoded.length + 3) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid ${label}`);
  return value;
}

function validateScopeState(raw, scope, model) {
  requireObject(raw, scope);
  if (!GOALS.has(raw.goal) || !PREFERENCES.has(raw.preference) || !BALANCES.has(raw.balance)) throw new Error(`invalid ${scope} enum`);
  if (!Number.isInteger(raw.weightQ) || raw.weightQ < 1 || raw.weightQ > 24) throw new Error(`invalid ${scope} weight`);
  const selectable = new Set(model.selectors[scope].all);
  if (raw.goal === "custom") {
    if (typeof raw.selectedPlanId !== "string" || !selectable.has(raw.selectedPlanId)) throw new Error(`invalid ${scope} custom plan`);
  } else if (raw.selectedPlanId !== null) {
    throw new Error(`invalid ${scope} selected plan`);
  }
  return {
    goal: raw.goal,
    preference: raw.preference,
    balance: raw.balance,
    weightQ: raw.weightQ,
    selectedPlanId: raw.selectedPlanId,
  };
}

export function validatePayload(raw, model) {
  requireObject(raw, "payload");
  if (raw.v !== PAYLOAD_VERSION || raw.dataVersion !== model.dataVersion || !MODES.has(raw.mode)) throw new Error("unsupported payload");
  const once = validateScopeState(raw.once, "once", model);
  const twice = validateScopeState(raw.twice, "twice", model);
  const expansion = requireObject(raw.expand, "expand");
  const validOnce = new Set(model.validOncePlanIds);
  if (typeof expansion.basePlanId !== "string" || !validOnce.has(expansion.basePlanId)) throw new Error("invalid baseline");
  if (!Number.isInteger(expansion.weightQ) || expansion.weightQ < 1 || expansion.weightQ > 24) throw new Error("invalid expansion weight");
  const base = planById(model, expansion.basePlanId);
  const maxBudget = model.upper - base.pairIds.length;
  if (!Number.isInteger(expansion.budget) || expansion.budget < 0 || expansion.budget > maxBudget) throw new Error("invalid expansion budget");
  if (typeof expansion.keepGate !== "boolean" || !Array.isArray(expansion.excludedPairIds)) throw new Error("invalid expansion settings");
  const rowIds = new Set(model.rows.filter((row) => row.status !== "no").map((row) => row.id));
  const baseIds = new Set(base.pairIds);
  if (new Set(expansion.excludedPairIds).size !== expansion.excludedPairIds.length || expansion.excludedPairIds.some(
    (id) => typeof id !== "string" || !rowIds.has(id) || baseIds.has(id),
  )) throw new Error("invalid exclusions");
  const view = requireObject(raw.view, "view");
  const routeIds = new Set(["all", ...model.routeIds]);
  if (!routeIds.has(view.route) || !ROSTER_VIEWS.has(view.roster)) throw new Error("invalid view");
  return {
    v: PAYLOAD_VERSION,
    dataVersion: model.dataVersion,
    mode: raw.mode,
    once,
    twice,
    expand: {
      basePlanId: expansion.basePlanId,
      weightQ: expansion.weightQ,
      budget: expansion.budget,
      keepGate: expansion.keepGate,
      excludedPairIds: [...expansion.excludedPairIds],
    },
    view: { route: view.route, roster: view.roster },
  };
}
