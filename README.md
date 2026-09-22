# J.A.R.V.I.S. — your personal AI that runs everything

A fully local-first, **self-learning** AI butler that lives on your laptop,
sees what you're doing across all your machines, and gets itself ready
*before* you ask. The "JARVIS" from the Instagram vids — minus the arc reactor.

-  **Learns what you need and when** — every request and every app session is
  logged, habits are detected per day-of-week + hour (recency-weighted, so it
  adapts when your routine changes), and JARVIS *proactively* preps things
  when it's "about that time" — with a **PREP IT** button.
- 🎙 **Voice** — "Hey JARVIS" wake word, local Whisper STT, calm British
  voice (Piper TTS). All offline, all on your machine.
- 🧠 **Brain** — plug in any LLM (OpenAI-compatible or local Ollama) for full
  conversation, or run the built-in offline rule brain with zero setup.
- 🖥 **Fleet control** — one JARVIS over all your devices: laptops, servers,
  phones. Each device runs a tiny *agent* that connects to the core; you can
  ask "status of all devices", "run docker ps on web-01", "run disk on api-02".
- 👀 **Awareness** — on desktops the agent tracks your foreground app and
  session lengths. JARVIS builds "you've been in VS Code 93 min today" context
  into briefings and learns "you code at 9am" habits.
- 📝 **Memory** — "remember I prefer dark mode" → stored forever in local
  SQLite, recalled automatically. Nothing leaves your laptop.
- 🧬 **Auto-learns without asking** — "I love coffee", "I'm allergic to
  shellfish", "I usually open VS Code at 9" are picked up from ordinary
  conversation — the last one becomes a scheduled prep. Repeated
  open-A-then-B patterns are *noticed* and offered: "save this as a routine?"
- 👁 **Figurative, made real** — "I'll keep an eye on it" → every device is
  watched, with a red **alert** when one drops and an announcement when it
  returns. "I'll take care of it" → a background routine that runs itself and
  reports back step by step. "Quiet" → it genuinely stops all proactivity.
- 📅 **Calendar autopilot** — "i have a meeting with Priya at 4 pm" lands on
  your calendar automatically; `lead_minutes` before any meeting JARVIS fires
  your `meeting` routine (or offers it); briefings lead with what's next.
  Import your real calendar with **"import my calendar from work.ics"**
  (Google/Outlook/Apple all export .ics).
- 📸 **Screen capture** — "screenshot my-mac" grabs the actual screen on any
  agent (macOS/Linux/Windows) and pops it up in the UI — "what's on my screen?"
  is no longer a figure of speech.
