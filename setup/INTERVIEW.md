# The first campaign, as a conversation

Use this when they did **not** paste a prompt from the builder. Ask in Hebrew, **one question at a time**,
wait for the answer, and keep each question to one line. Offer the builder as a shortcut once:
"אם נוח לך יותר למלא טופס עם תצוגה בטלפון, תכתוב 'פתח את הבונה'" → `ezra builder --open`.

Before the first question, quietly run `check` and `list`. Only mention what fails.

## The questions

1. **"מה אתה רוצה לשלוח למי שמגיב?"**
   (מדריך, פרק, קופון, הרשמה לסדנה...). Write down the gift in their words.
2. **"מה הלינק?"**
   Open it yourself (or let `show` probe it). A dead link cannot be fixed after the DM is sent.
   Ask: "זה דף שבו משאירים שם ומייל, או ישר לדבר עצמו?" If it is a signup page, the DM says so ("שם ומייל, ומיד מקבלים").
3. **"על איזה פוסט?"**
   Run `posts`, list the last 5 as "1. 18.10 · 5 ימים בבוידם...", let them pick a number.
   Not published yet → "נכין הכל עכשיו, ותכתוב לי ברגע שהוא עלה. אני יוצר את החוק לפני שמגיעות תגובות."
4. **"איזו מילה יגיבו?"**
   Then check it with them, out loud:
   - an everyday word (לינק, מדריך, תודה, מחיר, וואו)? → refuse, and offer two better ones from their topic.
   - two letters? too short, it hides inside other words. Ask for a longer one.
   - already used by a live campaign (`list`)? → choose another.
   Then say how it will match: on a post, "גם 'אשמח לבוט' וגם 'בוט 🙏' ייתפסו, ורק על הפוסט הזה".
   On a story: "רק תשובה שהיא המילה עצמה, אז אוסיף גם 'הבוט' ו'לבוט'".
5. **"רק לעוקבים, או לכולם?"**
   Both are fine. Everyone = more people reach the link. Followers only = more followers, fewer clicks.
   If followers only: the gate message gives permission to leave.
6. **"להוסיף כפתור 'תזכירו לי אחר כך'?"**
   Recommend yes for anything that takes more than 2 minutes to consume (a video, a course, a long guide):
   people see the reel on the bus. Ask how many hours (2, 4 or 8; 23 at most).
7. **"להוסיף כפתור 'שלחו לי גם למייל'?"**
   Recommend it only if they have a newsletter. Ask which one. Explain the two ways (`docs/newsletter.md`).

## Then

- Draft the DM, the button title and 4 public replies in their voice (ask: "אתם / אתה / את?" if unclear).
  Show the draft as it will look, let them edit.
- Write the campaign into config.json, run `show NAME`, translate it into what the commenter sees.
- Wait for "מאשר". Then `create NAME --yes`, the flows, `audit`.
- Walk them through the test from a second account (SKILL.md, C). Ask what the second phone shows.
- Close with two lines: "הבוט חי. כדי לראות מה קורה, תכתוב לי 'תפתח לי את הפאנל'."
