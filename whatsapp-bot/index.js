// Listens to the faculty WhatsApp channel(s) and publishes each new post on the HNU Board.
import 'dotenv/config';
import { connect, logger } from './connect.js';
import { parsePost } from './parser.js';
import { fetchRecent, loadState, saveState } from './catchup.js';

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

// Returns false only when the site couldn't be reached, so the message is retried later.
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
        return true;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
      logger.info({ title: payload.title, result: body }, 'Published');
      return true;
    } catch (e) {
      logger.warn({ attempt, err: e.message }, 'Send failed');
      await new Promise((r) => setTimeout(r, attempt * 5000));
    }
  }
  logger.error({ title: payload.title }, 'Site unreachable, will retry on next start');
  return false;
}

// Last handled message time per channel. The first run starts from "now",
// so old posts aren't imported (and don't use up the Cohere quota).
const state = loadState();
const startedAt = Math.floor(Date.now() / 1000);
for (const jid of CHANNELS.keys()) state[jid] ??= startedAt;
saveState(state);
let siteDown = false; // stop moving forward until the site is back, so nothing is skipped

async function handle(msg) {
  const jid = msg.key?.remoteJid;
  if (!jid || !CHANNELS.has(jid)) return;
  const time = Number(msg.messageTimestamp || 0);
  if (time <= state[jid]) return; // already handled (or from before the first run)

  const text = extractText(msg.message);
  if (text) {
    const postedAt = new Date(time * 1000);
    const parsed = await parsePost(text, { postedAt, courses: await getCourses() });
    if (!parsed.year) parsed.year = CHANNELS.get(jid); // level not in the text: use the channel's
    if (!parsed.is_relevant) {
      logger.info({ preview: text.slice(0, 60) }, 'Skipped (not relevant)');
    } else {
      const ok = await publish({
        ...parsed,
        // Channel + send time: the same in live and caught-up messages, so the site can ignore repeats.
        source_id: `${jid}:${time}`,
        posted_at: postedAt.toISOString(),
      });
      if (!ok) {
        siteDown = true;
        return;
      }
    }
  }
  if (!siteDown) {
    state[jid] = time;
    saveState(state);
  }
}

// Handle messages one at a time, in order, whether live or caught up.
let queue = Promise.resolve();
function enqueue(messages) {
  queue = queue.then(async () => {
    for (const msg of messages) {
      try {
        await handle(msg);
      } catch (e) {
        logger.error({ err: e.message }, 'Failed to handle message');
      }
    }
  });
  return queue;
}

async function catchUp(sock) {
  siteDown = false;
  for (const jid of CHANNELS.keys()) {
    try {
      const missed = (await fetchRecent(sock, jid)).filter((m) => m.messageTimestamp > state[jid]);
      if (missed.length) logger.info({ channel: jid, count: missed.length }, 'Catching up on missed posts');
      await enqueue(missed);
    } catch (e) {
      logger.warn({ channel: jid, err: e.message }, 'Could not fetch missed posts');
    }
  }
}

await connect((sock) => {
  sock.ev.on('messages.upsert', ({ messages }) => enqueue(messages));
  sock.ev.on('connection.update', ({ connection }) => {
    if (connection === 'open') catchUp(sock);
  });
});

logger.info({ channels: Object.fromEntries(CHANNELS) }, 'Watching channels');
