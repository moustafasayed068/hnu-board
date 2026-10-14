// Shared WhatsApp connection helper (QR login + auto-reconnect).
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from 'baileys';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

export const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

export async function connect(onSocket) {
  const { state, saveCreds } = await useMultiFileAuthState('./auth');
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: logger.child({ module: 'baileys' }, { level: 'warn' }),
    markOnlineOnConnect: false, // keep the phone receiving notifications normally
    syncFullHistory: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log('\nScan this QR with the SPARE phone: WhatsApp → Linked devices → Link a device\n');
      qrcode.generate(qr, { small: true });
    }
    if (connection === 'open') logger.info('Connected to WhatsApp');
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        logger.error('Logged out. Delete the ./auth folder and run again to re-link.');
        process.exit(1);
      }
      logger.warn({ code }, 'Connection closed, reconnecting in 5s…');
      setTimeout(() => connect(onSocket), 5000);
    }
  });

  onSocket(sock);
  return sock;
}
