function normalizePublicSignupRole(role) {
  return role === 'donor' ? 'donor' : 'patient';
}

module.exports = { normalizePublicSignupRole };
