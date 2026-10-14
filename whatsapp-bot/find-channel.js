// Usage: npm run find-channel -- https://whatsapp.com/channel/0029VaXXXXXXXX
// Follows the channel from the bot's number and prints its JID for CHANNELS in .env.
import 'dotenv/config';
import { connect } from './connect.js';

const link = process.argv[2];
const code = link?.split('/channel/')[1]?.split(/[/?]/)[0];
if (!code) {
  console.error('Pass the channel link: npm run find-channel -- https://whatsapp.com/channel/XXXX');
  process.exit(1);
}

let done = false;
await connect((sock) => {
  sock.ev.on('connection.update', async ({ connection }) => {
    if (connection !== 'open' || done) return;
    done = true;
    try {
      const meta = await sock.newsletterMetadata('invite', code);
      if (!meta) throw new Error('channel not found, check the link');
      await sock.newsletterFollow(meta.id);
      const name = meta.thread_metadata?.name?.text || meta.name || meta.id;
      console.log(`\nFollowing "${name}"`);
      console.log(`Add this to CHANNELS in .env:  ${meta.id}=LEVEL`);
      console.log('Replace LEVEL with the channel\'s level (1-4), or remove "=LEVEL" if it posts for all levels.\n');
    } catch (e) {
      console.error('Lookup failed:', e.message);
    }
    setTimeout(() => process.exit(0), 2000); // let the login session finish saving
  });
});
