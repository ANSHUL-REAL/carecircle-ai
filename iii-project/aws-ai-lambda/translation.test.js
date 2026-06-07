const test = require('node:test');
const assert = require('node:assert/strict');

const {
  languageByCode,
  normalizeTranslationRequest,
  parseTranslationOutput
} = require('./translation');

test('supports English plus six Indian languages', () => {
  assert.deepEqual(Object.keys(languageByCode), ['en', 'hi', 'bn', 'ta', 'te', 'mr', 'kn']);
});

test('normalizes translation text and caps the batch size', () => {
  const request = normalizeTranslationRequest({
    language: 'hi',
    texts: Array.from({ length: 130 }, (_, index) => ` Text ${index} `)
  });

  assert.equal(request.language.code, 'hi');
  assert.equal(request.texts.length, 120);
  assert.equal(request.texts[0], 'Text 0');
});

test('rejects unsupported languages', () => {
  assert.throws(
    () => normalizeTranslationRequest({ language: 'fr', texts: ['Hello'] }),
    /Unsupported language/
  );
});

test('parses Bedrock translation JSON and preserves text count', () => {
  const parsed = parseTranslationOutput('```json\n{"translations":["नमस्ते","रक्त खोजें"]}\n```', 2);
  assert.deepEqual(parsed, ['नमस्ते', 'रक्त खोजें']);
});
