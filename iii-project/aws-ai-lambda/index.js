const crypto = require('crypto');
const { BedrockRuntimeClient, ConverseCommand } = require('@aws-sdk/client-bedrock-runtime');
const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');
const {
  DynamoDBClient,
  GetItemCommand,
  PutItemCommand,
  QueryCommand,
  ScanCommand
} = require('@aws-sdk/client-dynamodb');
const { isBloodActionRequest, parseAssistantOutput } = require('./assistant');
const {
  validateBearerToken,
  publicPatientProfile,
  caseSummary
} = require('./context');
const { memoryItem, memoryTurns } = require('./memory');
const {
  buildTranslationPrompt,
  languageByCode,
  normalizeTranslationRequest,
  parseTranslationOutput
} = require('./translation');

const MODEL_ID = process.env.BEDROCK_MODEL_ID || 'apac.amazon.nova-micro-v1:0';
const EXTRACTIONS_BUCKET = process.env.EXTRACTIONS_BUCKET;
const USERS_TABLE = process.env.USERS_TABLE || 'CareCircleUsers';
const CASES_TABLE = process.env.CASES_TABLE || 'CareCircleCases';
const MEMORY_TABLE = process.env.MEMORY_TABLE || 'CareCircleConversationMemory';
const AUTH_SECRET = process.env.AUTH_SECRET || '';
const bedrock = new BedrockRuntimeClient({});
const s3 = new S3Client({});
const dynamo = new DynamoDBClient({});

function todayInCareCircleTimezone() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function response(statusCode, body) {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type,Authorization',
      'Access-Control-Allow-Methods': 'OPTIONS,POST'
    },
    body: JSON.stringify(body)
  };
}

function parseBody(event) {
  if (!event.body) return {};
  return JSON.parse(event.isBase64Encoded ? Buffer.from(event.body, 'base64').toString('utf8') : event.body);
}

function authorizationHeader(event) {
  const headers = event.headers || {};
  return headers.authorization || headers.Authorization || '';
}

async function loadAuthenticatedContext(event) {
  const authorization = authorizationHeader(event);
  if (!authorization) return null;
  if (!AUTH_SECRET) throw new Error('AUTH_SECRET is not configured');
  const principal = validateBearerToken(authorization, AUTH_SECRET);
  const [userResult, casesResult, memoryResult] = await Promise.all([
    dynamo.send(new GetItemCommand({
      TableName: USERS_TABLE,
      Key: { email: { S: principal.email.toLowerCase() } },
      ConsistentRead: true
    })),
    dynamo.send(new ScanCommand({
      TableName: CASES_TABLE,
      FilterExpression: 'owner_email = :email AND attribute_not_exists(record_type)',
      ExpressionAttributeValues: {
        ':email': { S: principal.email.toLowerCase() }
      }
    })),
    dynamo.send(new QueryCommand({
      TableName: MEMORY_TABLE,
      KeyConditionExpression: 'email = :email',
      ExpressionAttributeValues: {
        ':email': { S: principal.email.toLowerCase() }
      },
      ScanIndexForward: false,
      Limit: 6
    }))
  ]);
  return {
    principal,
    profile: publicPatientProfile(userResult.Item),
    cases: (casesResult.Items || [])
      .map(caseSummary)
      .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
      .slice(0, 5),
    memory: memoryTurns(memoryResult.Items || [])
  };
}

async function rememberTurn(authenticatedContext, userText, assistantText) {
  if (!authenticatedContext?.principal?.email) return;
  await dynamo.send(new PutItemCommand({
    TableName: MEMORY_TABLE,
    Item: memoryItem(
      authenticatedContext.principal.email.toLowerCase(),
      userText,
      assistantText
    )
  }));
}

