const VALID_BLOOD_GROUPS = new Set([
  'O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'
]);

const REQUIRED_REQUEST_FIELDS = [
  'patient_name',
  'blood_group',
  'hospital',
  'city',
  'deadline'
];

function normalizeBloodGroup(value) {
  if (!value) return undefined;
  const compact = String(value).trim().toUpperCase()
    .replace(/\s+/g, ' ')
    .replace(' POSITIVE', '+')
    .replace(' NEGATIVE', '-')
    .replace(/\s/g, '');
  return VALID_BLOOD_GROUPS.has(compact) ? compact : undefined;
}

function cleanRequestDraft(input) {
  const source = input && typeof input === 'object' ? input : {};
  const draft = {};
  const textFields = [
    'patient_name', 'hospital', 'city', 'deadline', 'urgency',
    'component', 'diagnosis'
  ];
  for (const field of textFields) {
    const value = source[field];
    if (typeof value === 'string' && value.trim()) draft[field] = value.trim();
  }
  if (draft.deadline && /^\d{4}-\d{2}-\d{2}/.test(draft.deadline)) {
    draft.deadline = draft.deadline.slice(0, 10);
  }
  const bloodGroup = normalizeBloodGroup(source.blood_group);
  if (bloodGroup) draft.blood_group = bloodGroup;
  const units = Number.parseInt(source.units, 10);
  draft.units = Number.isInteger(units) && units >= 1 && units <= 20 ? units : 1;
  draft.urgency ||= 'routine';
  draft.component ||= 'red_cells';
  return draft;
}

function isBloodActionRequest(message, hasActiveDraft = false) {
  if (hasActiveDraft) return true;
  const text = String(message || '').toLowerCase();
  const hasAction = /\b(arrange|book|find|locate|get|need|request|send|contact|apply|search)\b/.test(text)
    || /\blooking\s+for\b/.test(text);
  const hasBloodTask = /\b(blood|donor|donors|transfusion|unit|units)\b/.test(text);
  return hasAction && hasBloodTask;
}

function parseAssistantOutput(raw, defaults = {}, options = {}) {
  const cleaned = String(raw || '').trim()
    .replace(/^```json\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/```$/i, '')
    .trim();
  let parsed;
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    return {
      answer: cleaned || 'I could not understand that request. Please try again.',
      intent: 'answer',
      requestDraft: {},
      missingFields: []
    };
  }
  const modelIntent = parsed.intent === 'arrange_blood' ? 'arrange_blood' : 'answer';
  const intentGuardTriggered = modelIntent === 'arrange_blood'
    && options.allowArrangeBlood === false;
  const intent = intentGuardTriggered ? 'answer' : modelIntent;
  const requestDraft = intent === 'arrange_blood'
    ? cleanRequestDraft({
        ...defaults,
        ...(parsed.requestDraft || {})
      })
    : {};
  const missingFields = intent === 'arrange_blood'
    ? REQUIRED_REQUEST_FIELDS.filter((field) => !requestDraft[field])
    : [];
  const followUpQuestions = {
    patient_name: 'What is the patient name?',
    blood_group: 'What blood group is required?',
    hospital: 'Which hospital should receive the blood?',
    city: 'Which city is the hospital in?',
    deadline: 'By what date is the blood required?'
  };
  let answer = String(parsed.answer || 'How can I help with your blood-care request?');
  if (intent === 'arrange_blood') {
    answer = missingFields.length === 0
      ? 'I have enough details to create the blood request. Please confirm the summary shown by CareCircle.'
      : followUpQuestions[missingFields[0]];
  }
  return {
    answer,
    intent,
    requestDraft,
    missingFields,
    intentGuardTriggered
  };
}

module.exports = {
  isBloodActionRequest,
  normalizeBloodGroup,
  parseAssistantOutput
};
