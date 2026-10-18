# Zernio, explained for a first-time user

Read this to the user one screen at a time. Their screens may be labelled slightly differently;
if they send a screenshot, follow what is on it.

## What Zernio is, in one sentence

"זה הצינור הרשמי בין Claude לאינסטגרם: Zernio מחובר לאינסטגרם דרך החיבור הרשמי של מטא,
ו-Claude מדבר עם Zernio עם מפתח. בלי סיסמה של אינסטגרם, ובלי שום עקיפה."

## Price (as of October 2026, zernio.com/pricing)

- Up to **2 connected accounts: free**, no credit card.
- Every feature is included in every tier: comments, DMs, automations, workflows.
- **10,000 outgoing messages a month free**. Above that $1 per 10,000, only if a card is on file.
  Without a card, sending simply stops at 10,000 until the next month.
- More accounts: $6 per account per month from the 3rd to the 10th.
  So: connect **only Instagram** (and maybe Facebook), not every network they have.

## The screens

1. **Sign up** at zernio.com (Google or email). No card.
2. **Connect Instagram**: "Connect account" → Instagram → log in to Instagram in the window that opens →
   approve the permissions. It must be a **professional** account (Business or Creator).
   - Asked to pick a Facebook page? Only for the Facebook connection; Instagram can connect on its own.
   - Approve everything it asks for, especially **messages** and **comments**. Without them the bot cannot answer.
3. **Profiles**: Zernio groups accounts in a "profile" (one per brand). One profile is enough.
4. **API key**: in the settings, "API Keys" → create a key → copy it **once** (it is shown once).
   It starts with something like `late_` or `sk_`. It goes only into `~/Ezra/.env` (`ezra key`).
   This key is a password to every account connected to Zernio: never into the chat, never on screen in a recording.
5. **Inbox / Automations / Workflows** in Zernio's own dashboard: everything the bot creates shows up there too.
   The user never has to build anything there by hand, but it is a good place to see a campaign with their own eyes,
   or switch one off from the phone.

## Two Instagram settings that block DMs (if `logs` shows permission errors)

- Instagram app → Settings → **Messages and story replies** → **Message controls** → **Connected tools** →
  **Allow access to messages**: on.
- Reconnect the account in Zernio after changing it.

## Words to use with the user

| Zernio says | say |
|---|---|
| comment automation | "החוק": מילה + הודעה, על פוסט אחד |
| workflow | "זרימה": מה קורה אחרי שלוחצים על כפתור |
| profile | "המותג" (קבוצה של חשבונות) |
| private reply | "ההודעה בפרטי" (אחת לכל תגובה, אף פעם לא שתיים) |
| Message Requests | "בקשות הודעות": לשם מגיעה הודעה למי שלא עוקב |
