const test = require('node:test');
const assert = require('node:assert/strict');

const {
  isBloodActionRequest,
  normalizeBloodGroup,
  parseAssistantOutput
} = require('./assistant');

test('normalizes spoken blood groups', () => {
  assert.equal(normalizeBloodGroup('B positive'), 'B+');
  assert.equal(normalizeBloodGroup('o negative'), 'O-');
  assert.equal(normalizeBloodGroup('AB+'), 'AB+');
});

test('keeps supplied request fields and asks only for genuinely missing fields', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'I can help arrange this. Which hospital should receive the blood?',
    intent: 'arrange_blood',
    requestDraft: {
      patient_name: 'Anshul',
      blood_group: 'B positive',
      units: 2,
      city: 'Delhi',
      deadline: '2026-06-13',
      urgency: 'high'
    }
  }));

  assert.equal(result.requestDraft.blood_group, 'B+');
  assert.equal(result.requestDraft.units, 2);
  assert.deepEqual(result.missingFields, ['hospital']);
});

test('rejects malformed action data and asks for the invalid field', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'Please tell me the blood group.',
    intent: 'arrange_blood',
    requestDraft: {
      patient_name: 'Anshul',
      blood_group: 'blue',
      units: 50,
      hospital: 'Apollo Hospital',
      city: 'Delhi',
      deadline: '2026-06-12'
    }
  }));

  assert.match(result.answer, /blood group/i);
  assert.equal(result.requestDraft.blood_group, undefined);
  assert.equal(result.requestDraft.units, 1);
  assert.ok(result.missingFields.includes('blood_group'));
});

test('normalizes complete action drafts to an executable date and confirmation', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'Please confirm the urgency level.',
    intent: 'arrange_blood',
    requestDraft: {
      patient_name: 'Anshul',
      blood_group: 'B+',
      hospital: 'Apollo Hospital',
      city: 'Delhi',
      deadline: '2026-06-12T23:59:59Z',
      urgency: 'high'
    }
  }));

  assert.equal(result.requestDraft.deadline, '2026-06-12');
  assert.deepEqual(result.missingFields, []);
  assert.match(result.answer, /enough details/i);
});

test('fills model omissions from trusted conversation context', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'Which city?',
    intent: 'arrange_blood',
    requestDraft: {
      hospital: 'Apollo Hospital',
      deadline: '2026-06-12'
    }
  }), {
    patient_name: 'Anshul',
    blood_group: 'B+',
    city: 'Delhi'
  });

  assert.equal(result.requestDraft.city, 'Delhi');
  assert.equal(result.requestDraft.blood_group, 'B+');
  assert.deepEqual(result.missingFields, []);
});

test('asks for the validated missing field instead of trusting model wording', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'When do you need it?',
    intent: 'arrange_blood',
    requestDraft: {
      patient_name: 'Anshul',
      blood_group: 'B+',
      city: 'Delhi',
      deadline: '2026-06-12'
    }
  }));

  assert.deepEqual(result.missingFields, ['hospital']);
  assert.match(result.answer, /hospital/i);
});

test('does not treat a patient profile question as a blood-booking action', () => {
  assert.equal(
    isBloodActionRequest('Using my profile, tell me my blood group and city.', false),
    false
  );
});

test('allows explicit blood requests and follow-up answers for an active draft', () => {
  assert.equal(
    isBloodActionRequest('Please arrange one unit of B positive blood this week.', false),
    true
  );
  assert.equal(isBloodActionRequest('Apollo Hospitals', true), true);
});

test('blocks a stale model action when the current question is informational', () => {
  const result = parseAssistantOutput(JSON.stringify({
    answer: 'I have enough details to create the blood request.',
    intent: 'arrange_blood',
    requestDraft: {
      patient_name: 'Hoon Context Patient',
      blood_group: 'B+',
      hospital: 'Apollo Hospitals',
      city: 'Hyderabad',
      deadline: '2026-06-08'
    }
  }), {}, { allowArrangeBlood: false });

  assert.equal(result.intent, 'answer');
  assert.deepEqual(result.requestDraft, {});
  assert.equal(result.intentGuardTriggered, true);
});
