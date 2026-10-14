// Remembers the last message handled per channel, and fetches what was missed
// while the bot was off (PC asleep, no internet...).
import fs from 'node:fs';
import { proto } from 'baileys';

const STATE_FILE = './state.json';
const FETCH_COUNT = 30; // recent channel posts to look at on every (re)connect

export function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return {}; // first run
  }
}

export function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// Walk the reply and collect every <message> node that carries a <plaintext> body.
function findMessageNodes(node, found = []) {
  if (!node || typeof node !== 'object') return found;
  const children = Array.isArray(node.content) ? node.content : [];
  if (node.tag === 'message' && children.some((c) => c?.tag === 'plaintext')) {
    found.push(node);
  }
  for (const child of children) findMessageNodes(child, found);
  return found;
}

// Turn the raw fetch reply into the same message shape that messages.upsert gives us.
export function parseFetched(jid, reply) {
  const messages = [];
  for (const node of findMessageNodes(reply)) {
    try {
      const plaintext = node.content.find((c) => c?.tag === 'plaintext');
      const buf = typeof plaintext.content === 'string'
        ? Buffer.from(plaintext.content, 'binary')
        : Buffer.from(plaintext.content);
      messages.push({
        key: { remoteJid: jid, id: node.attrs.message_id || node.attrs.server_id || node.attrs.id },
        message: proto.Message.decode(buf).toJSON(),
        messageTimestamp: Number(node.attrs.t),
      });
    } catch {
      // one unreadable post shouldn't stop the others
    }
  }
  return messages.sort((a, b) => a.messageTimestamp - b.messageTimestamp); // oldest first
}

export async function fetchRecent(sock, jid) {
  const reply = await sock.newsletterFetchMessages(jid, FETCH_COUNT);
  return parseFetched(jid, reply);
}
