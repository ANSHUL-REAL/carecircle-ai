const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');

const {
  validateBearerToken,
  publicPatientProfile,
  caseSummary
} = require('./context');

function token(payload, secret) {
  const encoded = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = crypto.createHmac('sha256', secret)
    .update(encoded)
    .digest('base64url');
  return `${encoded}.${signature}`;
}

test('validates the signed bearer token and returns its patient identity', () => {
  const secret = 'test-secret';
  const signed = token({
    email: 'patient@example.com',
    role: 'patient',
    displayName: 'Anshul',
    exp: Date.now() + 60_000
  }, secret);

  const principal = validateBearerToken(`Bearer ${signed}`, secret);

  assert.equal(principal.email, 'patient@example.com');
  assert.equal(principal.role, 'patient');
});

test('rejects expired tokens', () => {
  const secret = 'test-secret';
  const signed = token({
    email: 'patient@example.com',
    role: 'patient',
    exp: Date.now() - 1
  }, secret);

  assert.throws(
    () => validateBearerToken(`Bearer ${signed}`, secret),
    /expired/i
  );
});

test('removes password fields from patient context', () => {
  const profile = publicPatientProfile({
    email: { S: 'patient@example.com' },
    name: { S: 'Anshul' },
    city: { S: 'Hyderabad' },
    bloodGroup: { S: 'A+' },
    passwordHash: { S: 'secret' },
    passwordSalt: { S: 'salt' }
  });

  assert.deepEqual(profile, {
    email: 'patient@example.com',
    name: 'Anshul',
    city: 'Hyderabad',
    bloodGroup: 'A+'
  });
});

test('summarizes owned cases without exposing storage internals', () => {
  assert.deepEqual(caseSummary({
    id: { S: 'case-1' },
    state: { S: 'OUTREACH_ACTIVE' },
    updated_at: { S: '2026-06-07T10:00:00Z' },
    request: {
      M: {
        blood_group: { S: 'A+' },
        hospital: { S: 'Apollo' },
        deadline: { S: '2026-06-08' }
      }
    }
  }), {
    id: 'case-1',
    state: 'OUTREACH_ACTIVE',
    bloodGroup: 'A+',
    hospital: 'Apollo',
    deadline: '2026-06-08',
    updatedAt: '2026-06-07T10:00:00Z'
  });
});
