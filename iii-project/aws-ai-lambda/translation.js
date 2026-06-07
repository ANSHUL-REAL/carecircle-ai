const languageByCode = {
  en: { code: 'en', label: 'English', bedrockName: 'English' },
  hi: { code: 'hi', label: 'Hindi', bedrockName: 'Hindi' },
  bn: { code: 'bn', label: 'Bengali', bedrockName: 'Bengali' },
  ta: { code: 'ta', label: 'Tamil', bedrockName: 'Tamil' },
  te: { code: 'te', label: 'Telugu', bedrockName: 'Telugu' },
  mr: { code: 'mr', label: 'Marathi', bedrockName: 'Marathi' },
  kn: { code: 'kn', label: 'Kannada', bedrockName: 'Kannada' }
};

function normalizeTranslationRequest(body) {
  const code = String(body.language || body.targetLanguage || '').trim().toLowerCase();
  const language = languageByCode[code];
  if (!language) throw new Error('Unsupported language');
  const texts = [...(Array.isArray(body.texts) ? body.texts : [])]
    .map((text) => String(text || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .slice(0, 120);
  if (texts.length === 0) throw new Error('No text supplied for translation');
  return { language, texts };
}

function buildTranslationPrompt(language, texts) {
  return [
    `Translate this CareCircle AI website UI text into ${language.bedrockName}.`,
    'Keep product names, medical blood groups such as A+, B-, O-, URLs, numbers, and IDs unchanged.',
    'Return only valid JSON with one key named translations. The value must be an array with exactly the same number of strings, in the same order.',
    `Texts: ${JSON.stringify(texts)}`
  ].join('\n\n');
}

function parseTranslationOutput(raw, expectedCount) {
  let cleaned = String(raw || '').trim()
    .replace(/^```json\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/```$/i, '')
    .trim();
  const firstBrace = cleaned.indexOf('{');
  const lastBrace = cleaned.lastIndexOf('}');
  if (firstBrace > 0 || lastBrace < cleaned.length - 1) {
    cleaned = firstBrace >= 0 && lastBrace > firstBrace
      ? cleaned.slice(firstBrace, lastBrace + 1)
      : cleaned;
  }
  const parsed = JSON.parse(cleaned);
  if (!Array.isArray(parsed.translations) || parsed.translations.length !== expectedCount) {
    throw new Error('Translation count mismatch');
  }
  return parsed.translations.map((text) => String(text || ''));
}

module.exports = {
  buildTranslationPrompt,
  languageByCode,
  normalizeTranslationRequest,
  parseTranslationOutput
};
