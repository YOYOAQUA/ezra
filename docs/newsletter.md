# From a comment to the newsletter

Two ways. They can use both in the same campaign.

## 1. The link is a signup page (simplest, most reliable)

The DM's button leads to a page with a form (name + email). After signing up, the page shows or sends the gift.
Every newsletter tool has this: Rav Messer (רב מסר) landing pages and forms, Mailchimp, ConvertKit, Flodesk, Beehiiv.

- In the DM, say it upfront: "שם ומייל, ומיד מקבלים". Surprises cost signups.
- Keep `utm` on the campaign (`"utm": "ig/dm/<campaign>"`). The button URL gets
  `?utm_source=ig&utm_medium=dm&utm_campaign=<campaign>`, and most tools store it with the subscriber.
- Add a separate list or tag per campaign, so they know which reel brought whom.

## 2. The email inside the DM (`email_capture`)

A button "📩 שלחו לי גם למייל". The person taps it, the bot asks for the email, they type it in the chat.
The flow checks it contains an @ (one retry if not), thanks them, and passes it on.

```json
"email_capture": {
  "button": "📩 שלחו לי גם למייל",
  "ask": "בכיף! כתבו לי כאן את המייל שלכם, ואשלח לשם גם את המדריך 👇",
  "thanks": "קיבלתי ✅ זה בדרך למייל שלכם. לא רואים? מציצים בקידומי מכירות",
  "retry": "נראה לי שזה לא מייל 🙂 אפשר לכתוב שוב, למשל name@gmail.com"
}
```

Where the email goes:

- **No webhook** (`newsletter.webhook_url` empty): it stays in Zernio. `ezra emails` exports everything to
  `~/Ezra/emails.csv`, to import into any newsletter tool (Rav Messer: Contacts → Import).
  The export reads the last 100 runs of each flow: run it once a week.
- **A webhook**: the flow posts `{"email": "...", "source": "instagram-dm", "campaign": "..."}` to
  `newsletter.webhook_url` the moment it arrives. Use a relay that adds the subscriber:
  - **Make** (free plan is enough): new scenario → "Webhooks → Custom webhook" (copy its URL into
    `newsletter.webhook_url`) → "Rav Messer → Add New Subscriber" (or Mailchimp/ConvertKit) → map `email`.
  - **Zapier**: "Webhooks by Zapier → Catch Hook" → the newsletter's "Add subscriber" action.
  - Rav Messer's own API signs every request and its token expires every 14 days, which a Zernio webhook cannot do.
    That is why it always goes through a relay.
- After setting the webhook, run `email NAME` again (delete the old email flow in Zernio first), and test it
  from a second account with a real address.

## Consent, in one line

They asked for it in writing, inside the chat, so it is a clear opt-in. Still, the first email they get should say
where they signed up ("ביקשת את המדריך באינסטגרם") and carry an unsubscribe link, like every newsletter.
