import test from "node:test";
import assert from "node:assert/strict";
import { costQ, expandPlan, selectableFrontier, selectPlanId } from "../src/planner-core.mjs";
import { readJson, readModel } from "./helpers.mjs";

const model = readModel();
const fixtures = readJson("tests/fixtures/expansion.json");
const base = model.plans.find((plan) => plan.id === fixtures.defaultBasePlanId);

function comparable(result) {
  return {
    upper: result.upper,
    eligibleCount: result.eligibleCount,
    baseIds: result.baseIds,
    automaticIds: result.automaticIds,
    addedIds: result.addedIds,
    candidateIds: result.candidateIds,
    total: result.total,
    added: result.added,
    frequency: Object.fromEntries(Object.entries(result.frequency).map(([key, value]) => [String(key), value])),
    r: result.r,
    s: result.s,
    addedCostQ: result.addedCostQ,
    recruitCounts: result.recruitCounts,
    gates: result.gates,
  };
}

test("default plan identity and selector match the reviewed fixture", () => {
  assert.equal(model.dataVersion, fixtures.dataVersion);
  assert.equal(model.defaultBasePlanId, fixtures.defaultBasePlanId);
  const settings = { goal: "compromise", preference: "compromise", balance: "cost", weightQ: 4, selectedPlanId: null };
  assert.equal(selectPlanId(model, "once", settings), fixtures.defaultBasePlanId);
});

for (const [name, options] of [
  ["default", {}],
  ["keep_gate", { keepGate: true }],
  ["zero_budget", { budget: 0 }],
  ["one_extra", { budget: 1 }],
  ["remove_without_refill", { excludedPairIds: [fixtures.cases.default.automaticIds[0]] }],
]) {
  test(`expansion fixture: ${name}`, () => {
    const result = expandPlan(model.rows, base.pairIds, model.routeIds, options);
    assert.deepEqual(comparable(result), fixtures.cases[name]);
  });
}

test("synthetic equal costs allow one character on all four routes under the global cap", () => {
  const routes = ["a", "b", "c", "d"];
  const values = [[2, 2, 2, 2], [3, 20, null, null], [4, 20, null, null], [5, null, null, null]];
  const rows = values.flatMap((personValues, rank) => personValues.map((value, routeIndex) => ({
    id: `x${rank}@${routes[routeIndex]}`,
    characterId: `x${rank}`,
    routeId: routes[routeIndex],
    rank,
    status: value === null ? "no" : "recruit",
    renown: value,
    support: value === null ? null : 0,
  })));
  const baseline = ["x0@a", "x1@a", "x2@a", "x3@a"];
  const result = expandPlan(rows, baseline, routes, { budget: 3 });
  assert.deepEqual(result.frequency, { 1: 3, 4: 1 });
  assert.equal(result.total, 7);
  assert.deepEqual(result.addedIds, ["x0@b", "x0@c", "x0@d"]);
});

test("the second order statistic counts repeated costs", () => {
  const routes = ["a", "b", "c", "d"];
  const rows = [5, 5, 9, 11].map((renown, rank) => ({
    id: `x@${routes[rank]}`, characterId: "x", routeId: routes[rank], rank: 0,
    status: "recruit", renown, support: 0,
  }));
  const result = expandPlan(rows, ["x@a"], routes, { budget: 1 });
  assert.ok(result.candidateIds.includes("x@b"));
  assert.ok(!result.candidateIds.includes("x@c"));
});

test("selection reaches the independent minimum primary cost", () => {
  const result = expandPlan(model.rows, base.pairIds, model.routeIds, { budget: 4 });
  const candidateCosts = result.candidateIds.map((id) => costQ(model.rows.find((row) => row.id === id), 4)).sort((a, b) => a - b);
  const selectedCost = result.automaticIds.reduce((sum, id) => sum + costQ(model.rows.find((row) => row.id === id), 4), 0);
  assert.equal(selectedCost, candidateCosts.slice(0, 4).reduce((sum, value) => sum + value, 0));
});

