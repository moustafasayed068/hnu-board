// Listens to the faculty WhatsApp channel(s) and publishes each new post on the HNU Board.
import 'dotenv/config';
import { connect, logger } from './connect.js';
import { parsePost } from './parser.js';

const SITE = process.env.SITE_URL.replace(/\/$/, ''); // e.g. https://mosuatafa.pythonanywhere.com
const HEADERS = { 'Content-Type': 'application/json', 'X-Ingest-Token': process.env.INGEST_TOKEN };

// CHANNELS="1203...@newsletter=4,1204...@newsletter" → channel id = default level (optional)
const CHANNELS = new Map(
  (process.env.CHANNELS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const [jid, level] = entry.split('=');
      return [jid.trim(), Number(level) || 0];
    }),
);
if (!CHANNELS.size) {
  logger.error('No CHANNELS set in .env. Run: npm run find-channel -- <channel link>');
  process.exit(1);
}

// Unwrap the message container and return its text or caption.
function extractText(message) {
  if (!message) return '';
  const m =
    message.ephemeralMessage?.message ||
    message.viewOnceMessage?.message ||
    message.viewOnceMessageV2?.message ||
    message;
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    m.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    ''
  ).trim();
}

async function getCourses() {
  try {
    const res = await fetch(`${SITE}/ingest/courses/`, { headers: HEADERS });
    if (res.ok) return (await res.json()).courses;
    logger.warn({ status: res.status }, 'Could not load courses');
  } catch (e) {
    logger.warn({ err: e.message }, 'Could not load courses');
  }
  return [];
}

async function publish(payload) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await fetch(`${SITE}/ingest/`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify(payload),
      });
      const body = await res.text();
      if (res.status === 422 || res.status === 403) {
        // The site understood but refused (e.g. no level found): retrying won't help.
        logger.error({ title: payload.title, body }, 'Site refused the post');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
      logger.info({ title: payload.title, result: body }, 'Published');
      return;
    } catch (e) {
      logger.warn({ attempt, err: e.message }, 'Send failed');
      await new Promise((r) => setTimeout(r, attempt * 5000));
    }
  }
  logger.error({ title: payload.title }, 'Giving up on this message');
}

async function handle(msg) {
  const jid = msg.key?.remoteJid;
  if (!jid || !CHANNELS.has(jid)) return;

  const text = extractText(msg.message);
  if (!text) return; // stickers, reactions, media without a caption

  const postedAt = new Date(Number(msg.messageTimestamp || Date.now() / 1000) * 1000);
  const parsed = await parsePost(text, { postedAt, courses: await getCourses() });
  if (!parsed.year) parsed.year = CHANNELS.get(jid); // level not in the text: use the channel's
  if (!parsed.is_relevant) {
    logger.info({ preview: text.slice(0, 60) }, 'Skipped (not relevant)');
    return;
  }

  await publish({
    ...parsed,
    source_id: `${jid}:${msg.key.id}`, // the site uses this to ignore duplicates
    posted_at: postedAt.toISOString(),
  });
}

await connect((sock) => {
  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const msg of messages) {
      try {
        await handle(msg);
      } catch (e) {
        logger.error({ err: e.message }, 'Failed to handle message');
      }
    }
  });
});

logger.info({ channels: Object.fromEntries(CHANNELS) }, 'Watching channels');
