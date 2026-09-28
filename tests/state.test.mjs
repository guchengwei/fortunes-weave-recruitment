import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ENCODED_PAYLOAD,
  applyNavigationRoute,
  createDefaultPayload,
  decodePlanPayload,
  encodePlanPayload,
  storedExpansionVisited,
  transitionMode,
  validatePayload,
} from "../src/planner-core.mjs";
import { readModel } from "./helpers.mjs";

const model = readModel();

test("default payload validates and ignores unknown keys", () => {
  const payload = createDefaultPayload(model);
  payload.unknown = "ignored";
  payload.once.unknown = true;
  const validated = validatePayload(payload, model);
  assert.equal(validated.mode, "once");
  assert.equal("unknown" in validated, false);
  assert.equal("unknown" in validated.once, false);
});

test("UTF-8 share payload survives an unpadded base64url round trip", () => {
  const payload = createDefaultPayload(model);
  const encoded = encodePlanPayload({ ...payload, ignoredLabel: "全員・日本語" });
  assert.match(encoded, /^[A-Za-z0-9_-]+$/);
  assert.ok(!encoded.includes("="));
  const decoded = decodePlanPayload(encoded);
  assert.equal(decoded.ignoredLabel, "全員・日本語");
  assert.deepEqual(validatePayload(decoded, model), payload);
});

test("stale, oversized, unsupported, and malformed payloads are rejected", () => {
  const stale = createDefaultPayload(model);
  stale.dataVersion = "stale";
  assert.throws(() => validatePayload(stale, model));
  const unsupported = createDefaultPayload(model);
  unsupported.v = 2;
  assert.throws(() => validatePayload(unsupported, model));
  assert.throws(() => decodePlanPayload("!not-base64url"));
  assert.throws(() => decodePlanPayload("a".repeat(MAX_ENCODED_PAYLOAD + 1)));
});

test("known invalid settings reject the whole payload", () => {
  const invalidWeight = createDefaultPayload(model);
  invalidWeight.once.weightQ = 25;
  assert.throws(() => validatePayload(invalidWeight, model));
  const invalidCustom = createDefaultPayload(model);
  invalidCustom.once.goal = "custom";
  invalidCustom.once.selectedPlanId = null;
  assert.throws(() => validatePayload(invalidCustom, model));
  const invalidBudget = createDefaultPayload(model);
  invalidBudget.expand.budget = 44;
  assert.throws(() => validatePayload(invalidBudget, model));
});

test("once to expansion captures the selected baseline and clears exclusions", () => {
  const payload = createDefaultPayload(model);
  const alternate = model.selectors.once.frontier.find((id) => id !== model.defaultBasePlanId);
  payload.once.goal = "custom";
  payload.once.selectedPlanId = alternate;
  payload.once.weightQ = 12;
  payload.expand.excludedPairIds = [model.rows.find((row) => row.status === "recruit" && !model.plans.find((plan) => plan.id === alternate).pairIds.includes(row.id)).id];
  const transitioned = transitionMode(payload, "expand", model, false);
  assert.equal(transitioned.state.expand.basePlanId, alternate);
  assert.equal(transitioned.state.expand.weightQ, 12);
  assert.deepEqual(transitioned.state.expand.excludedPairIds, []);
  assert.equal(transitioned.expansionVisited, true);
});

test("twice to expansion restores expansion state, and later entries keep expansion weight", () => {
  const payload = createDefaultPayload(model);
  payload.mode = "twice";
  payload.expand.weightQ = 20;
  const fromTwice = transitionMode(payload, "expand", model, true);
  assert.equal(fromTwice.state.expand.basePlanId, model.defaultBasePlanId);
  assert.equal(fromTwice.state.expand.weightQ, 20);
  fromTwice.state.mode = "once";
  fromTwice.state.once.weightQ = 2;
  const reentered = transitionMode(fromTwice.state, "expand", model, true);
  assert.equal(reentered.state.expand.weightQ, 20);
});

test("first expansion entry through twice uses the last once plan and weight", () => {
  const payload = createDefaultPayload(model);
  const alternate = model.selectors.once.frontier.find((id) => id !== model.defaultBasePlanId);
  payload.once.goal = "custom";
  payload.once.selectedPlanId = alternate;
  payload.once.weightQ = 12;
  payload.mode = "twice";
  const transitioned = transitionMode(payload, "expand", model, false);
  assert.equal(transitioned.state.expand.basePlanId, alternate);
  assert.equal(transitioned.state.expand.weightQ, 12);
  assert.equal(transitioned.expansionVisited, true);
});

test("refresh metadata preserves whether expansion was actually visited", () => {
  const payload = createDefaultPayload(model);
  assert.equal(storedExpansionVisited(payload, null), false);
  assert.equal(storedExpansionVisited(payload, "0"), false);
  assert.equal(storedExpansionVisited(payload, "1"), true);
  payload.mode = "expand";
  assert.equal(storedExpansionVisited(payload, null), true);
});

test("route-guide navigation overrides saved view but not an explicit plan", () => {
  const payload = createDefaultPayload(model);
  payload.view.route = "all";
  assert.equal(applyNavigationRoute(payload, "leda", model, false).view.route, "leda");
  assert.equal(applyNavigationRoute(payload, "leda", model, true).view.route, "all");
  assert.equal(applyNavigationRoute(payload, "unknown", model, false).view.route, "all");
});

test("removed recommendations remain exclusions and are not replaced", () => {
  const payload = createDefaultPayload(model);
  const fixturePlan = model.plans.find((plan) => plan.id === model.defaultBasePlanId);
  const automatic = model.rows.find((row) => row.status === "recruit" && !fixturePlan.pairIds.includes(row.id));
  payload.expand.excludedPairIds = [automatic.id];
  assert.deepEqual(validatePayload(payload, model).expand.excludedPairIds, [automatic.id]);
});
