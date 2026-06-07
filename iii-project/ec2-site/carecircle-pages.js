document.addEventListener('DOMContentLoaded', async () => {
  if (!window.CareCircle) return;

  const C = window.CareCircle;
  const page = document.body.dataset.page;
  if (!page) return;

  try {
    const data = await C.loadData();
    if (page === 'patient-circle') initPatientCircle(data);
    if (page === 'donor-profile') initDonorProfile(data);
    if (page === 'volunteer') initVolunteer(data);
    if (page === 'outreach') initOutreach(data);
    if (page === 'donor-response') initDonorResponse(data);
    if (page === 'admin') initOperations(data);
    if (page === 'home') initHomeMetrics(data);
    if (page === 'dataset') initDatasetExplorer(data);
  } catch (error) {
    document.querySelectorAll('[data-carecircle-loading]').forEach(element => {
      element.innerHTML = `<div class="data-error">Unable to load coordination data: ${C.escapeHTML(error.message)}</div>`;
    });
  }

  function riskClass(level) {
    return level.toLowerCase().replace(/\s+/g, '-');
  }

  function renderGauge(container, score, level, label = 'Support Readiness') {
    const circumference = 301.6;
    const offset = circumference - (score / 100) * circumference;
    container.innerHTML = `
      <div class="readiness-gauge ${riskClass(level)}">
        <svg viewBox="0 0 120 120" role="img" aria-label="${C.escapeHTML(label)} ${score} out of 100">
          <circle class="gauge-track" cx="60" cy="60" r="48"></circle>
          <circle class="gauge-progress" cx="60" cy="60" r="48" style="stroke-dashoffset:${offset}"></circle>
        </svg>
        <div class="gauge-value"><strong>${score}</strong><span>/100</span></div>
      </div>
      <div class="gauge-caption"><span>${C.escapeHTML(label)}</span><strong>${C.escapeHTML(level)}</strong></div>
    `;
  }

  function renderScoreBar(label, value, tone = '') {
    return `
      <div class="intelligence-score ${tone}">
        <div class="score-meta"><span>${C.escapeHTML(label)}</span><strong>${value}/100</strong></div>
        <div class="score-track"><span style="width:${value}%"></span></div>
      </div>
    `;
  }

  function populateSelect(select, items, getLabel) {
    select.innerHTML = items.map(item =>
      `<option value="${C.escapeHTML(item.id)}">${C.escapeHTML(getLabel(item))}</option>`
    ).join('');
  }

  function initPatientCircle(data) {
    const selector = document.getElementById('patient-selector');
    populateSelect(selector, data.patients, patient => `${patient.name} · ${patient.blood_group}`);
    const requestedId = new URLSearchParams(location.search).get('patient');
    if (requestedId && data.patientById[requestedId]) selector.value = requestedId;
    selector.addEventListener('change', render);
    render();

    async function render() {
      const patient = data.patientById[selector.value];
      let statusIndex = C.getPatientStatus(patient);

      try {
        const cases = await window.CareCircleAutomation.listCases();
        const cloudCase = cases.find(c => c.request.patient_name.toLowerCase() === patient.name.toLowerCase());
        if (cloudCase) {
          switch (cloudCase.state) {
            case 'DRAFT': statusIndex = 0; break;
            case 'PLANNED': statusIndex = 1; break;
            case 'OUTREACH_ACTIVE': statusIndex = 1; break;
            case 'DONOR_CONFIRMED': statusIndex = 2; break;
            case 'COORDINATING': statusIndex = 4; break;
            case 'FULFILLED': statusIndex = 5; break;
            case 'CANCELLED': statusIndex = 0; break;
          }
          C.savePatientStatus(patient.id, statusIndex);
        }
      } catch (err) {
        console.warn("Unable to fetch cloud case status for patient circle:", err);
      }

      const readiness = C.calculateReadinessScore(patient, data);
      const forecast = C.calculateForecast(patient);
      const circles = C.getCircleDonors(patient, data);

      document.getElementById('patient-name').textContent = patient.name;
      document.getElementById('patient-meta').textContent =
        `${patient.condition} · ${patient.location} · ${patient.frequency_days}-day cycle`;
      document.getElementById('patient-blood').textContent = patient.blood_group;
      document.getElementById('patient-avatar').textContent = patient.name.charAt(0);
      renderGauge(document.getElementById('readiness-gauge-container'), readiness.score, readiness.level);

      document.getElementById('readiness-factors').innerHTML = `
        <div><span>Available donors</span><strong>${readiness.availableDonors}</strong></div>
        <div><span>Primary ready</span><strong>${readiness.primaryAvailable}</strong></div>
        <div><span>Avg reliability</span><strong>${readiness.reliabilityAverage}%</strong></div>
        <div><span>Volunteer coverage</span><strong>${readiness.volunteerCoverage}</strong></div>
      `;

      const primaryNames = circles.primary.slice(0, 3).map(d => d.name.split(' ')[0]);
      const backupNames = circles.backup.slice(0, 3).map(d => d.name.split(' ')[0]);
      document.getElementById('care-circle-svg').innerHTML = `
        <circle cx="250" cy="250" r="220" class="circle-ring ring-escalation"></circle>
        <circle cx="250" cy="250" r="175" class="circle-ring ring-coordinator"></circle>
        <circle cx="250" cy="250" r="130" class="circle-ring ring-volunteer"></circle>
        <circle cx="250" cy="250" r="88" class="circle-ring ring-backup"></circle>
        <circle cx="250" cy="250" r="48" class="circle-ring ring-primary"></circle>
        <circle cx="250" cy="250" r="30" class="patient-node"></circle>
        <text x="250" y="246" class="circle-label center-label">${C.escapeHTML(patient.name.split(' ')[0])}</text>
        <text x="250" y="263" class="circle-label center-sub">${C.escapeHTML(patient.blood_group)}</text>
        <text x="250" y="193" class="circle-label">${C.escapeHTML(primaryNames.join(' · ') || 'Primary')}</text>
        <text x="250" y="146" class="circle-label">${C.escapeHTML(backupNames.join(' · ') || 'Backup')}</text>
        <text x="250" y="99" class="circle-label">${C.escapeHTML(patient.volunteers.join(' · '))}</text>
        <text x="250" y="54" class="circle-label">${C.escapeHTML(patient.coordinator)}</text>
        <text x="250" y="488" class="circle-label">Blood Bank Escalation</text>
      `;

      document.getElementById('circle-roster').innerHTML = [
        ...circles.primary.map(donorCard => circleMember(donorCard, patient, 'Primary')),
        ...circles.backup.map(donorCard => circleMember(donorCard, patient, 'Backup'))
      ].join('');
      renderConnectionBoard(patient);

      document.getElementById('forecast-summary').innerHTML = `
        <div><span>Last transfusion</span><strong>${C.formatDate(patient.last_transfusion_date)}</strong></div>
        <div><span>Expected next</span><strong>${C.formatDate(forecast.nextDate)}</strong></div>
        <div><span>Countdown</span><strong>${forecast.daysUntil} days</strong></div>
      `;
      document.getElementById('forecast-calendar').innerHTML = forecast.schedule.map((item, index) => `
        <div class="forecast-date ${item.risk.toLowerCase()}">
          <span>${index === 0 ? 'Next' : `Cycle ${index + 1}`}</span>
          <strong>${C.formatDate(item.date)}</strong>
          <small>${item.daysUntil} days · ${item.risk}</small>
        </div>
      `).join('');

      const stages = ['Request Prepared', 'Donors Assigned', 'Donor Confirmed', 'Backup Activated', 'Blood Ready', 'Transfusion Complete'];
      document.getElementById('patient-status-tracker').innerHTML = stages.map((stage, index) => `
        <div class="status-step ${index < statusIndex ? 'complete' : index === statusIndex ? 'active' : ''}">
          <span>${index < statusIndex ? '&#10003;' : index + 1}</span>
          <strong>${stage}</strong>
        </div>
      `).join('');
    }

    function circleMember(donor, patient, role) {
      const scores = C.getDonorScores(donor, patient);
      return `
        <a class="circle-member" href="donor-profile.html?donor=${C.escapeHTML(donor.id)}">
          <span class="circle-role">${role}</span>
          <strong>${C.escapeHTML(donor.name)}</strong>
          <small>${C.escapeHTML(donor.blood_group)} · Reliability ${scores.reliability}% · Match ${scores.finalMatch}%</small>
        </a>
      `;
    }

    function renderConnectionBoard(patient) {
      const plan = C.getConnectionPlan(patient, data);
      const availableCount = plan.available.length;
      const pendingCount = plan.pending.length;
      document.getElementById('connection-summary').innerHTML = `
        <span><strong>${availableCount}</strong> available</span>
        <span><strong>${pendingCount}</strong> pending</span>
        <span><strong>${plan.unavailable.length}</strong> need replacement</span>
      `;

      const recommendation = plan.recommended;
      document.getElementById('recommended-connection').innerHTML = recommendation
        ? `<div>
            <span class="recommendation-label">${recommendation.response.status === 'available' ? 'Confirmed donor' : recommendation.role === 'Alternate' ? 'Best replacement' : 'Next donor to contact'}</span>
            <strong>${C.escapeHTML(recommendation.donor.name)} · ${recommendation.donor.blood_group}</strong>
            <small>${recommendation.match}% match · ${C.escapeHTML(recommendation.role)} circle</small>
          </div>
          <a class="btn btn-primary btn-sm" href="${responseLink(patient.id, recommendation.donor.id)}">Open Connection</a>`
        : '<p class="empty-state">No compatible replacement is currently available. Escalate to the blood bank network.</p>';

      document.getElementById('donor-connection-grid').innerHTML = plan.assigned.map(item => {
        const statusLabel = {
          pending: 'Awaiting response',
          available: 'Available',
          busy: 'Busy at work',
          out_of_area: 'Out of area',
          unavailable: 'Unavailable'
        }[item.response.status];
        return `
          <article class="donor-connection-card ${item.response.status}">
            <div class="connection-card-head">
              <span>${C.escapeHTML(item.role)}</span>
              <b class="connection-status">${statusLabel}</b>
            </div>
            <h3>${C.escapeHTML(item.donor.name)}</h3>
            <p>${item.donor.blood_group} · ${item.match}% match</p>
            <small>${C.escapeHTML(item.response.location)}${item.response.note ? ` · ${C.escapeHTML(item.response.note)}` : ''}</small>
            <div class="connection-card-actions">
              <a class="btn btn-secondary btn-sm" href="${responseLink(patient.id, item.donor.id)}">Response Page</a>
              <button class="btn btn-secondary btn-sm copy-response-link" type="button" data-link="${responseLink(patient.id, item.donor.id)}">Copy Link</button>
            </div>
          </article>
        `;
      }).join('');

      document.getElementById('alternate-donor-list').innerHTML = plan.unavailable.length && plan.alternates.length
        ? `<div class="alternate-heading"><span>Automatic replacement pool</span><strong>${plan.alternates.length} compatible alternates</strong></div>
          <div class="alternate-grid">${plan.alternates.map(item => `
            <article>
              <div><strong>${C.escapeHTML(item.donor.name)}</strong><span>${item.donor.blood_group} · ${item.match}% match</span></div>
              <a href="${responseLink(patient.id, item.donor.id)}">Invite alternate</a>
            </article>
          `).join('')}</div>`
        : '';
    }

    function responseLink(patientId, donorId) {
      return `donor-response.html?patient=${encodeURIComponent(patientId)}&donor=${encodeURIComponent(donorId)}`;
    }

    document.getElementById('donor-connection-grid').addEventListener('click', async event => {
      const button = event.target.closest('.copy-response-link');
      if (!button) return;
      const absoluteLink = new URL(button.dataset.link, window.location.href).href;
      try {
        await navigator.clipboard.writeText(absoluteLink);
        button.textContent = 'Link Copied';
      } catch {
        button.textContent = 'Open & Copy URL';
      }
      setTimeout(() => { button.textContent = 'Copy Link'; }, 1800);
    });
  }

  function initDonorResponse(data) {
    const params = new URLSearchParams(location.search);
    const patient = data.patientById[params.get('patient')] || data.patients[0];
    const donor = data.donorById[params.get('donor')] || C.getCircleDonors(patient, data).primary[0];
    const existing = C.getDonorResponse(patient.id, donor.id);
    const forecast = C.calculateForecast(patient);

    document.getElementById('response-donor-name').textContent = donor.name;
    document.getElementById('response-donor-meta').textContent =
      `${donor.blood_group} · ${donor.donor_type} · ${C.calculateFinalMatchScore(donor, patient)}% match`;
    document.getElementById('response-patient-name').textContent = patient.name;
    document.getElementById('response-patient-meta').textContent =
      `${patient.condition} · ${patient.blood_group} · ${patient.location}`;
    document.getElementById('response-case-facts').innerHTML = `
      <div><span>Expected transfusion</span><strong>${C.formatDate(forecast.nextDate)}</strong></div>
      <div><span>Time remaining</span><strong>${forecast.daysUntil} days</strong></div>
      <div><span>Units needed</span><strong>${patient.quantity_required}</strong></div>
      <div><span>Care circle</span><strong>${patient.primary_donors.includes(donor.id) ? 'Primary' : 'Backup / Alternate'}</strong></div>
    `;

    const statusInput = document.querySelector(`input[name="response-status"][value="${existing.status}"]`);
    if (statusInput) statusInput.checked = true;
    document.getElementById('response-location').value = existing.location === 'Not shared' ? '' : existing.location;
    document.getElementById('response-available-from').value = existing.availableFrom || '';
    document.getElementById('response-note').value = existing.note || '';

    document.getElementById('donor-response-form').addEventListener('submit', async event => {
      event.preventDefault();
      const status = new FormData(event.currentTarget).get('response-status');
      const responseData = {
        status,
        availability: status.replaceAll('_', ' '),
        location: document.getElementById('response-location').value.trim() || 'Not shared',
        availableFrom: document.getElementById('response-available-from').value,
        note: document.getElementById('response-note').value.trim()
      };

      try {
        const cases = await window.CareCircleAutomation.listCases();
        const cloudCase = cases.find(c => c.request.patient_name.toLowerCase() === patient.name.toLowerCase());
        if (cloudCase) {
          const backendStatus = status === 'available' ? 'accepted' : 'declined';
          await window.CareCircleAutomation.submitResponse(cloudCase.id, {
            donor_id: donor.id,
            status: backendStatus
          });
        }
      } catch (err) {
        console.warn("Could not submit response to cloud automation API:", err);
      }

      C.saveDonorResponse(patient.id, donor.id, responseData);
      
      const plan = C.getConnectionPlan(patient, data);
      const replacementText = status === 'available'
        ? `You are now the recommended contact for ${patient.name}.`
        : plan.recommended
          ? `${plan.recommended.donor.name} is now the recommended alternate for the family.`
          : 'The case should now escalate to the blood bank network.';
      document.getElementById('response-success').innerHTML = `
        <strong>Response saved</strong>
        <p>${C.escapeHTML(replacementText)}</p>
        <a href="patient-circle.html?patient=${patient.id}">View updated patient connection board</a>
      `;
      document.getElementById('response-success').classList.add('visible');
    });
  }

  function initDonorProfile(data) {
    const selector = document.getElementById('donor-selector');
    populateSelect(selector, data.donors, donor => `${donor.name} · ${donor.blood_group}`);
    const requestedId = new URLSearchParams(location.search).get('donor');
    const search = document.getElementById('donor-search');
    function refreshOptions(query = '') {
      const term = query.trim().toLowerCase();
      const matches = data.donors.filter(donor =>
        !term || donor.name.toLowerCase().includes(term) ||
        donor.id.toLowerCase().includes(term) || donor.blood_group.toLowerCase().includes(term)
      ).slice(0, 150);
      const selected = data.donorById[selector.value] || data.donorById[requestedId];
      if (selected && !matches.some(donor => donor.id === selected.id)) matches.unshift(selected);
      populateSelect(selector, matches, donor => `${donor.name} | ${donor.blood_group} | ${donor.id}`);
      if (selected) selector.value = selected.id;
    }
    refreshOptions();
    if (requestedId && data.donorById[requestedId]) selector.value = requestedId;
    search.addEventListener('input', () => {
      refreshOptions(search.value);
      render();
    });
    selector.addEventListener('change', render);
    render();

    function render() {
      const donor = data.donorById[selector.value];
      const assignedPatients = donor.assigned_patients.map(id => data.patientById[id]).filter(Boolean);
      const focusPatient = assignedPatients[0] || data.patients[0];
      const scores = C.getDonorScores(donor, focusPatient);
      const fatigue = C.fatigueLevel(scores.fatigue);

      document.getElementById('donor-name-display').textContent = donor.name;
      document.getElementById('donor-meta').textContent =
        `${donor.donor_type} · Hyderabad · ${donor.donations_till_date} recorded donations`;
      document.getElementById('donor-blood-display').textContent = donor.blood_group;
      document.getElementById('donor-avatar').textContent = donor.name.charAt(0);
      const statusBadge = document.getElementById('donor-status');
      statusBadge.textContent = `${donor.active_status} · ${donor.eligibility_status}`;
      statusBadge.className = `badge ${donor.active_status === 'Active' ? 'badge-green' : 'badge-danger'}`;

      document.getElementById('intelligence-scores').innerHTML =
        renderScoreBar('Reliability Score', scores.reliability) +
        renderScoreBar('Availability Score', scores.availability) +
        renderScoreBar(`Fatigue Score · ${fatigue}`, scores.fatigue, fatigue.toLowerCase()) +
        renderScoreBar(`Match for ${focusPatient.name}`, scores.finalMatch);

      document.getElementById('cooldown-panel').innerHTML = `
        <div class="cooldown-value">${scores.availability}</div>
        <div>
          <span>Availability index</span>
          <strong>${C.escapeHTML(donor.eligibility_status)}</strong>
          <p>Next eligible: ${C.formatDate(donor.next_eligible_date)} · Last donation: ${C.formatDate(donor.last_donation_date)}</p>
        </div>
      `;

      document.getElementById('donation-history').innerHTML = buildDonationHistory(donor);
      document.getElementById('assigned-patients').innerHTML = assignedPatients.length
        ? assignedPatients.map(patient => {
          const match = C.calculateFinalMatchScore(donor, patient);
          return `<a href="patient-circle.html?patient=${patient.id}" class="assigned-patient">
            <strong>${C.escapeHTML(patient.name)}</strong>
            <span>${C.escapeHTML(patient.condition)} · ${patient.blood_group}</span>
            <b>${match}% match</b>
          </a>`;
        }).join('')
        : '<p class="empty-state">Not currently assigned to a recurring-care circle.</p>';
    }

    function buildDonationHistory(donor) {
      const last = donor.last_donation_date ? C.formatDate(donor.last_donation_date) : 'No recent donation';
      const bridge = donor.donated_earlier ? 'Completed a previous bridge donation' : 'No bridge donation recorded';
      return `
        <div class="history-event active"><span></span><div><strong>${last}</strong><p>Most recent recorded donation</p></div></div>
        <div class="history-event"><span></span><div><strong>${donor.donations_till_date} lifetime donations</strong><p>${bridge}</p></div></div>
        <div class="history-event"><span></span><div><strong>${donor.total_calls} outreach calls</strong><p>Calls-to-donations ratio: ${Number(donor.calls_to_donations_ratio).toFixed(2)}</p></div></div>
      `;
    }
  }

  function initVolunteer(data) {
    const patients = data.patients.map(patient => ({
      patient,
      readiness: C.calculateReadinessScore(patient, data),
      forecast: C.calculateForecast(patient)
    })).sort((a, b) => a.readiness.score - b.readiness.score);

    document.getElementById('volunteer-metrics').innerHTML = `
      <div class="metric-card"><span>Active cases</span><h2>${patients.length}</h2><p>Recurring-care circles</p></div>
      <div class="metric-card"><span>High-risk patients</span><h2>${patients.filter(item => item.readiness.score < 40).length}</h2><p>Readiness below 40</p></div>
      <div class="metric-card"><span>Pending follow-ups</span><h2>${patients.reduce((sum, item) => sum + Math.max(0, 3 - item.readiness.primaryAvailable), 0)}</h2><p>Primary confirmations needed</p></div>
      <div class="metric-card"><span>Next 14 days</span><h2>${patients.filter(item => item.forecast.daysUntil <= 14).length}</h2><p>Upcoming transfusions</p></div>
    `;

    document.getElementById('active-case-grid').innerHTML = patients.map(({ patient, readiness, forecast }) => `
      <article class="case-card ${riskClass(readiness.level)}">
        <div class="case-card-head"><span>${C.escapeHTML(patient.id)}</span><b>${readiness.score}/100</b></div>
        <h3>${C.escapeHTML(patient.name)}</h3>
        <p>${C.escapeHTML(patient.blood_group)} · ${C.escapeHTML(patient.condition)}</p>
        <div class="case-facts"><span>${forecast.daysUntil} days</span><span>${readiness.availableDonors} donors ready</span></div>
        <a class="btn btn-secondary btn-sm" href="patient-circle.html?patient=${patient.id}">Open Care Circle</a>
      </article>
    `).join('');

    const highRisk = patients.filter(item => item.readiness.score < 40);
    document.getElementById('high-risk-list').innerHTML = highRisk.length
      ? highRisk.map(({ patient, readiness }) => `<div class="alert-row">
          <div><strong>${C.escapeHTML(patient.name)}</strong><span>${readiness.level} · ${readiness.primaryAvailable} primary ready</span></div>
          <a href="outreach.html?patient=${patient.id}">Escalate</a>
        </div>`).join('')
      : '<p class="empty-state">No patient is currently below the critical readiness threshold.</p>';

    document.getElementById('follow-up-list').innerHTML = patients.map(({ patient, readiness }) => `
      <div class="follow-up-row">
        <span class="follow-up-priority">${readiness.primaryAvailable < 2 ? 'Priority' : 'Routine'}</span>
        <div><strong>${C.escapeHTML(patient.name)}</strong><p>Confirm ${Math.max(0, 3 - readiness.primaryAvailable)} primary donor slots</p></div>
        <a href="outreach.html?patient=${patient.id}">Open queue</a>
      </div>
    `).join('');

    document.getElementById('upcoming-calendar').innerHTML = patients
      .filter(item => item.forecast.daysUntil <= 14)
      .map(({ patient, forecast }) => `<div class="calendar-event">
        <strong>${C.formatDate(forecast.nextDate)}</strong>
        <span>${C.escapeHTML(patient.name)} · ${patient.blood_group}</span>
        <b>${forecast.daysUntil} days</b>
      </div>`).join('') || '<p class="empty-state">No transfusions scheduled in the next 14 days.</p>';
  }

  function initOutreach(data) {
    const selector = document.getElementById('outreach-patient-selector');
    populateSelect(selector, data.patients, patient => `${patient.name} · ${patient.blood_group}`);
    const requestedId = new URLSearchParams(location.search).get('patient');
    if (requestedId && data.patientById[requestedId]) selector.value = requestedId;
    selector.addEventListener('change', render);
    document.getElementById('auto-simulate').addEventListener('click', runSimulation);
    document.getElementById('reset-outreach').addEventListener('click', reset);
    render();

    function rankedDonors(patient) {
      const circles = C.getCircleDonors(patient, data);
      return [...circles.primary.map(d => ({ ...d, circle: 'Primary' })),
        ...circles.backup.map(d => ({ ...d, circle: 'Backup' }))]
        .map(donor => ({ ...donor, match: C.calculateFinalMatchScore(donor, patient) }))
        .sort((a, b) => b.match - a.match);
    }

    async function render() {
      const patient = data.patientById[selector.value];
      let state = C.getOutreachState(patient.id);

      try {
        const cases = await window.CareCircleAutomation.listCases();
        const cloudCase = cases.find(c => c.request.patient_name.toLowerCase() === patient.name.toLowerCase());
        if (cloudCase) {
          const approvals = await window.CareCircleAutomation.listApprovals();
          const caseApprovals = approvals.filter(appr => appr.case_id === cloudCase.id);
          
          const newStatuses = {};
          caseApprovals.forEach(appr => {
            if (appr.status === 'approved') {
              newStatuses[appr.donor_id] = 'Contacted';
            } else if (appr.status === 'pending') {
              newStatuses[appr.donor_id] = 'Awaiting Approval';
            }
          });

          // Check if any donor accepted or declined via local responses
          const circleDonors = C.getCircleDonors(patient, data);
          const allCircleDonors = [...circleDonors.primary, ...circleDonors.backup];
          allCircleDonors.forEach(donor => {
            const resp = C.getDonorResponse(patient.id, donor.id);
            if (resp && resp.status === 'available') {
              newStatuses[donor.id] = 'Confirmed';
            } else if (resp && ['busy', 'out_of_area', 'unavailable'].includes(resp.status)) {
              newStatuses[donor.id] = 'Declined';
            }
          });

          // Sync status index
          let localStatusIdx = 1;
          switch (cloudCase.state) {
            case 'DRAFT': localStatusIdx = 0; break;
            case 'PLANNED': localStatusIdx = 1; break;
            case 'OUTREACH_ACTIVE': localStatusIdx = 1; break;
            case 'DONOR_CONFIRMED': localStatusIdx = 2; break;
            case 'COORDINATING': localStatusIdx = 4; break;
            case 'FULFILLED': localStatusIdx = 5; break;
          }
          C.savePatientStatus(patient.id, localStatusIdx);

          state = {
            level: cloudCase.escalation_level,
            statuses: { ...state.statuses, ...newStatuses },
            bankConfirmed: cloudCase.state === 'COORDINATING' || cloudCase.state === 'FULFILLED'
          };
          C.saveOutreachState(patient.id, state);
        }
      } catch (err) {
        console.warn("Unable to sync outreach status with cloud:", err);
      }

      const donors = rankedDonors(patient);
      const statuses = donors.map(d => state.statuses[d.id] || 'Pending');
      const confirmed = statuses.filter(status => status === 'Confirmed').length + (state.bankConfirmed ? 1 : 0);
      const contacted = statuses.filter(status => status !== 'Pending' && status !== 'Awaiting Approval').length;

      document.getElementById('outreach-patient-meta').textContent =
        `${patient.condition} · ${patient.blood_group} · ${C.formatDate(C.calculateForecast(patient).nextDate)}`;
      document.getElementById('outreach-queue-body').innerHTML = donors.map((donor, index) => {
        const status = state.statuses[donor.id] || 'Pending';
        return `<tr>
          <td>${index + 1}</td>
          <td><strong>${C.escapeHTML(donor.name)}</strong><br><small>${donor.blood_group}</small></td>
          <td>${C.escapeHTML(donor.circle)}</td>
          <td>${donor.match}/100</td>
          <td><span class="outreach-status ${status.toLowerCase().replaceAll(' ', '-')}">${status}</span></td>
        </tr>`;
      }).join('');

      const levels = ['Primary Circle', 'Backup Circle', 'Volunteer Escalation', 'Coordinator Escalation', 'Blood Bank Escalation'];
      document.getElementById('escalation-ladder').innerHTML = levels.map((level, index) => `
        <div class="escalation-level ${index < state.level || (index === 4 && state.bankConfirmed) ? 'complete' : index === state.level ? 'active' : ''}">
          <span>${index < state.level || (index === 4 && state.bankConfirmed) ? '&#10003;' : index + 1}</span>
          <div>
            <strong>${level}</strong>
            <p>${index === 4 && state.bankConfirmed ? 'Completed · Blood bank support confirmed' : index < state.level ? 'Completed' : index === state.level ? 'Active response layer' : 'Standby'}</p>
          </div>
        </div>
      `).join('') + (state.bankConfirmed ? `
        <div class="bank-resolution-card">
          <span class="bank-resolution-icon">&#10003;</span>
          <div>
            <strong>Blood bank escalation resolved</strong>
            <p>Hyderabad Blood Bank Network confirmed support. The family and coordinator can now proceed with collection.</p>
          </div>
          <a href="map.html" class="btn btn-primary btn-sm">View Blood Banks</a>
        </div>
      ` : '');

      const responseRate = donors.length ? Math.round((contacted / donors.length) * 100) : 0;
      document.getElementById('response-analytics').innerHTML = `
        <div><span>Response rate</span><strong>${responseRate}%</strong></div>
        <div><span>Confirmed</span><strong>${confirmed}</strong></div>
        <div><span>Current level</span><strong>${state.level + 1}/5</strong></div>
        <div><span>Est. confirmation</span><strong>${state.bankConfirmed ? '11 min · Bank' : confirmed ? '4 min' : 'Pending'}</strong></div>
      `;
    }

    async function runSimulation() {
      const patient = data.patientById[selector.value];
      const donors = rankedDonors(patient);
      const button = document.getElementById('auto-simulate');
      button.disabled = true;

      try {
        // 1. Get or Create cloud case
        let cloudCase;
        const cases = await window.CareCircleAutomation.listCases();
        cloudCase = cases.find(c => c.request.patient_name.toLowerCase() === patient.name.toLowerCase());
        
        if (!cloudCase) {
          const payload = {
            patient_name: patient.name,
            blood_group: patient.blood_group,
            units: 1,
            hospital: patient.hospital || 'Hyderabad City Hospital',
            city: patient.location || 'Hyderabad',
            deadline: new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10),
            urgency: 'critical',
            diagnosis: patient.condition || 'Emergency'
          };
          const idempotencyKey = `case-${Date.now()}`;
          cloudCase = await window.CareCircleAutomation.createCase(payload, idempotencyKey);
          cloudCase = await window.CareCircleAutomation.planCase(cloudCase.id);
        }
        
        const caseId = cloudCase.id;

        // 2. Start outreach in backend
        await window.CareCircleAutomation.startCase(caseId);
        C.savePatientStatus(patient.id, 1);
        
        const state = { level: 0, statuses: {}, bankConfirmed: false };
        const primaryDonor = donors.find(donor => donor.circle === 'Primary');
        const backupDonor = donors.find(donor => donor.circle === 'Backup');
        
        if (primaryDonor) {
          state.statuses[primaryDonor.id] = 'Contacted';
          C.saveOutreachState(patient.id, state);
          await render();
          await wait(1000);
          
          // Submit declined response in backend
          await window.CareCircleAutomation.submitResponse(caseId, {
            donor_id: primaryDonor.id,
            status: 'declined'
          });
          state.statuses[primaryDonor.id] = 'Declined';
          C.saveOutreachState(patient.id, state);
          
          // Save locally
          C.saveDonorResponse(patient.id, primaryDonor.id, {
            status: 'unavailable',
            availability: 'Unavailable',
            location: 'Not shared',
            availableFrom: '',
            note: 'Busy this cycle'
          });
          await render();
          await wait(1000);
        }
        
        if (backupDonor) {
          state.level = 1;
          state.statuses[backupDonor.id] = 'Contacted';
          C.saveOutreachState(patient.id, state);
          await render();
          await wait(1000);
          
          // Submit accepted response in backend
          await window.CareCircleAutomation.submitResponse(caseId, {
            donor_id: backupDonor.id,
            status: 'accepted'
          });
          state.statuses[backupDonor.id] = 'Confirmed';
          C.saveOutreachState(patient.id, state);
          C.savePatientStatus(patient.id, 2); // Donor Confirmed
          
          // Save locally
          C.saveDonorResponse(patient.id, backupDonor.id, {
            status: 'available',
            availability: 'Available',
            location: 'Secunderabad',
            availableFrom: new Date().toISOString().slice(0, 10),
            note: 'Confirmed support for this cycle.'
          });
          await render();
        }
      } catch (err) {
        alert("Simulation failed: " + err.message);
      } finally {
        button.disabled = false;
      }
    }

    async function reset() {
      const patient = data.patientById[selector.value];
      C.saveOutreachState(patient.id, { level: 0, statuses: {}, bankConfirmed: false });
      
      // Clear local donor responses for this patient
      const circleDonors = C.getCircleDonors(patient, data);
      const allCircleDonors = [...circleDonors.primary, ...circleDonors.backup];
      allCircleDonors.forEach(donor => {
        C.saveDonorResponse(patient.id, donor.id, {
          status: 'pending',
          availability: 'Awaiting response',
          location: 'Not shared',
          availableFrom: '',
          note: ''
        });
      });
      
      C.savePatientStatus(patient.id, 0);

      // Close the cloud case if possible
      try {
        const cases = await window.CareCircleAutomation.listCases();
        const cloudCase = cases.find(c => c.request.patient_name.toLowerCase() === patient.name.toLowerCase() && c.state !== 'CANCELLED' && c.state !== 'FULFILLED');
        if (cloudCase) {
          await window.CareCircleAutomation.closeCase(cloudCase.id, 'cancelled');
        }
      } catch (err) {
        console.warn("Could not cancel cloud case on reset:", err);
      }

      await render();
    }

    function wait(ms) {
      return new Promise(resolve => setTimeout(resolve, ms));
    }
  }

  function initOperations(data) {
    const patientAnalytics = data.patients.map(patient => ({
      patient,
      readiness: C.calculateReadinessScore(patient, data),
      forecast: C.calculateForecast(patient)
    }));
    const avgReadiness = Math.round(patientAnalytics.reduce((sum, item) => sum + item.readiness.score, 0) / patientAnalytics.length);
    const retention = Math.round((data.source_summary.active_donors / data.source_summary.total_records) * 100);
    const escalated = patientAnalytics.filter(item => item.readiness.primaryAvailable < 2).length;

    setText('metric-donors', data.source_summary.total_records.toLocaleString());
    setText('metric-requests', data.patients.length);
    setText('metric-matches', `${avgReadiness}%`);
    setText('metric-countries', `${retention}%`);
    setText('metric-donors-label', 'Dataset Records');
    setText('metric-requests-label', 'Active Patients');
    setText('metric-matches-label', 'Avg Readiness');
    setText('metric-countries-label', 'Donor Retention');

    const counts = { 'Low Risk': 0, 'Medium Risk': 0, 'High Risk': 0, 'Critical': 0 };
    patientAnalytics.forEach(item => counts[item.readiness.level]++);
    document.getElementById('readiness-distribution').innerHTML = Object.entries(counts).map(([level, count]) => `
      <div class="distribution-row">
        <div><span>${level}</span><strong>${count}</strong></div>
        <div class="distribution-track"><span class="${riskClass(level)}" style="width:${count / data.patients.length * 100}%"></span></div>
      </div>
    `).join('');

    document.getElementById('operations-patients').innerHTML = patientAnalytics
      .sort((a, b) => a.readiness.score - b.readiness.score)
      .map(({ patient, readiness, forecast }) => `
        <a href="patient-circle.html?patient=${patient.id}" class="operations-patient">
          <span>${C.escapeHTML(patient.name)}</span>
          <small>${patient.blood_group} · ${forecast.daysUntil} days</small>
          <strong class="${riskClass(readiness.level)}">${readiness.score}</strong>
        </a>
      `).join('');

    document.getElementById('operations-summary').innerHTML = `
      <div><span>Active donor retention</span><strong>${retention}%</strong><small>${data.source_summary.active_donors.toLocaleString()} active records</small></div>
      <div><span>Primary-circle escalation</span><strong>${Math.round(escalated / data.patients.length * 100)}%</strong><small>${escalated} cases below two ready primary donors</small></div>
      <div><span>Bridge network coverage</span><strong>${data.source_summary.unique_bridges}</strong><small>Recurring-care bridge groups in source data</small></div>
    `;
  }

  function initHomeMetrics(data) {
    const readiness = data.patients.map(patient => C.calculateReadinessScore(patient, data).score);
    const average = Math.round(readiness.reduce((sum, value) => sum + value, 0) / readiness.length);
    setText('home-data-records', data.source_summary.total_records.toLocaleString());
    setText('home-bridge-count', data.source_summary.unique_bridges);
    setText('home-readiness-average', `${average}%`);
  }

  function initDatasetExplorer(data) {
    const search = document.getElementById('dataset-search');
    const role = document.getElementById('dataset-role');
    const blood = document.getElementById('dataset-blood');
    const body = document.getElementById('dataset-body');
    const status = document.getElementById('dataset-status');
    const prev = document.getElementById('dataset-prev');
    const next = document.getElementById('dataset-next');
    const pageSize = 25;
    let pageIndex = 0;

    setText('dataset-total', data.records.length.toLocaleString());
    setText('dataset-users', data.source_summary.unique_users.toLocaleString());
    setText('dataset-donors', data.donors.length.toLocaleString());
    setText('dataset-circles', data.patients.length.toLocaleString());
    role.innerHTML = '<option value="">All roles</option>' +
      Object.keys(data.source_summary.role_counts).map(value =>
        `<option value="${C.escapeHTML(value)}">${C.escapeHTML(value)}</option>`
      ).join('');

    function render() {
      const term = search.value.trim().toLowerCase();
      const filtered = data.records.filter(record =>
        (!role.value || record.role === role.value) &&
        (!blood.value || record.blood_group === blood.value) &&
        (!term || [record.id, record.entity_id, record.bridge_id, record.role, record.blood_group, record.status]
          .some(value => String(value || '').toLowerCase().includes(term)))
      );
      const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
      pageIndex = Math.max(0, Math.min(pageIndex, pages - 1));
      const start = pageIndex * pageSize;
      body.innerHTML = filtered.slice(start, start + pageSize).map(record => `
        <tr>
          <td><strong>${C.escapeHTML(record.id)}</strong></td><td>${C.escapeHTML(record.entity_id)}</td>
          <td>${C.escapeHTML(record.role)}</td><td><strong>${C.escapeHTML(record.blood_group)}</strong></td>
          <td>${C.escapeHTML(record.gender || 'Not specified')}</td><td>${C.escapeHTML(record.bridge_id || 'Unassigned')}</td>
          <td><span class="badge ${record.active_status === 'Active' ? 'badge-green' : 'badge-orange'}">${C.escapeHTML(record.active_status || record.status || 'Unknown')}</span></td>
          <td>${record.donations_till_date}</td>
        </tr>
      `).join('') || '<tr><td colspan="8" class="dataset-empty">No records match these filters.</td></tr>';
      status.textContent = filtered.length
        ? `Showing ${start + 1}-${Math.min(start + pageSize, filtered.length)} of ${filtered.length.toLocaleString()} records | Page ${pageIndex + 1} of ${pages}`
        : '0 records';
      prev.disabled = pageIndex === 0;
      next.disabled = pageIndex >= pages - 1;
    }

    [search, role, blood].forEach(control => control.addEventListener('input', () => { pageIndex = 0; render(); }));
    prev.addEventListener('click', () => { pageIndex--; render(); });
    next.addEventListener('click', () => { pageIndex++; render(); });
    render();
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }
});
