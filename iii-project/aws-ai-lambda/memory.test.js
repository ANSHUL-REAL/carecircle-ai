const test = require('node:test');
const assert = require('node:assert/strict');

const { memoryItem, memoryTurns } = require('./memory');

test('stores compact authenticated conversation memory with expiry', () => {
  const item = memoryItem(
    'patient@example.com',
    'What is my case status?',
    'Your request is in outreach.',
    1_780_000_000_000
  );

  assert.equal(item.email.S, 'patient@example.com');
  assert.equal(item.turn_key.S, '1780000000000');
  assert.equal(item.user_text.S, 'What is my case status?');
  assert.equal(item.assistant_text.S, 'Your request is in outreach.');
  assert.ok(Number(item.expires_at.N) > 1_780_000_000);
});

test('returns memory turns in chronological order', () => {
  const turns = memoryTurns([
    {
      turn_key: { S: '200' },
      user_text: { S: 'Second question' },
      assistant_text: { S: 'Second answer' }
    },
    {
      turn_key: { S: '100' },
      user_text: { S: 'First question' },
      assistant_text: { S: 'First answer' }
    }
  ]);

  assert.deepEqual(turns, [
    { user: 'First question', assistant: 'First answer' },
    { user: 'Second question', assistant: 'Second answer' }
  ]);
});
