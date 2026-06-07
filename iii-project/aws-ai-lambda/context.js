const crypto = require('crypto');

function validateBearerToken(authorization, secret) {
  if (!authorization || !authorization.startsWith('Bearer ')) {
    throw new Error('Bearer token required');
  }
  const token = authorization.slice('Bearer '.length).trim();
  const [encoded, suppliedSignature] = token.split('.');
  if (!encoded || !suppliedSignature) throw new Error('Malformed token');
  const expectedSignature = crypto.createHmac('sha256', secret)
    .update(encoded)
    .digest('base64url');
  if (!crypto.timingSafeEqual(
    Buffer.from(suppliedSignature),
    Buffer.from(expectedSignature)
  )) {
    throw new Error('Invalid token signature');
  }
  const payload = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
  if (!payload.exp || Number(payload.exp) <= Date.now()) {
    throw new Error('Token expired');
  }
  if (!payload.email || !payload.role) throw new Error('Malformed token payload');
  return payload;
}

function publicPatientProfile(item) {
  if (!item) return null;
  return {
    email: item.email?.S || '',
    name: item.name?.S || '',
    city: item.city?.S || '',
    bloodGroup: item.bloodGroup?.S || ''
  };
}

function caseSummary(item) {
  const request = item.request?.M || {};
  return {
    id: item.id?.S || '',
    state: item.state?.S || '',
    bloodGroup: request.blood_group?.S || '',
    hospital: request.hospital?.S || '',
    deadline: request.deadline?.S || '',
    updatedAt: item.updated_at?.S || ''
  };
}

module.exports = {
  validateBearerToken,
  publicPatientProfile,
  caseSummary
};