test("gate goal uses normalized route gates for every support weight", () => {
  for (const scope of ["once", "twice"]) {
    const candidates = model.selectors[scope].threshold.map((id, index) => ({
      index,
      plan: model.plans.find((candidate) => candidate.id === id),
    }));
    for (const { plan } of candidates) {
      const provenance = plan.objectives.threshold;
      assert.equal(provenance.r, plan.metrics.gates.reduce((sum, value) => sum + value, 0));
      assert.deepEqual(provenance.caps, plan.metrics.gates);
    }
    for (let weightQ = 1; weightQ <= 24; weightQ += 1) {
      const expected = [...candidates].sort((a, b) => {
        const aGate = a.plan.metrics.gates.reduce((sum, value) => sum + value, 0);
        const bGate = b.plan.metrics.gates.reduce((sum, value) => sum + value, 0);
        return (4 * aGate + weightQ * a.plan.s) - (4 * bGate + weightQ * b.plan.s)
          || a.plan.s - b.plan.s || a.plan.metrics.delta - b.plan.metrics.delta || a.index - b.index;
      })[0].plan.id;
      const settings = { goal: "gate", preference: "gate", balance: "cost", weightQ, selectedPlanId: null };
      assert.equal(selectPlanId(model, scope, settings), expected, `${scope} weightQ=${weightQ}`);
    }
  }
});

test("displayed frontiers remove dominated plans after headcount filtering", () => {
  for (const scope of ["once", "twice"]) {
    for (const balance of ["cost", "0", "2"]) {
      const plans = selectableFrontier(model, scope, balance);
      assert.ok(plans.length > 0);
      for (const plan of plans) {
        assert.ok(!plans.some((other) => other.id !== plan.id && (
          (other.r <= plan.r && other.s <= plan.s && (other.r < plan.r || other.s < plan.s))
          || (other.r === plan.r && other.s === plan.s && other.metrics.delta < plan.metrics.delta)
        )), `${scope}/${balance}: ${plan.id} is dominated`);
      }
    }
    assert.ok(selectableFrontier(model, scope, "cost").length < model.selectors[scope].frontier.length);
  }
});

test("small synthetic expansion reaches brute-force maximum count and minimum cost", () => {
  const routes = ["a", "b", "c"];
  const rows = [
    ["x", "a", "recruit", 1], ["x", "b", "recruit", 2], ["x", "c", "recruit", 9],
    ["y", "a", "recruit", 1], ["y", "b", "recruit", 1], ["y", "c", "recruit", 5],
    ["z", "a", "story", 0], ["z", "b", "recruit", 2], ["z", "c", "recruit", 2],
  ].map(([characterId, routeId, status, renown], rank) => ({
    id: `${characterId}@${routeId}`, characterId, routeId, status, renown, support: 0, rank,
  }));
  const baseline = ["x@a", "y@a", "z@a"];
  const budget = 3;
  const eligible = rows.filter((row) => {
    if (baseline.includes(row.id)) return false;
    const costs = rows.filter((other) => other.characterId === row.characterId)
      .map((other) => other.status === "story" ? 0 : 4 * other.renown).sort((a, b) => a - b);
    return (row.status === "story" ? 0 : 4 * row.renown) <= costs[1];
  });
  const subsets = Array.from({ length: 1 << eligible.length }, (_, mask) => eligible.filter((_, index) => mask & (1 << index)))
    .filter((subset) => subset.length <= budget);
  const optimumCount = Math.max(...subsets.map((subset) => subset.length));
  const optimumCost = Math.min(...subsets.filter((subset) => subset.length === optimumCount)
    .map((subset) => subset.reduce((sum, row) => sum + (row.status === "story" ? 0 : 4 * row.renown), 0)));
  const result = expandPlan(rows, baseline, routes, { budget, weightQ: 4 });
  assert.equal(result.addedIds.length, optimumCount);
  assert.equal(result.addedCostQ, optimumCost);
});
