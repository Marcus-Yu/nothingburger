# Watch a robot do its job in VR (Meta Quest)

A finished run can be watched from inside the scanned room, at full size: you stand about two metres from the
robot and it does the job in front of you. It is the plan played back, not a live simulation.

Not tried in a headset yet (none was connected when this was written, 2026-11-15). The page, the list, the
command and the headset code's arithmetic were checked on a desktop; see "What was checked" at the end.

## One-time headset setup

1. Turn on developer mode: Meta Horizon phone app > Menu > Devices > your headset > Headset settings >
   Developer Mode. The Meta account has to be a developer account (developers.meta.com, create an organisation).
2. Install adb on the laptop: `brew install android-platform-tools`.
3. Plug the headset into the laptop with a USB-C cable that carries data, put it on, and accept
   "Allow USB debugging" (tick "Always allow from this computer").

## The one command

From the repo, on the laptop:

```bash
tools/quest/quest
```

It checks the headset, starts the design workflow server on port 8020 if it is not running, runs
`adb reverse tcp:8020 tcp:8020`, and opens `http://localhost:8020/vr` in the headset's browser.

```bash
tools/quest/quest runs/demos/la-mirada-kitchen-wipe   # open one run straight away
tools/quest/quest --check                             # say what is ready and what is missing; change nothing
```

`adb reverse` makes the headset's `localhost` the laptop. WebXR only runs on a secure origin or on localhost,
so the page has to be opened as `http://localhost:8020/...`, not by the laptop's address on the network.

## What you see

- **The launch page** (`/vr`): the runs that can be played, as large cards: the job, the place, and
  **Room: yes/no** (whether the scanned room's mesh is on the laptop). All of `runs/demos` and `runs/gallery`
  that have a robot export, and the 15 newest from `runs/studio`. Point at a card and pull the trigger.
- **The room** (`/room.html?run=<run>&vr=1`): the room loads behind one large **Enter VR** button. Press it.
- **In VR**: you stand on the floor about two metres from the robot, facing it, and the job starts. A label
  floats over the robot with the step it is on ("t1: wipe (strokes 3–5 of 24)"), the time, and the buttons.

The same page without `&vr=1` is the desktop view: Matterport-style controls along the bottom, and
**Enter VR** in the three-dots menu when the browser has a headset.

## Controls in the headset

| Control | Does |
| :-- | :-- |
| Right trigger | play or pause |
| Left stick | walk (forward, back, sideways), at 1.4 m/s |
| Right stick, left or right | snap-turn, 30° a push |
| Right stick, forward or back | walk |
| A or X | stand by the robot again, facing it |
| B or Y | start the job again |
| Either grip | Follow on or off |
| The headset's menu button | leave VR |

Comfort: nothing turns you except your own snap-turn. With Follow on (it starts on) you are slid along only
when the robot gets more than 3.2 m away or closer than 1.2 m, at no more than 1.2 m/s, with gentle starts and
stops, and never through a wall. The recorded drive is fast (3 m/s), so when the robot gets more than 6.5 m
away, or stops to work somewhere you cannot see it, the view fades to black, puts you beside it, and fades
back (at most once in three seconds). If the sliding bothers you, squeeze a grip to turn
Follow off and use A or X to catch up.

## Troubleshooting

**Blank room: the robot among outlines and boxes, or on nothing.** The page says so in a line at the top:
"No room mesh for <place> on this machine". The room is `world/_scans/<world id>/room.glb`, which is not
committed (it is Matterport's), so a checkout or a machine that never captured it has none.
- Check which server you are looking at. `tools/quest/quest --check` says when the server on port 8020 runs
  from another checkout, and how many runs have their room. That was the cause of "the robot drives in blank
  space": a server started from a checkout with neither `runs/demos` nor the meshes.
- To get the mesh: capture it (`web/README.md`, "The real room as a mesh"), or link another checkout's folder:
  `ln -s /path/to/other/checkout/world/_scans/<world id> world/_scans/<world id>`. Both servers follow the link.
- The outdoor demo runs (`vexcel-*`) have no room and no robot export; they are not in the list.

**"Enter VR" is missing.** The page says why in place of the button.
- "cannot enter VR from this address": the page was opened by the laptop's address. Run `tools/quest/quest`
  again and use `http://localhost:8020/...`.
- "this browser has no VR headset": that browser is not the Quest's (a desktop browser says this).
- The cable was unplugged: `adb reverse` is lost with it. Run `tools/quest/quest` again.

**The list did not load / the page does not open.** The design workflow server is not running, or an older one
is on the port. `tools/quest/quest --check` says which; `tools/quest/quest` starts this checkout's. Its log is
`/tmp/claude-design-workflow.log`.

**The headset is not found.** `adb devices` should list it as `device`. `unauthorized`: accept the prompt in
the headset. Nothing listed: developer mode is off, or the cable only charges.

**Wireless adb (no cable).** With the cable in once:

```bash
adb tcpip 5555
adb connect <the headset's IP address>:5555     # Settings > Wi-Fi > the network, in the headset
```

Unplug, then run `tools/quest/quest`. If both the cable and the wireless connection are listed, pick one with
`ANDROID_SERIAL=<address>:5555 tools/quest/quest`. The laptop and the headset must be on the same network.

**The room page stays empty or unstyled.** The headset needs its own internet connection: the page loads
three.js (cdn.jsdelivr.net) and the launch page its fonts (Google Fonts) from the web, and `adb reverse` only
forwards port 8020.

**It stutters.** A room mesh is 18 to 25 MB of textured triangles. Close other tabs in the headset's browser.

**Matterport's logo shows as the word.** The logo file comes from their SDK bundle, which is not committed:
`python web/fetch_sdk.py` fetches it into `web/_vendor/matterport`.

## Where it lives

| File | Is |
| :-- | :-- |
| `tools/quest/quest` | the command |
| `web/viewer/vr.html` | the launch page |
| `web/viewer/room.html` | the room: desktop view, the missing-mesh fallback, and everything in the headset |
| `agent/design_flow/serve.py` | `/vr`, `/vr/runs`, `/room.html`, the run files and `/scans/<world>/room.glb` |

`python -m web.serve` (port 8010) also serves `room.html`, with `&vr=1`, for any run; it has no launch list.

## What was checked, and what was not

Checked on a desktop (Chrome, no headset): the launch page and its list; the room page for the three demo runs
with the room around the robot; `&vr=1` showing the line that says what is missing; the missing-mesh fallback;
`tools/quest/quest` against a stand-in `adb`; and the headset code's arithmetic with made-up head poses (you
land on the spot facing the robot, a snap-turn pivots on your head, the Follow slide stays under its speed limit
and inside the rooms).

Not checked, because it needs a headset: entering VR at all, the controller buttons and sticks, how the label
reads, the frame rate with a full room mesh, and how the Follow slide and the fades feel.
