// Listens to the faculty WhatsApp channel(s) and publishes each new post on the HNU Board.
import 'dotenv/config';
import { connect, logger } from './connect.js';
import { parsePost } from './parser.js';
import fs from 'node:fs';
import { fetchRecent, loadState, saveState } from './catchup.js';

// One line per handled post (time, what happened, start of the text), to see later why a post is missing.
function history(time, result, text) {
  const line = { at: new Date(time * 1000).toISOString(), result, text: (text || '').slice(0, 80) };
  try { fs.appendFileSync('./history.jsonl', JSON.stringify(line) + '\n'); } catch {}
}

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

// Ask the site whether this post is already there (e.g. forwarded via Telegram), to save an LLM call.
async function alreadyOnSite(source_id, text) {
  try {
    const res = await fetch(`${SITE}/ingest/`, {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ source_id, text, check_only: true }),
    });
    if (res.ok) return (await res.json()).duplicate === true;
  } catch {
    // site unreachable: carry on, publish() will retry and the site still rejects repeats
  }
  return false;
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
        return 'refused';
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
      const duplicate = body.includes('"duplicate": true') || body.includes('"duplicate":true');
      logger.info({ title: payload.title, result: body }, duplicate ? 'Already on the site (skipped)' : 'Published');
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
  if (!text) history(time, 'no text (skipped)', Object.keys(msg.message || {}).join(','));
  if (text && (await alreadyOnSite(`${jid}:${time}`, text))) {
    logger.info({ preview: text.slice(0, 60) }, 'Already on the site (skipped)');
    history(time, 'already on site (skipped)', text);
  } else if (text) {
    const postedAt = new Date(time * 1000);
    const parsed = await parsePost(text, { postedAt, courses: await getCourses() });
    if (!parsed.year) parsed.year = CHANNELS.get(jid); // level not in the text: use the channel's
    if (!parsed.is_relevant) {
      logger.info({ preview: text.slice(0, 60) }, 'Skipped (not relevant)');
      history(time, 'not relevant (skipped)', text);
    } else {
      const ok = await publish({
        ...parsed,
        // Channel + send time: the same in live and caught-up messages, so the site can ignore repeats.
        source_id: `${jid}:${time}`,
        text, // raw text: the site matches it with the same post forwarded via Telegram
        posted_at: postedAt.toISOString(),
      });
      history(time, ok === 'refused' ? 'refused by site (no level?)' : ok ? 'sent to site' : 'site unreachable', text);
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

// Runs inside the queue, so live messages that arrive meanwhile wait until the missed posts
// are handled (otherwise a live message moves the saved time forward and hides the older ones).
function catchUp(sock) {
  siteDown = false;
  for (const jid of CHANNELS.keys()) {
    queue = queue.then(async () => {
      try {
        const since = state[jid];
        const { messages, counts } = await fetchRecent(sock, jid);
        const missed = messages.filter((m) => Number(m.messageTimestamp) > since);
        logger.info({ channel: jid, fetched: counts, missed: missed.length }, 'Checked for missed posts');
        for (const msg of missed) {
          try {
            await handle(msg);
          } catch (e) {
            logger.error({ err: e.message }, 'Failed to handle message');
          }
        }
      } catch (e) {
        logger.warn({ channel: jid, err: e.message }, 'Could not fetch missed posts');
      }
    });
  }
  return queue;
}

await connect((sock) => {
  sock.ev.on('messages.upsert', ({ messages }) => enqueue(messages));
  sock.ev.on('connection.update', ({ connection }) => {
    if (connection === 'open') catchUp(sock);
  });
});

logger.info({ channels: Object.fromEntries(CHANNELS) }, 'Watching channels');
