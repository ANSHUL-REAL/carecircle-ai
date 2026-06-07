(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HoonAction = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  const requiredFields = [
    'patient_name',
    'blood_group',
    'hospital',
    'city',
    'deadline'
  ];

  function mergeDraft(current, incoming) {
    return {
      ...(current || {}),
      ...(incoming || {})
    };
  }

  function toCasePayload(draft) {
    const missing = requiredFields.filter((field) => !draft || !draft[field]);
    if (missing.length) {
      throw new Error(`Missing request fields: ${missing.join(', ')}`);
    }
    return {
      patient_name: draft.patient_name,
      blood_group: draft.blood_group,
      units: Number(draft.units) || 1,
      hospital: draft.hospital,
      city: draft.city,
      deadline: String(draft.deadline).slice(0, 10),
      urgency: draft.urgency || 'routine',
      component: draft.component || 'red_cells',
      diagnosis: draft.diagnosis || null
    };
  }

  return { mergeDraft, toCasePayload };
}));
