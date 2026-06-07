const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 8080);
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || '*';
const DATASET_PATH = path.join(__dirname, 'assets', 'carecircle-dataset.json');
const TRAINING_PATH = path.join(__dirname, 'assets', 'aws-training-data.json');

function sendJson(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization'
  });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error('Request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error('Invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

function loadDataset() {
  const raw = fs.readFileSync(DATASET_PATH, 'utf8');
  return JSON.parse(raw);
}

function getRows(data, key) {
  return Array.isArray(data[key]) ? data[key] : [];
}

function localAssistantAnswer(message) {
  const text = String(message || '').toLowerCase();
  if (text.includes('thalassemia') || text.includes('transfusion')) {
    return 'For thalassemia, regular monitoring, transfusion planning, and iron overload management are important. Please discuss exact timing and treatment with a qualified hematologist.';
  }
  if (text.includes('o-') || text.includes('universal')) {
    return 'O negative blood is commonly treated as the universal red-cell donor type in emergencies, but hospitals still confirm compatibility before transfusion.';
  }
  if (text.includes('donor') || text.includes('match')) {
    return 'I can help rank compatible donors by blood group, city, and readiness. Share the patient city and blood group to begin matching.';
  }
  return 'I am connected through the CareCircle AWS API. Ask me about donor matching, blood compatibility, thalassemia care, or transfusion planning.';
}

async function aiAssistant(message, history) {
  const aiBaseUrl = String(
    process.env.CARECIRCLE_AI_API_BASE_URL ||
    'https://nj7b75qyka.execute-api.ap-south-1.amazonaws.com'
  ).replace(/\/$/, '');
  const response = await fetch(`${aiBaseUrl}/ai/assistant`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      message: String(message || ''),
      history: Array.isArray(history) ? history : []
    })
  });

  if (!response.ok) {
    throw new Error(`AWS AI service failed with ${response.status}`);
  }
  const data = await response.json();
  return data.answer || localAssistantAnswer(message);
}

function matchDonors(payload) {
  const data = loadDataset();
  const donors = getRows(data, 'donors');
  const blood = String(payload.bloodGroup || payload.blood || '').toUpperCase();
  const city = String(payload.city || '').toLowerCase();
  return donors
    .filter((donor) => !blood || String(donor.blood_group || donor.blood || '').toUpperCase() === blood)
    .filter((donor) => {
      if (!city) return true;
      const donorPlace = String(donor.city || donor.location || '').toLowerCase();
      return donorPlace ? donorPlace.includes(city) : true;
    })
    .slice(0, 10);
}

function patientRisk(payload) {
  const scoreValue = payload.readinessScore !== undefined ? payload.readinessScore : payload.score;
  const daysValue = payload.daysUntilTransfusion !== undefined ? payload.daysUntilTransfusion : payload.daysUntil;
  const score = Number(scoreValue !== undefined ? scoreValue : 50);
  const daysUntil = Number(daysValue !== undefined ? daysValue : 14);
  const risk = score < 35 || daysUntil <= 3 ? 'high' : score < 60 || daysUntil <= 10 ? 'medium' : 'low';
  return { risk, score, daysUntil, generatedAt: new Date().toISOString() };
}

async function handle(req, res) {
  if (req.method === 'OPTIONS') return sendJson(res, 200, { ok: true });

  const url = new URL(req.url, `http://${req.headers.host}`);

  try {
    if (req.method === 'GET' && url.pathname === '/api/health') {
      return sendJson(res, 200, {
        ok: true,
        service: 'carecircle-aws-api',
        budgetMode: '20-usd-safe',
        aiProvider: 'amazon-bedrock',
        time: new Date().toISOString()
      });
    }

    if (req.method === 'POST' && url.pathname === '/api/match-donors') {
      return sendJson(res, 200, { matches: matchDonors(await readBody(req)) });
    }

    if (req.method === 'POST' && url.pathname === '/api/patient-risk') {
      return sendJson(res, 200, patientRisk(await readBody(req)));
    }

    if (req.method === 'POST' && url.pathname === '/api/train-data') {
      const body = await readBody(req);
      const rows = Array.isArray(body.rows) ? body.rows : [];
      fs.writeFileSync(TRAINING_PATH, JSON.stringify({ rows, updatedAt: new Date().toISOString() }, null, 2));
      return sendJson(res, 200, { ok: true, storedRows: rows.length, path: 'assets/aws-training-data.json' });
    }

    if (req.method === 'POST' && url.pathname === '/api/assistant') {
      const body = await readBody(req);
      const answer = await aiAssistant(body.message, body.history);
      return sendJson(res, 200, { answer });
    }

    sendJson(res, 404, { error: 'Not found' });
  } catch (error) {
    sendJson(res, 500, { error: error.message });
  }
}

http.createServer(handle).listen(PORT, '0.0.0.0', () => {
  console.log(`CareCircle AWS API listening on http://0.0.0.0:${PORT}`);
});