- 🌐 **Real web access** — paste any URL and JARVIS reads it ("read
  https://…", or just drop the link in chat): title + readable text, no
  headless browser, no keys.
- 📰 **News** — "what's the news", "tech news", "news about markets": DuckDuckGo
  News first, then RSS fallbacks (BBC / Al Jazeera / NYT), cached 15 min; the
  top headline rides along in every brief.
- 💱 **Forex & markets** — "how much is 100 usd in zar", "eurusd", "bitcoin
  price", "markets": live pairs (Stooq intraday), ECB/open.er-api daily
  fallback, crypto via CoinGecko, indices & gold; the Command Center shows a
  live board. **Rate watchers**: "watch usdzar above 19" arms a real alert —
  the moment the pair crosses, you get a red banner and a spoken flag.
  No API keys anywhere; offline + `--demo` uses a clearly labelled sim feed.
- 🕰 **World clock** — "time in tokyo" (session planning across zones).
- 🧠 **LLM-ready by construction** — plug any OpenAI-compatible endpoint into
  `llm:` and it inherits *everything*: an auto-generated capability manifest
  (every tool, grouped: laptop / memory / calendar / markets / home / music /
  scenes / fleet), persistent conversation memory across restarts, 6-round
  agentic tool chaining, and a vision path (`analyze_screen`, "what am I
  looking at?") that sends the captured PNG to the model.
- 🏠 **Smart home** — Home Assistant REST bridge when configured
  (`home_assistant: url + token`), labelled sim house otherwise: "lights on
  kitchen", "dim desk to 40", "tv off", "set temperature to 22".
- 🎵 **Music** — real MPRIS control via `playerctl` (Spotify/VLC/browser),
  `play <query>` opens a Spotify search when nothing is playing; sim player
  offline. "pause", "next track", "what's playing".
- 🎬 **Scenes** — "good morning", "movie night", "good night": whole routines
  of home+music+brief actions run in the background with step reports.
  Scene buttons appear in the Command Center.
- 📱 **Phone superpowers** — the Android agent (Termux) can really send SMS
  (`termux-sms-send`) and place calls (`termux-telephony-call`) when started
  with `--allow sms --allow call`: "text Sam I'm running late", "call mom".
- ✅ **Tasks & reminders** — "remind me to call the bank in 20 minutes / at 5pm /
  tomorrow at 9 / every day at 8:30", "add task email Sam", "my tasks",
  "done 3". Timed reminders fire through the announce + alert channel;
  repeats reschedule themselves; the Tasks panel has DONE buttons.
- 🌐 **Web watchers** — "watch <url> for <keyword> every 30 seconds" or
  "monitor <url>": JARVIS keeps re-reading the page and alerts on content
  change or first keyword appearance (with a fresh-text snippet), tracks
  unreachable pages honestly, and lists/stops them via "my web watches" /
  "stop watching <host>". `--demo` serves `/demo/page`, a local page that
  flips every 2 minutes, so watchers are testable with no internet.
  **Honest limits:** text-level fetching only — no JS rendering, no logins,
  no form filling, no browser automation. For that you'd bolt on Playwright;
  everything up to it is real here.
- 🪞 **SELF — it is its own study object.** Every turn is journaled; your
  thanks and corrections become reward signals; a phrase JARVIS misunderstood
  twice and you rephrased becomes a **permanent self-taught rule** (announced
  when learned, reversible with `unlearn …`); a request you repeat at the same
  hour across days becomes a **self-created scheduled routine**; suggestion
  aggressiveness is tuned from your acceptance rate; flaky tools get marked
  degraded and retried later. Ask **"why did you say that?"** for the real
  decision trace, or **"self check"** for its weekly self-report. The Self
  panel in the UI shows turns, landed-%, praise/corrections and every rule it
  taught itself.
- ✨ **Hologram UI** — animated ring + **Command Center** panel: fleet health,
  today's activity, preps, memories, habits.

- 📤 **Reach you anywhere — push, digest, browser** — Telegram and email
  bridges: `send <message> to telegram`, `push status`; with no credentials
  configured every message is logged to an honest outbox (nothing is ever
  pretended-sent). Alert routing respects `push.mode` (alerts/all/off). At
  night (`digest.quiet_hours`, default 23→7) proactive alerts are stashed
  into a **digest** instead of waking the UI — `what did I miss` reads them
  out and marks them delivered; the morning brief mentions what's waiting.
  And `render <url> in browser` drives a real headless Chromium (Playwright:
  JS executed, screenshot saved to `data/shots/`) when installed — otherwise
  it degrades to a plain-text read, always labelled "JS not rendered", never
  faking a browser.

- 🏠 **Integrated, not an app** — one command weaves JARVIS into the machine:
  `python3 -m jarvis.cli install` writes a real **systemd user service**
  (Linux), **launchd plist** (macOS), autostart `.desktop`, Windows startup
  `.bat`, or a **Termux boot script** (phone agent survives reboots) — plus a
  `jarvis` command in `~/.local/bin`, so from any terminal, any time:
  `jarvis brief me`, `jarvis remind me to stretch in 20 minutes`. The core
  runs `--headless` (no browser tab hostage-taking); red alerts also fire
  `notify-send`/`osascript` desktop notifications when the OS has them
  (`integration.notify: auto|on|off`). Uninstall is complete and marker-scoped
  — it removes exactly what it added. If the machine refuses a service
  (e.g. no user bus in a container), the report says *"failed: ..."* —
  never a silent checkbox.
## Quickstart (2 minutes, zero API keys)

```bash
cd JARVIS-PERSONAL
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml      # set your name + city + fleet token
python run.py
```

Open http://127.0.0.1:8595 and try:

```
brief me
status of all devices
open spotify          ← say it twice, then check the LEARNED panel
good morning          ← scene: brief + kitchen lights + focus music
lights off all        ← smart home (Home Assistant, or labelled sim)
play focus music      ← real MPRIS control when a player is running
text sam: on my way   ← real SMS from your Termux phone agent
what am i looking at  ← screen capture + vision model when connected
remind me to stretch in 20 minutes
my tasks              ← open list; "done 3" ticks one off
watch <url> for launch every 30 seconds   ← page-change/keyword alerts
what did I miss         ← overnight digest (alerts stashed while you slept)
send dinner plans to telegram  ← real when configured, honest outbox if not
render <url> in browser        ← real Chromium when Playwright installed
jarvis brief me         ← the SAME brain from any shell (after `jarvis install`)
python3 -m jarvis.cli install --dry   ← see exactly what would be written
i love coffee         ← auto-learned, no "remember" needed
i have a meeting with Priya at 4 pm   ← lands on the calendar, autoprepped
meetings today
screenshot web-01     ← its actual screen, popped up in the UI
what's the news       ← headlines; top one joins every brief
https://example.com   ← paste a link and I read it for you
how much is 100 usd in zar
watch usdzar above 19 ← real alert the moment it crosses
markets               ← pairs, crypto, indices board
take care of work     ← background routine, reports back
watch web-01          ← I'll alert you if it drops
quiet for 30 minutes
23*7-4
```

`python run.py --demo` also spawns two simulated devices (a Linux server and a
phone) so you can feel the fleet experience with no extra hardware.

## Connect your real devices (the fleet)

Every machine runs the same lightweight agent — it only ever makes an
*outbound* connection to the core (no open ports, no firewall changes):

```bash
# a server (health + allowed shell commands):
pip install psutil websockets
python -m jarvis.fleet.agent --name web-01 --url ws://192.168.1.10:8595 \
    --token <your fleet token> --allow shell:docker --allow shell:git

# an Android phone in Termux (SMS + calls + notifications, when YOU allow it):
#   pkg install python termux-api
python -m jarvis.fleet.agent --name phone --url ws://192.168.1.10:8595 \
    --token <your fleet token> --allow sms --allow call

# your laptop (adds foreground-app awareness):
python -m jarvis.fleet.agent --name my-mac --url ws://192.168.1.10:8595 \
    --token <token> --activity --allow open_app

# an Android phone via Termux:
pkg install python && pip install psutil websockets
python -m jarvis.fleet.agent --name phone --url ws://<core-lan-ip>:8595 --token <token>
```

Once connected, ask JARVIS anything:

```
status of all devices
status of web-01
run docker ps on web-01
run disk on api-02
run telemetry on phone
```

### Security model

- **Token auth** — agents must present the shared `fleet.token`; the core
  rejects anything else (close code 4401).
- **Allowlist actions** — agents only expose `telemetry/disk/uptime/processes/
  activity/notify/open_app` by default. Shell commands run *only* if their
  prefix is explicitly allowlisted (`--allow shell:docker`). "run rm -rf / on
  web-01" gets refused by the agent itself.
- **LAN-only by default** — keep the core on `127.0.0.1` or your LAN. Don't
  expose port 8595 to the internet without a VPN/Tailscale.

## How the learning & prep works

1. **Every request is an event** — tool used, what for, hour, weekday.
2. **Activity is an event too** — finished app sessions (≥60 s) feed the same
   engine: "active in VS Code at 09:00 Wed".
3. **Habits** = (what, weekday, hour) buckets, weighted by recency — a habit
   from 3 weeks ago counts half as much as today's.
4. **Prep engine** — `lead_minutes` before a learned time (or a scheduled
   routine), JARVIS surfaces an amber banner: *"About your usual time to work
   in VS Code (~09:00)"* with **PREP IT**. Snoozed preps stay quiet 30 min.
5. **Routines** — named command lists in `config.yaml` or learned in the
   database, scheduled (`morning` at 08:30 weekdays) or on-demand (`prep work`
   → opens your workspace). Routines can use ANY capability, including fleet
   commands. `prep.mode: auto` fires them itself; `ask` asks first.
6. **Watchers** — `fleet.auto_watch: true` keeps an eye on every device:
   red alert banner when one drops, announcement when it's back (and it says
   *how long* it was out).
7. **Take care of X** — runs routine X in the background and reports each
   step over the wire, finishing with a summary.
8. **Calendar** — events live in the same local SQLite. Meetings mentioned in
   ordinary conversation are added automatically (past times roll to
   tomorrow). `calendar.lead_minutes` before an event, the `meeting` routine
   runs (auto mode) or is offered (ask mode); ~2 min before, a heads-up.
   ICS import covers real calendars.
9. **Screen capture** — agents expose a `screenshot` action
   (`screencapture`/`scrot`/`gnome-screenshot`/Pillow by platform). The core
   stores it under `data/screenshots/` and shows it in a UI overlay.
10. **Briefings** — "brief me" composes: today's activity, the calendar
    (next event + later today), fleet health, upcoming habits, routines,
    remembered facts. The first "hi" of the day includes a compact brief.

## Full voice mode ("Hey JARVIS")

```bash
pip install -r requirements-voice.txt
python -m piper.download_voices en_GB-alan-medium   # the British voice
```

Put the model in `data/voices/`, set `voice.enabled: true` in `config.yaml`,
`python run.py`. Say **"Hey JARVIS"** → speak → local transcription → spoken
answer. The browser **MIC** button also works as push-to-talk.
No Piper? Auto-fallback to espeak-ng or pyttsx3.

## Make it conversational (the LLM brain)

*Zero-cost route:* a Token Harbor key (free tier on `deepseek-v4.1-flash:free`)
in `config.yaml` → `llm.provider: openai`, `openai_base_url:
https://tokenharbor.ai/v1` — inline `openai_api_key` or, safer, an
`OPENAI_API_KEY` env var (env wins). Without network or with a dead endpoint
every turn falls back to the rule brain in ~0 ms — the log says so, and you
never wait on a dead socket.


The rule brain covers the classics; an LLM makes it conversational and lets it
decide which tool to use on its own (function calling over ALL tools —
including fleet + routines).

```bash
# option A — OpenAI (or any OpenAI-compatible API):
export OPENAI_API_KEY=sk-...

# option B — 100% local via Ollama:
ollama pull llama3.2        # config: llm.provider: ollama
```

## Architecture

```
run.py                      # launcher: config + core + optional voice + demo fleet
jarvis/
├── main.py                 # Jarvis orchestrator: state machine, briefings,
│                           #   proactive preps, thread-safe UI fan-out
├── server.py               # FastAPI: UI, /ws, /api/*, /fleet/ws (agent endpoint)
├── config.py               # config.yaml + defaults
├── brain/
│   ├── rules.py            # offline rule brain (no keys needed)
│   ├── llm.py              # LLM brain via any OpenAI-compatible API
│   ├── memory.py           # SQLite: facts, events, habits, activity,
│   │                       #   devices, routines, watchers, calendar
│   ├── ics.py              # dependency-free ICS import
│   ├── fx.py               # markets engine: stooq/ECB/er-api/coingecko + sim
│   ├── home.py             # smart-home bridge: Home Assistant REST or sim
│   ├── music.py            # music bridge: playerctl (MPRIS) or sim
│   └── prep.py             # PREP ENGINE: routines + habit-based getting-ready
├── learner/patterns.py     # usage log → proactive suggestions
├── fleet/
│   ├── hub.py              # core-side device registry + command dispatch
│   ├── agent.py            # THE AGENT: run on any laptop/server/phone
│   └── sim.py              # simulated devices for --demo
├── tools/                  # the "hands": open_app, web_search, weather,
│   │                       #   find_files, set_volume, system_stats, math,
│   │                       #   remember_fact, recall_facts, fleet_status,
│   │                       #   device_info, run_remote, fire_routine,
│   │                       #   calendar_today, calendar_add, calendar_cancel,
│   │                       #   market_snapshot, convert_currency, set_rate_alert,
│   │                       #   home_light, home_tv, home_climate, home_state,
│   │                       #   music_control, run_scene, send_sms, place_call,
│   │                       #   analyze_screen, read_url, news, world_time
├── voice/                  # lazy: openWakeWord wake, Whisper STT, Piper TTS
└── ui/                     # hologram + Command Center (fleet/activity/prep)
data/memory.db              # your memories (created at runtime, git-ignored)
```

## Privacy

Everything runs on your machines: wake word, STT, TTS, memory, habits,
telemetry. Network calls are only the ones you asked for (search, weather)
plus your optional LLM API. No telemetry, no cloud account. The agent only
ever connects *out* to your core.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pip install piper-tts` fails | try `pip install piper-tts==1.2.0`, or pyttsx3/espeak |
| Wake word never fires | speak ~30 cm from mic; lower threshold in `voice/wake.py` |
| Device won't connect | check `fleet.token` matches, core reachable at `--url` |
| "shell command not in allowlist" | add `--allow shell:<prefix>` to that agent |
| Port busy | `python run.py --port 8600` |
| Windows volume | `pip install pycaw comtypes` |

## Roadmap ideas

Multi-user "who's asking" detection · a global push-to-talk hotkey daemon
over the CLI · per-weekday habit reports · fill in `push.telegram` /
`push.mail` credentials to make sends leave the machine ·
`pip install playwright && playwright install chromium` to upgrade web reads
into real browser renders · browser-automation tools for logins/forms via the
same Playwright engine.
