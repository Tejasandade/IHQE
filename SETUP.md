# IHQE Setup Instructions

## Telegram Bot Integration

To enable Telegram alerts for the IHQE engine, follow these steps:

1. **Create a Bot via BotFather:**
   - Open Telegram and search for `@BotFather`.
   - Send the command `/newbot` and follow the prompts to name your bot.
   - BotFather will provide an HTTP API token (e.g., `123456789:ABCdefGHIjklmNOPqrsTUVwxyz`). Keep this secure.

2. **Get your Chat ID:**
   - Start a conversation with your new bot and send a dummy message (e.g., "Hello").
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your browser.
   - Look for the `"chat":{"id": <CHAT_ID>}` field in the JSON response.

3. **Configure Environment Variables:**
   - Open `config/.env` in the IHQE root directory.
   - Add/update the following values:
     ```env
     TELEGRAM_ENABLED=True
     TELEGRAM_BOT_TOKEN=your_bot_token_here
     TELEGRAM_CHAT_ID=your_chat_id_here
     ```

4. **Testing the Connection:**
   - When `TELEGRAM_ENABLED=False`, alerts will simply log to the console as `[TELEGRAM (Disabled)]`.
   - When enabled, the alerts will be dispatched directly to your Telegram chat.
   - You can verify it works by starting the live engine and waiting for a cascade state change or a Tiingo reconnect.
