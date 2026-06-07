(function () {
  const DATA_URL = 'assets/carecircle-dataset.json';
  const DAY_MS = 86400000;
  const BLOOD_COMPATIBILITY = {
    'O-': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],
    'O+': ['O+', 'A+', 'B+', 'AB+'],
    'A-': ['A-', 'A+', 'AB-', 'AB+'],
    'A+': ['A+', 'AB+'],
    'B-': ['B-', 'B+', 'AB-', 'AB+'],
    'B+': ['B+', 'AB+'],
    'AB-': ['AB-', 'AB+'],
    'AB+': ['AB+']
  };

  let dataPromise;

  function clamp(value, min = 0, max = 100) {
    return Math.min(max, Math.max(min, Math.round(value)));
  }

  function parseDate(value) {
    return value ? new Date(`${value}T00:00:00Z`) : null;
  }

  function toDateString(date) {
    return date.toISOString().slice(0, 10);
  }

  function formatDate(value) {
    const date = parseDate(value);
    if (!date) return 'Not recorded';
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC'
    });
  }

  function daysBetween(from, to) {
    const start = typeof from === 'string' ? parseDate(from) : from;
    const end = typeof to === 'string' ? parseDate(to) : to;
    if (!start || !end) return 0;
    return Math.ceil((end - start) / DAY_MS);
  }

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  async function loadData() {
    if (!dataPromise) {
      dataPromise = fetch(DATA_URL)
        .then(response => {
          if (!response.ok) throw new Error(`Dataset load failed (${response.status})`);
          return response.json();
        })
        .then(data => {
          data.donorById = Object.fromEntries(data.donors.map(donor => [donor.id, donor]));
          data.patientById = Object.fromEntries(data.patients.map(patient => [patient.id, patient]));
          return data;
        });
    }
    return dataPromise;
  }

  function calculateReliabilityScore(donor) {
    const donations = Number(donor.donations_till_date) || 0;
    const calls = Number(donor.total_calls) || 0;
    const completionRate = calls > 0 ? Math.min(1, donations / calls) : donations > 0 ? 1 : 0.35;
    const experience = Math.min(1, donations / 8);
    const previousDonation = donor.donated_earlier ? 1 : 0;
    return clamp(completionRate * 50 + experience * 35 + previousDonation * 15);
  }

  function calculateAvailabilityScore(donor) {
    let score = donor.eligibility_status === 'eligible' ? 65 : 20;
    score += donor.active_status === 'Active' ? 25 : 0;
    score += donor.donor_type === 'Regular Donor' ? 10 : 5;
    return clamp(score);
  }

  function calculateFatigueScore(donor) {
    const calls = Number(donor.total_calls) || 0;
    const donations = Number(donor.donations_till_date) || 0;
    const unproductiveCalls = Math.max(0, calls - donations);
    let score = Math.min(55, unproductiveCalls * 4);
    if (Number(donor.calls_to_donations_ratio) > 4) score += 20;
    if (donor.active_status === 'Inactive') score += 20;
    if (donor.eligibility_status !== 'eligible') score += 10;
    return clamp(score);
  }

  function isCompatible(donorBlood, patientBlood) {
    return Boolean(BLOOD_COMPATIBILITY[donorBlood]?.includes(patientBlood));
  }

  function calculateFinalMatchScore(donor, patient) {
    const reliability = calculateReliabilityScore(donor);
    const availability = calculateAvailabilityScore(donor);
    const fatigue = calculateFatigueScore(donor);
    const compatibility = donor.blood_group === patient.blood_group
      ? 100
      : isCompatible(donor.blood_group, patient.blood_group) ? 75 : 0;
    return clamp(reliability * 0.35 + availability * 0.35 + (100 - fatigue) * 0.2 + compatibility * 0.1);
  }

  function getCircleDonors(patient, data) {
    return {
      primary: patient.primary_donors.map(id => data.donorById[id]).filter(Boolean),
      backup: patient.backup_donors.map(id => data.donorById[id]).filter(Boolean)
    };
  }

  function calculateForecast(patient, now = new Date()) {
    const frequency = Math.max(1, Number(patient.frequency_days) || 21);
    const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    let next = parseDate(patient.expected_next_date) || parseDate(patient.last_transfusion_date) || today;
    while (next < today) next = new Date(next.getTime() + frequency * DAY_MS);

    const schedule = [];
    for (let index = 0; index < 5; index++) {
      const scheduled = new Date(next.getTime() + index * frequency * DAY_MS);
      const daysUntil = daysBetween(today, scheduled);
      schedule.push({
        date: toDateString(scheduled),
        daysUntil,
        risk: daysUntil <= 7 ? 'High' : daysUntil <= 21 ? 'Watch' : 'Planned'
      });
    }

    return {
      nextDate: schedule[0].date,
      daysUntil: schedule[0].daysUntil,
      schedule
    };
  }

  function readinessLevel(score) {
    if (score < 25) return 'Critical';
    if (score < 40) return 'High Risk';
    if (score < 70) return 'Medium Risk';
    return 'Low Risk';
  }

  function calculateReadinessScore(patient, data) {
    const circles = getCircleDonors(patient, data);
    const allDonors = [...circles.primary, ...circles.backup];
    const available = allDonors.filter(donor =>
      !['busy', 'out_of_area', 'unavailable'].includes(getDonorResponse(patient.id, donor.id).status) &&
      calculateAvailabilityScore(donor) >= 60 && calculateReliabilityScore(donor) >= 30
    );
    const primaryAvailable = circles.primary.filter(donor =>
      !['busy', 'out_of_area', 'unavailable'].includes(getDonorResponse(patient.id, donor.id).status) &&
      calculateAvailabilityScore(donor) >= 60 && calculateReliabilityScore(donor) >= 30
    );
    const backupAvailable = circles.backup.filter(donor =>
      !['busy', 'out_of_area', 'unavailable'].includes(getDonorResponse(patient.id, donor.id).status) &&
      calculateAvailabilityScore(donor) >= 60 && calculateReliabilityScore(donor) >= 30
    );
    const reliabilityAverage = allDonors.length
      ? allDonors.reduce((sum, donor) => sum + calculateReliabilityScore(donor), 0) / allDonors.length
      : 0;
    const coverageScore = Math.min(100, primaryAvailable.length * 24 + backupAvailable.length * 12);
    const volunteerScore = Math.min(100, patient.volunteers.length * 45 + (patient.coordinator ? 10 : 0));
    const forecast = calculateForecast(patient);
    const timePreparedness = forecast.daysUntil <= 3
      ? Math.min(100, available.length * 20)
      : forecast.daysUntil <= 10 ? Math.min(100, 35 + available.length * 12) : 85;
    const score = clamp(
      coverageScore * 0.4 +
      reliabilityAverage * 0.3 +
      volunteerScore * 0.15 +
      timePreparedness * 0.15
    );

    return {
      score,
      level: readinessLevel(score),
      availableDonors: available.length,
      primaryAvailable: primaryAvailable.length,
      reliabilityAverage: Math.round(reliabilityAverage),
      volunteerCoverage: patient.volunteers.length
    };
  }

  function getDonorScores(donor, patient) {
    return {
      reliability: calculateReliabilityScore(donor),
      availability: calculateAvailabilityScore(donor),
      fatigue: calculateFatigueScore(donor),
      finalMatch: patient ? calculateFinalMatchScore(donor, patient) : null
    };
  }

  function fatigueLevel(score) {
    if (score >= 70) return 'High';
    if (score >= 40) return 'Medium';
    return 'Low';
  }

  function getOutreachState(patientId) {
    const allState = JSON.parse(localStorage.getItem('carecircle_outreach_state') || '{}');
    return allState[patientId] || { level: 0, statuses: {}, bankConfirmed: false };
  }

  function saveOutreachState(patientId, state) {
    const allState = JSON.parse(localStorage.getItem('carecircle_outreach_state') || '{}');
    allState[patientId] = state;
    localStorage.setItem('carecircle_outreach_state', JSON.stringify(allState));
  }

  function getPatientStatus(patient) {
    const statuses = JSON.parse(localStorage.getItem('carecircle_patient_statuses') || '{}');
    return Number.isInteger(statuses[patient.id]) ? statuses[patient.id] : patient.status_index;
  }

  function savePatientStatus(patientId, statusIndex) {
    const statuses = JSON.parse(localStorage.getItem('carecircle_patient_statuses') || '{}');
    statuses[patientId] = statusIndex;
    localStorage.setItem('carecircle_patient_statuses', JSON.stringify(statuses));
  }

  function getDonorResponses() {
    return JSON.parse(localStorage.getItem('carecircle_donor_responses') || '{}');
  }

  function getDonorResponse(patientId, donorId) {
    const responses = getDonorResponses();
    return responses[`${patientId}:${donorId}`] || {
      status: 'pending',
      availability: 'Awaiting response',
      location: 'Not shared',
      availableFrom: '',
      note: '',
      updatedAt: null
    };
  }

  function saveDonorResponse(patientId, donorId, response) {
    const responses = getDonorResponses();
    responses[`${patientId}:${donorId}`] = {
      ...response,
      updatedAt: new Date().toISOString()
    };
    localStorage.setItem('carecircle_donor_responses', JSON.stringify(responses));
    return responses[`${patientId}:${donorId}`];
  }

  function getConnectionPlan(patient, data) {
    const circles = getCircleDonors(patient, data);
    const assigned = [
      ...circles.primary.map(donor => ({ donor, role: 'Primary' })),
      ...circles.backup.map(donor => ({ donor, role: 'Backup' }))
    ].map(item => ({
      ...item,
      response: getDonorResponse(patient.id, item.donor.id),
      match: calculateFinalMatchScore(item.donor, patient)
    }));

    const available = assigned
      .filter(item => item.response.status === 'available')
      .sort((a, b) => b.match - a.match);
    const pending = assigned
      .filter(item => item.response.status === 'pending')
      .sort((a, b) => b.match - a.match);
    const unavailable = assigned
      .filter(item => ['busy', 'out_of_area', 'unavailable'].includes(item.response.status));
    const assignedIds = new Set(assigned.map(item => item.donor.id));
    const alternates = data.donors
      .filter(donor =>
        !assignedIds.has(donor.id) &&
        isCompatible(donor.blood_group, patient.blood_group) &&
        calculateAvailabilityScore(donor) >= 60 &&
        calculateReliabilityScore(donor) >= 30
      )
      .map(donor => ({
        donor,
        role: 'Alternate',
        response: getDonorResponse(patient.id, donor.id),
        match: calculateFinalMatchScore(donor, patient)
      }))
      .sort((a, b) => b.match - a.match)
      .slice(0, 4);

    const recommended = available[0] || pending[0] || alternates[0] || null;
    return { assigned, available, pending, unavailable, alternates, recommended };
  }

  window.CareCircle = {
    loadData,
    clamp,
    escapeHTML,
    formatDate,
    daysBetween,
    calculateReliabilityScore,
    calculateAvailabilityScore,
    calculateFatigueScore,
    calculateFinalMatchScore,
    calculateReadinessScore,
    calculateForecast,
    getCircleDonors,
    getDonorScores,
    fatigueLevel,
    getOutreachState,
    saveOutreachState,
    getPatientStatus,
    savePatientStatus,
    getDonorResponse,
    saveDonorResponse,
    getConnectionPlan,
    isCompatible
  };
})();
