# Owned-account seed test handoff

The email, LinkedIn sender/recipient and Instagram sender/recipient supplied in the conversation
are entered in `config/seed_accounts.local.json`. This private file is ignored by Git and excluded
from the package. No passwords are needed by this engine, and it does not send messages.

The attempted local schedule/tracker launch was blocked by the environment's automatic approval
review. No schedule, send, click, reply or screenshot is being claimed as completed.

Run these from `D:\Growth` when you are ready to perform the test. The first command schedules
local reminders 15 minutes ahead; the second serves local tracking in a separate terminal:

```powershell
$seedStart = [DateTimeOffset]::UtcNow.AddMinutes(15).ToOffset([TimeSpan]::FromHours(5.5)).ToString('yyyy-MM-ddTHH:mm:sszzz')
.\.venv\Scripts\python.exe -m incubrix_engine seed plan --campaign incubrix_owned_20261029 --start $seedStart --base-url http://127.0.0.1:8081
```

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine seed serve --port 8081
```

Check `http://127.0.0.1:8081/health`, then open `seed_private/plan.csv`. It contains nine local
reminders and private tracking links. The campaign name must be new if a previous plan exists.
Local reminders alone are not proof of native sending or scheduling.

For each channel, use the corresponding owned accounts, schedule the test in the actual service
if supported, and capture recipient, content, time and scheduling evidence. Record scheduling,
send, click and reply evidence in the sequence described in [seed-evidence-checklist.md](seed-evidence-checklist.md).
Use the tracker links on this same computer; localhost on a phone addresses that phone.

If a service cannot schedule messages, document the limitation and leave that gate incomplete.
Do not substitute a public creator, fabricated events, or a local reminder for the required proof.

The final report command is:

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine seed report
```

Only fill the workbook's seed-test proof after the actual platform actions and screenshots exist.
