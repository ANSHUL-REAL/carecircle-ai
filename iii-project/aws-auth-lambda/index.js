const crypto = require('crypto');
const {
  DynamoDBClient,
  GetItemCommand,
  PutItemCommand,
  ScanCommand,
  UpdateItemCommand
} = require('@aws-sdk/client-dynamodb');
const { normalizePublicSignupRole } = require('./auth-logic');

const TABLE_NAME = process.env.USERS_TABLE || 'CareCircleUsers';
const AUTH_SECRET = process.env.AUTH_SECRET || 'carecircle-demo-secret';
const dynamo = new DynamoDBClient({});

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

function usernameFromEmail(email) {
  return String(email || '').split('@')[0].toLowerCase().replace(/[^a-z0-9._-]/g, '');
}

function makeLinkedId(role) {
  const prefix = role === 'donor' ? 'DON' : role === 'admin' ? 'ADM' : 'PAT';
  return `${prefix}-${Date.now().toString().slice(-6)}`;
}

function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
  const hash = crypto.pbkdf2Sync(String(password), salt, 100000, 32, 'sha256').toString('hex');
  return { salt, hash };
}

function verifyPassword(password, salt, expectedHash) {
  const { hash } = hashPassword(password, salt);
  return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(expectedHash, 'hex'));
}

function signSession(user) {
  const payload = {
    email: user.email,
    username: user.username,
    role: user.role,
    displayName: user.displayName || user.name,
    linkedId: user.linkedId,
    exp: Date.now() + 1000 * 60 * 60 * 8
  };
  const encoded = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = crypto.createHmac('sha256', AUTH_SECRET).update(encoded).digest('base64url');
  return `${encoded}.${sig}`;
}

function publicUser(item) {
  return {
    username: item.username.S,
    email: item.email.S,
    role: item.role.S,
    displayName: item.name.S,
    linkedId: item.linkedId.S,
    city: item.city && item.city.S ? item.city.S : '',
    bloodGroup: item.bloodGroup && item.bloodGroup.S ? item.bloodGroup.S : ''
  };
}

async function signup(body) {
  const name = String(body.name || '').trim();
  const email = String(body.email || '').trim().toLowerCase();
  const password = String(body.password || '');
  const role = normalizePublicSignupRole(body.role);
  const city = String(body.city || '').trim();
  const bloodGroup = String(body.bloodGroup || '').trim();

  if (!name || !email || !password || password.length < 6) {
    return response(400, { error: 'Name, email, and a 6-character password are required.' });
  }

  const linkedId = makeLinkedId(role);
  const username = usernameFromEmail(email);
  const passwordHash = hashPassword(password);
  const createdAt = new Date().toISOString();

  const item = {
    email: { S: email },
    username: { S: username },
    name: { S: name },
    role: { S: role },
    linkedId: { S: linkedId },
    city: { S: city },
    bloodGroup: { S: bloodGroup },
    passwordSalt: { S: passwordHash.salt },
    passwordHash: { S: passwordHash.hash },
    createdAt: { S: createdAt },
    lastLoginAt: { S: createdAt }
  };

  try {
    await dynamo.send(new PutItemCommand({
      TableName: TABLE_NAME,
      Item: item,
      ConditionExpression: 'attribute_not_exists(email)'
    }));
  } catch (error) {
    if (error.name === 'ConditionalCheckFailedException') {
      return response(409, { error: 'An account already exists for this email.' });
    }
    throw error;
  }

  const user = publicUser(item);
  return response(201, { ok: true, user, token: signSession(user) });
}

async function login(body) {
  const identity = String(body.identity || body.email || body.username || '').trim().toLowerCase();
  const password = String(body.password || '');
  const role = String(body.role || '').trim();

  if (!identity || !password) {
    return response(400, { error: 'Email/username and password are required.' });
  }

  let item;
  if (identity.includes('@')) {
    const result = await dynamo.send(new GetItemCommand({
      TableName: TABLE_NAME,
      Key: { email: { S: identity } }
    }));
    item = result.Item;
  } else {
    const result = await dynamo.send(new ScanCommand({
      TableName: TABLE_NAME,
      FilterExpression: 'username = :identity',
      ExpressionAttributeValues: {
        ':identity': { S: identity }
      }
    }));
    item = result.Items && result.Items[0];
  }
  if (!item || (role && item.role.S !== role) || !verifyPassword(password, item.passwordSalt.S, item.passwordHash.S)) {
    return response(401, { error: 'Invalid email, password, or role.' });
  }

  await dynamo.send(new UpdateItemCommand({
    TableName: TABLE_NAME,
    Key: { email: { S: item.email.S } },
    UpdateExpression: 'SET lastLoginAt = :now',
    ExpressionAttributeValues: { ':now': { S: new Date().toISOString() } }
  }));

  const user = publicUser(item);
  return response(200, { ok: true, user, token: signSession(user) });
}

async function logout(body) {
  const email = String(body.email || '').trim().toLowerCase();
  if (email) {
    await dynamo.send(new UpdateItemCommand({
      TableName: TABLE_NAME,
      Key: { email: { S: email } },
      UpdateExpression: 'SET lastLogoutAt = :now',
      ExpressionAttributeValues: { ':now': { S: new Date().toISOString() } }
    }));
  }
  return response(200, { ok: true });
}

exports.handler = async (event) => {
  if (event.requestContext && event.requestContext.http && event.requestContext.http.method === 'OPTIONS') {
    return response(200, { ok: true });
  }

  try {
    const body = parseBody(event);
    const path = event.rawPath || event.path || '';
    if (path.endsWith('/signup')) return signup(body);
    if (path.endsWith('/login')) return login(body);
    if (path.endsWith('/logout')) return logout(body);
    return response(404, { error: 'Not found' });
  } catch (error) {
    console.error(error);
    return response(500, { error: 'Auth service failed.' });
  }
};
