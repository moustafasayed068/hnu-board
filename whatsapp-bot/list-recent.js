// Usage (stop the bot first): npm run list-recent
// Prints the channel's recent posts and whether the bot already counts them as handled.
import 'dotenv/config';
import { connect } from './connect.js';
import { fetchRecent, loadState } from './catchup.js';

const state = loadState();
const cairo = (t) => new Date(t * 1000).toLocaleString('en-GB', { timeZone: 'Africa/Cairo' });

function textOf(message = {}) {
  const m = message.ephemeralMessage?.message || message.viewOnceMessage?.message ||
    message.viewOnceMessageV2?.message || message;
  return (m.conversation || m.extendedTextMessage?.text || m.imageMessage?.caption ||
    m.videoMessage?.caption || m.documentMessage?.caption ||
    m.documentWithCaptionMessage?.message?.documentMessage?.caption || '').trim();
}

let done = false;
await connect((sock) => {
  sock.ev.on('connection.update', async ({ connection }) => {
    if (connection !== 'open' || done) return;
    done = true;
    for (const jid of Object.keys(state)) {
      console.log(`\nChannel ${jid}\nSaved time (handled up to): ${cairo(state[jid])}\n`);
      try {
        const { messages } = await fetchRecent(sock, jid);
        messages.forEach((m, i) => {
          const t = Number(m.messageTimestamp);
          const text = textOf(m.message).replace(/\s+/g, ' ');
          const mark = t > state[jid] ? 'NEW   ' : 'old   ';
          const kind = text ? text.slice(0, 70) : `(no text: ${Object.keys(m.message || {}).join(', ')})`;
          console.log(`${String(i + 1).padStart(2)}. ${mark}${cairo(t)}  ${kind}`);
        });
      } catch (e) {
        console.error('Fetch failed:', e.message);
      }
    }
    setTimeout(() => process.exit(0), 2000);
  });
});
