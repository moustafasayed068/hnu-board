# WhatsApp → HNU Board: Setup

```
WhatsApp channel ──► bot (Oracle Cloud) ──► Cohere reads the message ──► POST /ingest/ ──► published on the site
```

The bot runs on a **spare number** that follows the channel. When a new post arrives, Cohere extracts the type, level, course, deadline and links, and the site publishes it immediately, credited to the user `whatsapp-bot`.

> ⚠️ This uses an unofficial WhatsApp library. **Never use your personal number**: WhatsApp can ban the number.

---

## 1) The site on PythonAnywhere (once)

Open a **Bash console** on PythonAnywhere:

```bash
cd ~/hnu-board                 # your project folder
git pull
source .venv/bin/activate      # or your virtualenv's name
python manage.py migrate
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output (this is the shared secret) and add it to `.env` on the server:

```bash
echo "INGEST_TOKEN=paste-the-secret-here" >> .env
```

Go to the **Web** tab and click **Reload**.

Check it works: `https://mosuatafa.pythonanywhere.com/ingest/courses/` should show `forbidden`, not a 404 page.

---

## 2) Cohere key (free)

1. Sign up at https://dashboard.cohere.com
2. Go to **API Keys** and copy the Trial key.

---

## 3) Oracle Cloud server (once)

1. Sign up at https://www.oracle.com/cloud/free/. It asks for a card to verify you, but the Always Free resources are free.
2. Go to **Compute → Instances → Create instance**:
   - Image: **Ubuntu**
   - Shape: anything marked **Always Free**
   - Click **Save private key** to download the key.
3. Connect to it: the easiest way is **Cloud Shell** (the `>_` icon at the top of the Oracle page). Or from your laptop:
   ```bash
   ssh -i key-file.key ubuntu@<server-IP>
   ```
4. Install Node and Git:
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
   sudo apt install -y nodejs git
   ```
5. Download the project:
   ```bash
   git clone https://github.com/moustafasayed068/hnu-board
   cd hnu-board/whatsapp-bot
   npm install
   cp .env.example .env
   nano .env
   ```
   Fill in `INGEST_TOKEN` (the same secret from step 1) and `COHERE_API_KEY`. Save with `Ctrl+O`, Enter, then `Ctrl+X`.

   > If the repo is private, GitHub will ask for a username and password. Use a **Personal Access Token** as the password.

---

## 4) Link the spare number and the channel

```bash
npm run find-channel -- "https://whatsapp.com/channel/XXXXXXXX"
```

- A QR code appears. On the **spare phone**, go to WhatsApp → **Linked devices** → **Link a device** and scan it.
- The bot follows the channel by itself and prints a line like:
  `Add this to CHANNELS in .env:  120363...@newsletter=LEVEL`
- Put it in `.env`, replacing `LEVEL` with the channel's level. The level is used when a message doesn't state it.
  ```bash
  nano .env      # CHANNELS=120363...@newsletter=4
  ```
  For more than one channel, separate them with a comma: `CHANNELS=id1@newsletter=4,id2@newsletter=3`

---

## 5) Keep it running all the time

```bash
sudo npm install -g pm2
pm2 start index.js --name hnu-bot
pm2 save
pm2 startup        # copy the command it prints and run it
```

Watch it work:
```bash
pm2 logs hnu-bot
```
On the next post in the channel you'll see `Published`, and the post appears on the site.

---

## Day-to-day

| You want to | Command |
| --- | --- |
| Watch what's happening | `pm2 logs hnu-bot` |
| Update after a `git push` | `cd ~/hnu-board && git pull && cd whatsapp-bot && npm install && pm2 restart hnu-bot` |
| Restart it | `pm2 restart hnu-bot` |
| WhatsApp logged out | `pm2 stop hnu-bot && rm -rf auth && node index.js` → scan the QR again → `Ctrl+C` → `pm2 start hnu-bot` |

## Fixing mistakes

- Any wrong post: open the admin at `/manage/`. Use the **created by** filter and choose `whatsapp-bot` to see only the bot's posts. Edit or delete them (superuser only).
- `Site refused the post` in the logs means the bot couldn't tell which level the message was for. Add the post by hand.
- Attached files (PDFs and images) aren't uploaded. Only the text or caption goes through.

## When the bot was off

Every time it connects, the bot fetches the channel's last 30 posts and publishes any it hasn't handled yet. So if the PC was off, it catches up on its own as soon as it comes back on. The site never publishes the same post twice.

- `state.json` stores the time of the last post handled, per channel. On the first run it starts from "now", so it doesn't import the channel's old posts.
- If more than 30 posts went by while it was off, only the last 30 come through.
- If you move the bot to another machine, copy the `auth` folder and `state.json` along with it.
