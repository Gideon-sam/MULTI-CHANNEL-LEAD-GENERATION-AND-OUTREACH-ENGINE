# Three owned-channel seed tests

The software can schedule tasks, track clicks and log replies. A passed unit test is not proof of delivery or scheduling on an external platform. Complete these steps using accounts you actually own; do not use creator contacts from the research output.

1. Copy `config/seed_accounts.template.json` to `config/seed_accounts.local.json`. Fill the real sending and receiving accounts for email, LinkedIn and Instagram. Set `ownership_confirmed` only after checking ownership. The local file is ignored by Git and excluded from packaging.
2. Choose a timezone-aware start time and plan nine touches (three per channel):

   `python -m incubrix_engine seed plan --start 2026-11-02T09:00:00+05:30 --base-url http://127.0.0.1:8081`

   Replace the example date with the actual intended date. This creates a real task schedule in SQLite and `seed_private/plan.csv`. It does not schedule a message inside LinkedIn, Instagram or email.
3. Start tracking: `python -m incubrix_engine seed serve --port 8081`. Use the generated URLs only from a device that can reach this endpoint. For a remote owned-device test, use an approved private reverse proxy or SSH forwarding; localhost links will not work on another device by themselves.
4. Inspect due tasks with `python -m incubrix_engine seed due`. Prepare the relevant channel's sequence from `output/outreach/channel_sequences.md`. Use the platform's allowed native scheduling/send workflow. Where native scheduling is unsupported, document that limitation; task reminders are not proof of native scheduling.
5. Save actual scheduled-state proof, then record it:

   `python -m incubrix_engine seed record --message-id <actual-id> --event native_scheduled --evidence <existing-evidence-file-or-https-url>`

6. After the native message is actually sent, record `--event sent` with real send proof. Open its tracking URL from the owned receiving account and send a real reply. Record `--event reply` with the reply evidence. The endpoint logs the click against the message ID and adds channel-specific UTM parameters to the IncuBrix destination.
7. Run `python -m incubrix_engine seed report`. Each channel needs scheduling, sent, click and reply evidence on the same test message. Evidence completeness still requires the candidate/reviewer to verify the external screenshots or records.

Replies, opt-outs and bounces suppress pending follow-ups to that recipient within the campaign. Duplicate event submissions are idempotent. The service does not retain IP addresses and does not log secret tracking tokens. Pre-send link checks do not count as post-send tracking proof.

Store evidence privately, redact unrelated personal information, and add the actual result to the workbook only after all three channels meet the brief. The current workbook does not claim this test passed.
