import test from 'node:test';
import assert from 'node:assert/strict';
import { supportCost, costQ, computeMetrics, selectPlanId } from '../src/planner-core.mjs';
import { readModel } from './helpers.mjs';
const model = readModel();

test('starting support level 1 costs nothing; levels 2 and 3 need one and two increases', () => {
  for (const [support, expected] of [[1, 0], [2, 1], [3, 2]]) {
    const row = {status: 'recruit', support, renown: 7};
    assert.equal(supportCost(row), expected);
    assert.equal(costQ(row, 4), 28 + 4 * expected);
  }
  assert.equal(supportCost({status: 'free', support: 0}), 0);
  assert.equal(costQ({status: 'free', support: 0, renown: 2}, 24), 8);
  assert.equal(costQ({status: 'story', support: 3, renown: 7}, 24), 0);
});

test('Harwin on Theodora keeps the visible requirement at support 3', () => {
  const row = model.rows.find(row => row.sourceName === '哈尔温' && row.routeId === 'theodora');
  assert.equal(row.renown, 7);
  assert.equal(row.support, 3);
  assert.equal(supportCost(row), 2);
  assert.ok(!row.details.zh.includes('待核实'));
});

test('every precomputed plan agrees with runtime metrics and level increases', () => {
  for (const plan of model.plans) {
    const metrics = computeMetrics(model.rows, plan.pairIds, model.routeIds);
    assert.deepEqual(metrics, plan.metrics);
    const rows = model.rows.filter(row => plan.pairIds.includes(row.id));
    const expected = rows.reduce((n, row) => n + (row.status === 'recruit' ? Math.max(0, row.support - 1) : 0), 0);
    assert.equal(plan.s, expected);
    if (plan.objectives.product) assert.equal(plan.objectives.product.value, rows.reduce((n, row) => n + row.renown * (row.status === 'recruit' ? Math.max(0, row.support - 1) : 0), 0));
  }
});

test('unconstrained plans attain independently separable lower bounds at every support weight', () => {
  const people = [...new Set(model.rows.map(row => row.characterId))];
  for (const scope of ['once', 'twice']) {
    for (let q = 1; q <= 24; q++) {
      let lowerBound = 0;
      for (const person of people) {
        const rows = model.rows.filter(row => row.characterId === person && row.status !== 'no');
        // Enumerate all single choices / distinct pairs independently of the solver.
        const costs = rows.map(row => row.status === 'story' ? 0 : 4 * row.renown + q * (row.status === 'recruit' ? row.support - 1 : 0));
        const possibilities = scope === 'once' || rows.length === 1 ? costs : costs.flatMap((a, i) => costs.slice(i + 1).map(b => a + b));
        lowerBound += Math.min(...possibilities);
      }
      const id = selectPlanId(model, scope, {goal: 'compromise', balance: 'cost', weightQ: q});
      const plan = model.plans.find(p => p.id === id);
      assert.equal(4 * plan.r + q * plan.s, lowerBound, `${scope}, q=${q}`);
    }
  }
});