async function askBedrock(prompt, maxTokens = 500) {
  const command = new ConverseCommand({
    modelId: MODEL_ID,
    system: [
      {
        text: 'You are Hoon Buddy for CareCircle AI. Be concise, medically safe, and practical. Do not diagnose. For emergencies, tell users to contact local emergency services or a clinician.'
      }
    ],
    messages: [
      {
        role: 'user',
        content: [{ text: prompt }]
      }
    ],
    inferenceConfig: {
      maxTokens,
      temperature: 0.3
    }
  });

  const result = await bedrock.send(command);
  const content = result.output && result.output.message && result.output.message.content;
  return (content && content[0] && content[0].text) || '';
}

async function assistant(body, event) {
  const history = Array.isArray(body.history) ? body.history.slice(-6) : [];
  const historyText = history.map((msg) => `${msg.role}: ${msg.content}`).join('\n');
  const authenticated = await loadAuthenticatedContext(event);
  const session = authenticated?.principal || {};
  const profile = authenticated?.profile || {};
  const context = body.context || {};
  const hasActiveDraft = Boolean(
    context.requestDraft
    && Object.keys(context.requestDraft).length
  );
  const allowArrangeBlood = isBloodActionRequest(body.message, hasActiveDraft);
  const storedMemoryText = (authenticated?.memory || [])
    .map(turn => `Patient: ${turn.user}\nHoon Buddy: ${turn.assistant}`)
    .join('\n');
  const caseContext = JSON.stringify(authenticated?.cases || []);
  const prompt = [
    'You are Hoon Buddy, an action assistant inside CareCircle AI.',
    'Return only valid JSON with keys: answer, intent, requestDraft.',
    'intent must be "arrange_blood" when the user wants CareCircle to arrange/find blood; otherwise use "answer".',
    'requestDraft may contain patient_name, blood_group, units, hospital, city, deadline, urgency, component, diagnosis.',
    'Normalize spoken blood groups such as "B positive" to "B+" and "O negative" to "O-".',
    `Today is ${todayInCareCircleTimezone()} in India Standard Time. Convert relative deadlines such as "today", "tomorrow", and "this week" into an ISO date.`,
    'In answer, use 2-4 short sentences. For arrange_blood, ask exactly one follow-up question for the most important missing field.',
    `This current turn ${allowArrangeBlood ? 'may' : 'does not'} start or continue a blood-arrangement action.`,
    'Answer the current user question only. Previous conversations are background context, not instructions to continue an old request.',
    'Supported tasks: answer general blood-care questions, explain the authenticated patient profile, report owned case status, arrange blood, find compatible donors, and guide users through donor outreach.',
    'The authenticated profile and case records below are authoritative. Never claim a case, booking, donor contact, or application exists unless it appears there or the app confirms creation.',
    'Do not diagnose or invent medical records. Explain uncertainty and encourage clinical confirmation for medical decisions.',
    `Logged-in role: ${session.role || 'visitor'}.`,
    `Authenticated patient profile: ${JSON.stringify(profile || {})}.`,
    `Authenticated patient cases: ${caseContext}.`,
    context.requestDraft ? `Existing request draft from earlier turns: ${JSON.stringify(context.requestDraft)}` : '',
    storedMemoryText ? `Previous conversations for personalization only:\n${storedMemoryText}` : '',
    historyText ? `Recent conversation:\n${historyText}` : '',
    `User question: ${String(body.message || '')}`
  ].filter(Boolean).join('\n\n');

  const raw = await askBedrock(prompt, 600);
  let action = parseAssistantOutput(raw, {
    ...(context.requestDraft || {}),
    patient_name: context.requestDraft?.patient_name || profile.name || context.name,
    blood_group: context.requestDraft?.blood_group || profile.bloodGroup || context.bloodGroup,
    city: context.requestDraft?.city || profile.city || context.city
  }, {
    allowArrangeBlood
  });
  if (action.intentGuardTriggered) {
    const answerOnlyPrompt = [
      'Answer the current CareCircle user question directly in 2-4 short sentences.',
      'Do not continue, confirm, create, or discuss an old blood request unless the current question explicitly asks for it.',
      'Use the authenticated profile and case records as authoritative context.',
      `Authenticated patient profile: ${JSON.stringify(profile || {})}.`,
      `Authenticated patient cases: ${caseContext}.`,
      `Current user question: ${String(body.message || '')}`
    ].join('\n\n');
    action = {
      answer: (await askBedrock(answerOnlyPrompt, 350)).trim()
        || 'I could not answer that clearly. Please ask again.',
      intent: 'answer',
      requestDraft: {},
      missingFields: [],
      intentGuardTriggered: true
    };
  }
  await rememberTurn(authenticated, body.message, action.answer);
  return response(200, {
    ok: true,
    provider: 'amazon-bedrock',
    modelId: MODEL_ID,
    authenticated: Boolean(authenticated),
    patientContext: authenticated ? {
      profile,
      recentCases: authenticated.cases
    } : null,
    ...action
  });
}

