function memoryItem(email, userText, assistantText, now = Date.now()) {
  return {
    email: { S: email },
    turn_key: { S: String(now) },
    user_text: { S: String(userText || '').slice(0, 2000) },
    assistant_text: { S: String(assistantText || '').slice(0, 4000) },
    created_at: { S: new Date(now).toISOString() },
    expires_at: { N: String(Math.floor(now / 1000) + 60 * 60 * 24 * 90) }
  };
}

function memoryTurns(items) {
  return [...(items || [])]
    .sort((a, b) => Number(a.turn_key?.S || 0) - Number(b.turn_key?.S || 0))
    .map(item => ({
      user: item.user_text?.S || '',
      assistant: item.assistant_text?.S || ''
    }));
}

module.exports = { memoryItem, memoryTurns };
