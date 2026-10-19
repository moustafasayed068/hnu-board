// Turns a raw channel message into the fields board/ingest.py expects.
// Uses Cohere's free trial key (20 calls/min, 1,000 calls/month): one call per message.

import fs from 'node:fs';

const COHERE_URL = 'https://api.cohere.com/v2/chat';
const USAGE_FILE = './cohere-usage.json';

// Counts this bot's Cohere calls per month (the free key allows 1,000/month, shared with the
// site's Telegram import). Returns the count so far this month.
function countCall() {
  const month = new Date().toISOString().slice(0, 7); // e.g. 2026-10
  let usage = {};
  try {
    usage = JSON.parse(fs.readFileSync(USAGE_FILE, 'utf8').replace(/^\uFEFF/, ''));
  } catch {}
  usage[month] = (usage[month] || 0) + 1;
  try {
    fs.writeFileSync(USAGE_FILE, JSON.stringify(usage, null, 2));
  } catch {}
  return usage[month];
}

const SCHEMA = {
  type: 'object',
  properties: {
    is_relevant: { type: 'boolean' },
    kind: { type: 'string', enum: ['assignment', 'announcement'] },
    title: { type: 'string' },
    body: { type: 'string' },
    years: { type: 'array', items: { type: 'integer', enum: [1, 2, 3, 4] } },
    programs: { type: 'array', items: { type: 'string', enum: ['ds', 'mse', 'rse'] } },
    course_code: { type: 'string' },
    course_hint: { type: 'string' },
    deadline: { type: 'string' },
    submission_url: { type: 'string' },
    resource_url: { type: 'string' },
  },
  required: [
    'is_relevant', 'kind', 'title', 'body', 'years', 'programs',
    'course_code', 'course_hint', 'deadline', 'submission_url', 'resource_url',
  ],
};

export async function parsePost(text, { postedAt = new Date(), courses = [] } = {}) {
  if (process.env.COHERE_API_KEY) {
    try {
      return await parseWithCohere(text, postedAt, courses);
    } catch (e) {
      console.error('Cohere parse failed, falling back to regex:', e.message);
    }
  }
  return parseWithRegex(text);
}

async function parseWithCohere(text, postedAt, courses) {
  const courseList = courses.map((c) => `${c.code} | ${c.name} | level ${c.level}`).join('\n');
  const prompt =
    `Generate a JSON object describing this message from the WhatsApp channel of the Faculty of ` +
    `Computer Science & IT, Helwan National University. It was posted on ${postedAt.toISOString()}; ` +
    `Cairo time is UTC+03:00. Messages mix Egyptian Arabic and English.\n\n` +
    `Fields:\n` +
    `- is_relevant: false for greetings, notices about one specific student, polls or chit-chat\n` +
    `- kind: "assignment" if students must submit something by a deadline, else "announcement"\n` +
    `- title: short title (max ~80 chars), keep the original language\n` +
    `- body: the message text without greetings and sign-offs\n` +
    `- years: the levels / الفرقة (1-4) the message is for, as stated (e.g. "الفرقة الرابعة" or "4th year" = [4]; ` +
    `"الفرقة الثالثة والرابعة" = [3, 4]), or else the level of the matching course in the list below; ` +
    `[] if it is for all students or the level is unclear\n` +
    `- programs: any of "ds" (Data Science / داتا ساينس), "mse" (Multimedia), "rse" (Robotics); ` +
    `empty list if the message is for everyone\n` +
    `- course_code: the code of the matching course from the list below, else ""\n` +
    `- course_hint: the course name as written in the message, else ""\n` +
    `- deadline: ISO 8601 with +03:00 offset, resolving dates like "Saturday 17 October" to the next ` +
    `matching date on/after the posting date; "" if none\n` +
    `- submission_url: the link where students submit (e.g. a Google Form), else ""\n` +
    `- resource_url: any other link (sheet, slides, drive), else ""\n\n` +
    `Courses this semester (code | name | level):\n${courseList}\n\n` +
    `Message:\n"""\n${text}\n"""`;

  const res = await fetch(COHERE_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.COHERE_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: process.env.COHERE_MODEL || 'command-a-03-2025',
      messages: [{ role: 'user', content: prompt }],
      response_format: { type: 'json_object', schema: SCHEMA },
      temperature: 0,
    }),
  });
  const calls = countCall();
  if (calls % 50 === 0 || calls >= 900) {
    console.warn(`Cohere calls this month from the WhatsApp bot: ${calls} (free limit 1,000)`);
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);

  const data = await res.json();
  return JSON.parse(data.message.content[0].text);
}

// Without Cohere: posted as an announcement; the site needs the level in the text.
function parseWithRegex(text) {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  const links = text.match(/https?:\/\/\S+/g) || [];
  const yearMatch = text.match(/(?:level|الفرقة|المستوى)\s*(\d)/i);
  const ordinal = ['الأولى', 'الثانية', 'الثالثة', 'الرابعة']
    .findIndex((w) => text.includes(`الفرقة ${w}`) || text.includes(`المستوى ${w}`));
  return {
    is_relevant: text.length > 40,
    kind: 'announcement',
    title: lines[0]?.slice(0, 80) || 'Untitled',
    body: text,
    years: yearMatch ? [Number(yearMatch[1])] : ordinal >= 0 ? [ordinal + 1] : [], // [] = every level
    programs: [],
    course_code: '',
    course_hint: '',
    deadline: '',
    submission_url: '',
    resource_url: links[0] || '',
  };
}