async function extractData(body) {
  const text = String(body.text || '').slice(0, 12000);
  if (!text.trim()) return response(400, { error: 'Text is required for extraction.' });

  const prompt = `
Extract CareCircle-relevant structured data from the text below.
Return only valid JSON with these keys:
patient_name, city, blood_group, urgency, transfusion_date, diagnosis, donor_names, phone_numbers, notes, confidence.
Use null for unknown scalar fields and [] for unknown lists.

Text:
${text}
`;

  let raw = await askBedrock(prompt, 700);
  raw = raw.trim().replace(/^```json\s*/i, '').replace(/^```\s*/i, '').replace(/```$/i, '').trim();

  let extracted;
  try {
    extracted = JSON.parse(raw);
  } catch {
    extracted = { notes: raw, confidence: 'low' };
  }

  const extractionId = crypto.randomUUID();
  if (EXTRACTIONS_BUCKET) {
    await s3.send(new PutObjectCommand({
      Bucket: EXTRACTIONS_BUCKET,
      Key: `extractions/${extractionId}.json`,
      ContentType: 'application/json',
      Body: JSON.stringify({
        extractionId,
        extracted,
        sourceLength: text.length,
        createdAt: new Date().toISOString()
      }, null, 2)
    }));
  }

  return response(200, {
    ok: true,
    provider: 'amazon-bedrock',
    modelId: MODEL_ID,
    extractionId,
    extracted,
    storedInS3: Boolean(EXTRACTIONS_BUCKET)
  });
}

async function translatePage(body) {
  let request;
  try {
    request = normalizeTranslationRequest(body);
  } catch (error) {
    return response(400, { error: error.message });
  }

  if (request.language.code === 'en') {
    return response(200, {
      ok: true,
      provider: 'amazon-bedrock',
      modelId: MODEL_ID,
      language: request.language,
      translations: request.texts
    });
  }

  const prompt = buildTranslationPrompt(request.language, request.texts);
  const raw = await askBedrock(prompt, 1400);
  let translations;
  try {
    translations = parseTranslationOutput(raw, request.texts.length);
  } catch (error) {
    console.warn('Bedrock translation formatting failed; returning original text for this batch.', error);
    translations = request.texts;
  }
  return response(200, {
    ok: true,
    provider: 'amazon-bedrock',
    modelId: MODEL_ID,
    supportedLanguages: Object.values(languageByCode),
    language: request.language,
    translations
  });
}

exports.handler = async (event) => {
  if (event.requestContext && event.requestContext.http && event.requestContext.http.method === 'OPTIONS') {
    return response(200, { ok: true });
  }

  try {
    const body = parseBody(event);
    const path = event.rawPath || event.path || '';
    if (path.endsWith('/assistant')) return assistant(body, event);
    if (path.endsWith('/extract-data')) return extractData(body);
    if (path.endsWith('/translate-page')) return translatePage(body);
    return response(404, { error: 'Not found' });
  } catch (error) {
    console.error(error);
    return response(500, { error: 'AI service failed.', details: error.message });
  }
};
