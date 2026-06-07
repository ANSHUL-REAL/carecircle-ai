const test = require('node:test');
const assert = require('node:assert/strict');

const { normalizePublicSignupRole } = require('./auth-logic');

test('allows patient and donor public signup roles', () => {
  assert.equal(normalizePublicSignupRole('patient'), 'patient');
  assert.equal(normalizePublicSignupRole('donor'), 'donor');
});

test('does not allow public administrator signup', () => {
  assert.equal(normalizePublicSignupRole('admin'), 'patient');
});
