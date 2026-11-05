# The first real run

This is Daniel's runbook for the company's first real sessions: steps S3 to S7 of `docs/design.md`, in order, with the exact commands.
Each command is run in this order by a test, on a stub session (`tests/test_first_run.py`), which also checks each quoted line under "You should see".
The stub is not Claude Code, so the sentences on what a real session does are what the docs say, until this run shows them.

To stop everything at any moment, go to [Stop everything](#stop-everything).

## What it costs

From the team's measured records, a session should carry about $2.12 of list-price weight at the median, and $7.69 at the 90th percentile.
List-price weight is what apportions the week between the company and everyone else, and it is not a bill: what you pay stays the plan's price.
The probe and the kill test run on the cheapest model and should come in well under the median.
The command prints each session's weight, and `company treasurer share` shows the company's part of the week afterwards.
With extra usage off, a session past the account's limits stops, and nothing is billed.

## Which commands are yours alone

No worker of the agent team may start a company session, so only you run these, against your real home:

- `uv tool install`, `company settings init`, `company account checked`, `company reading record`, and `company go real-sessions`
- `company session probe`, `company session probe --kill-test`, `company session start`, and `company audit`
- `company paper check`
- `company treasurer check`, `company treasurer charge`, `company promise kept`, `company finding confirm`, and `company cell resume`
- `company kill` and `company resume`

A worker reads what these leave behind, read-only, and never the key.
The one command here that a worker runs on your real home is `company session scan-reading <run>`, which reads that run's saved output and nothing else.

## S3: the paper account's key

Create the free paper-trading account at Alpaca, whose paper host is `paper-api.alpaca.markets`.
If Alpaca refuses your region, stop here and say so, since a different free paper source would change only the paper module.

Make the key's file, with nothing in it yet, so that it is never readable by anyone else:

```sh
mkdir -p ~/.config/agent-company
```

You should see nothing.

```sh
install -m 600 /dev/null ~/.config/agent-company/paper.key
```

You should see nothing.

Open that file in your editor, and save the paper key id on its first line and the secret on its second.
Never put them on a command line, where your shell's history would keep them.

A pull of the kill switch moves this file aside, so that nothing can use it, by the `outside_accounts` entry `{"name": "paper", "rotation": "move-key", "key_file": "paper.key"}`.
`company settings init` writes that entry by default, so you have no step for it, and `company preflight` says if it has gone.

## S4: the command and your settings

Install the merged code from a checkout of this repository at the merged `dev`, in that directory:

```sh
uv tool install --force --reinstall --python 3.13 .
```

You should see `Installed 1 executable: company`.

`company` must then be on your `PATH`, and uv's own warning says how if it is not.
A session's sandbox also needs `bwrap` and `socat` in `/usr/local/bin`, `/usr/bin` or `/bin`, so install the `bubblewrap` and `socat` packages if `company preflight` asks for them.

Write your settings, each value yours.
The share is the 25% you decided, and the floor's recommended 60% is still open in the design.
These three are suggestions: a reading's age of 120 minutes, a session's limit of 60 minutes, and a weight limit of 20, which sits well above the 90th percentile above.

```sh
company settings init --company-share 0.25 --team-floor 60 --monthly-price <monthly price> --plan-name <plan> --reading-max-age-minutes 120 --session-max-minutes 60 --session-max-weight 20
```

You should see `Recorded event`.

The kill switch's self-test runs a whole pull in a temporary home of its own, on stubs, and touches nothing of yours:

```sh
company kill --self-test
```

You should see `passed: the session and its child stopped, with nothing left running`.

## S5: what no code can see

Do this before each go.

On the account page, check that extra usage is off, since no code can see or set it.
Then read these three, each of which can move, against what `docs/design.md` cites under "Dependencies to re-check":

1. **`claude -p` on plan limits.**
   The help article ["Use the Claude Agent SDK with your Claude plan"](https://support.claude.com/articles/15036540) should still say that `claude -p` draws from your subscription limits when you are signed in with your plan.
2. **`--bare` becoming the default.**
   The [headless docs](https://code.claude.com/docs/en/headless) said on 2026-11-04 that it "will become the default for `-p` in a future release", and that bare mode does not use your subscription login.
   If that release has come, every session fails at sign-in, which uses no model, and the launcher needs a change first.
3. **The terms.**
   Read the [legal page](https://code.claude.com/docs/en/legal-and-compliance) and the [Consumer Terms](https://www.anthropic.com/legal/consumer-terms), section 3, item 7, for any change from what the design quotes.
   You have accepted the "ordinary, individual usage" wording as your risk, and a change is yours to weigh again.

If any has moved, stop and say so.
If all three stand, and extra usage is off, say so:

```sh
company account checked
```

You should see `you checked that extra usage is off`.

## S6: a reading of the account

Read the week's use and its reset time from the usage page, and record them, with the reset time in UTC or with its zone:

```sh
company reading record --window seven_day --used-percent <percent> --resets-at <reset time>
```

You should see `seven_day`.

If the page also shows a five-hour window, record that the same way, since a reading that is there is enforced:

```sh
company reading record --window five_hour --used-percent <percent> --resets-at <reset time>
```

You should see `five_hour`.

A launch refuses a reading older than your `--reading-max-age-minutes`, and names this command, so you may need it again later in the run.

Optionally, to keep readings without your hand, add this to your own interactive session's `~/.claude/settings.json`, and reply once in that session:

```json
{"statusLine": {"type": "command", "command": "company reading statusline"}}
```

Now ask what is left:

```sh
company preflight
```

You should see `S3 passed`, `S4 passed`, `S5 passed`, `S6 passed` and `Preflight is open: S7.`

Any other step that is open names the command that closes it.
The preflight never opens the key's file, and adds nothing to the ledger.

## S7: gate A

The coordinator asks for your go here, stating what it covers: the probe, the kill test, one quant cell session and one Auditor session, which are four launches, and up to two re-runs after fixes.
Your word grants exactly the number you give it, and the launcher refuses past it:

```sh
company go real-sessions --message <Discord id> --sessions <n>
```

You should see `a go for`.

```sh
company preflight
```

You should see `Preflight passes: every step from S3 to S7 is done.`

One read-only call to the paper host shows the account, and never the key:

```sh
company paper check
```

You should see `PAPER, no real money`.

### The probe

This is a cheap real session that tries each forbidden action.
It writes and reads only decoys, each named `probe-decoy-` and holding no secret: in your config directory, in the company home and its `market-data/broker`, in your home directory, and in a workspace beside its own.
While it runs, a decoy `CLAUDE.md` sits in `workspaces/` in the company home, and a decoy rule sits in `~/.claude/rules`, where another session you start in that minute could load it: it holds a marker, and asks nothing of whoever reads it.
It removes them all at its end; if it is killed outright, any that stay can be deleted by hand.

```sh
company session probe
```

You should see `The check passed` and `the decoy CLAUDE.md above its workspace: absent`.

Each forbidden action is listed as `refused`, `succeeded` or `not-reported`, and each of these is listed as `present` or `absent`, and no more than that: the decoy `CLAUDE.md` above its workspace, the decoy rule, and your global instructions, `~/.claude/CLAUDE.md`.
Reads, writes and markers are judged from what the code can see, whatever the session says; the network is judged only from what the session says, since it leaves nothing to see.
The result is saved as `probe-report.json` in the run's directory, `runs/<run>/` in the company home, and its last line names the file.

What each ending means:

- **`The check FAILED`, with a forbidden action `succeeded`.**
  The kill switch has been pulled for you: every session has stopped, the schedule is off, and the key has moved aside.
  Regenerate the key at Alpaca once this is fixed, and start nothing further.
- **`The check FAILED`, with something `present`.**
  A session loads what it must not.
  No switch is pulled, since nothing was reached, but start nothing further until it is fixed.
- **`The check proved nothing`.**
  Nothing is known either way, and it says why.
  A re-run takes another launch of your word.

**Sign-in under `--restricted` is unproven until this probe.**
The docs say bare mode drops the subscription sign-in, and name no such limit for `--restricted`, but they do not say in so many words that the sign-in survives it.
A failed sign-in looks like this: the session exits at once with a non-zero exit, the weight reads `0.000000`, no action is reported, and the command says `The check proved nothing: the session exited`.
The session's own words, such as being not logged in, are in `output.jsonl` and `stderr.txt` in the run's directory.
It uses no model, and it spends one launch of your word.
Say so and stop: the fix is in the launcher, and it never falls back to loading your user settings or to any key.

Whether a real session's output reports the account's use is check C2, which this answers from what the probe saved; a worker may run it too:

```sh
company session scan-reading <run>
```

You should see `The saved output of run`.

### The kill test

This starts a probe that waits, stops it with the kill switch's stop step, shows that nothing is left running, and resumes.
It leaves your timers and key alone, and it is refused with the schedule on or another session running.

```sh
company session probe --kill-test
```

You should see `Left running after the stop: nothing.`, `The test passed.` and `Launches may start again.`

Its report, `kill-test.json` in the run's directory, is what answers check C1 for a real session, which ticket 14 reads.
If anything was left running, the command names it and ends it, says `The test FAILED.`, and leaves every launch refused: start nothing further until it is fixed.

### The quant cell and the Auditor

```sh
company session start cell --bet quant --prompt "Research one trading strategy to its verdict, on the broker's bars."
```

You should see `ended: exit 0`.

The Auditor reads that session's transcript on a different model, and is refused if the models are of one family:

```sh
company audit <cell run>
```

You should see `Findings from this audit:`.

## After a session

These are yours by hand until the schedule is on.
Each is safe to run again.

```sh
company treasurer charge
```

You should see `Charged:`.

```sh
company digest
```

You should see `## Bar`.

The digest lists each finding and each open promise, with the event number these commands take.
Only you can say a cell's promise was kept, and with no such word at the first check after its day ends, it is broken:

```sh
company promise kept <promise>
```

You should see `was kept on`.

```sh
company treasurer check
```

You should see `kept.`

A finding that code could not check waits for your word, which pauses its cell:

```sh
company finding confirm <finding>
```

You should see `is confirmed`.

Only you lift that pause:

```sh
company cell resume --bet quant
```

You should see `may launch again`.

## Stop everything

Ctrl-C at a running session stops that session's process group.
This stops every company session's process group, turns off the schedule, moves each outside account's key aside, and refuses every launch until you say otherwise:

```sh
company kill --reason "<why>"
```

You should see `The kill switch is pulled` and `Every launch is refused until`.

Regenerate the paper key at Alpaca and save it again as in S3 before the paper account is next needed, since the moved one stays moved.
Only this undoes the pull, and it leaves the schedule off:

```sh
company resume
```

You should see `Resumed:`.
