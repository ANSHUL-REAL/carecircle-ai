const test = require('node:test');
const assert = require('node:assert/strict');

const { mergeDraft, toCasePayload } = require('./hoon-action');

test('merges follow-up answers into the existing request draft', () => {
  const result = mergeDraft(
    { patient_name: 'Anshul', blood_group: 'B+', city: 'Delhi', units: 2 },
    { hospital: 'Apollo Hospital', deadline: '2026-06-13' }
  );
  assert.equal(result.blood_group, 'B+');
  assert.equal(result.hospital, 'Apollo Hospital');
});

test('builds a valid automation case only when required details exist', () => {
  const payload = toCasePayload({
    patient_name: 'Anshul',
    blood_group: 'B+',
    units: 2,
    hospital: 'Apollo Hospital',
    city: 'Delhi',
    deadline: '2026-06-13',
    urgency: 'high'
  });
  assert.deepEqual(payload, {
    patient_name: 'Anshul',
    blood_group: 'B+',
    units: 2,
    hospital: 'Apollo Hospital',
    city: 'Delhi',
    deadline: '2026-06-13',
    urgency: 'high',
    component: 'red_cells',
    diagnosis: null
  });
  assert.throws(() => toCasePayload({ city: 'Delhi' }), /missing/i);
});

test('strips a Bedrock timestamp from the case deadline', () => {
  const payload = toCasePayload({
    patient_name: 'Anshul',
    blood_group: 'B+',
    hospital: 'Apollo Hospital',
    city: 'Delhi',
    deadline: '2026-06-12T23:59:59Z'
  });
  assert.equal(payload.deadline, '2026-06-12');
});
