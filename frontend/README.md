# Nothingburger front-end

The landing page and studio for Nothingburger. The landing opens on a 3D site model of Princeton's Julis Romo Rabinowitz (JRR) Hall on the drafting grid; scrolling circles the building, then walks through its front door into the studio, which opens inside the hall's Matterport tour. The studio plans a job with the Pathfinder backend and can preview it with the robot in a sample apartment.

Plain HTML, CSS and JavaScript with no build step. Three.js 0.160.0 loads from jsDelivr through an import map in `index.html`.

## Run it

Browsers block ES modules opened straight from disk, so serve the folder:

```
cd frontend
python3 -m http.server 8000
```

Then open http://localhost:8000 (use `localhost`, not `127.0.0.1`: the Matterport Showcase SDK key only accepts `localhost`). Add `#studio` to the URL to jump straight into the studio.

For the real design workflow (outline, demonstration, then the design and pathing pipeline), also start `uv run --env-file .env python -m agent.design_flow.serve` from the repo root (port 8020; `?agent=http://host:port` overrides it). With it running, **Design robot** in a scan space runs that workflow and ends in **Open Robot Design**; without it the panel uses the stand-in planner below.

For the full flow, also start the Pathfinder backend from the repo (CORS is open, so the two ports talk):

```
cd robots-repo/world/pathfinder/backend
uv run python -m uvicorn server.app:app --host 0.0.0.0 --port 8004
```

Without the backend the studio still works: it shows the bundled list of spaces, plans with an offline copy of the stand-in planner, and turns off filming and parts search. The dot next to the space name shows which mode you're in.

URL options:

| Option | Does |
| :-- | :-- |
| `?api=http://host:port` | Use a backend somewhere other than `http://localhost:8004` |
| `?space=la-mirada` | Open the studio in that space (any id from `/worlds`, or `sample-apartment`) |

## The studio

The studio opens in a Matterport scan from the backend's `GET /worlds` (the list in `robots-repo/web/worlds.json`). The top-left bar picks the space:

- **Matterport scans** show full page as the public Matterport tour. On localhost, when the backend's `GET /web-config` returns a Showcase SDK key, Walk, Dollhouse and Floor plan buttons appear. The key stays in the backend's `.env` and is fetched at runtime.
- **Outside** shows the Vexcel aerial model when the backend has that space's scene package.
- **Outdoor lots (Vexcel aerial)** have no tour: a space with `aerial` (a picture in `assets/aerial/`) and no `matterport` opens on its Vexcel aerial photo, with the ground the robot may use outlined in white and its dock as an orange dot. Its own `jobs` are the suggestions under the prompt. Five are listed: `lawn-palmetto`, `trash-palmetto`, `pooldeck-lakes`, `parcel-eastland` and `lawn-sanpedro`; open one with `?space=lawn-palmetto#studio`. Mowing needs no demonstration, so **Mow the lawn** goes straight to the robot (about 10 s); the other jobs ask the headset first, like any skill not yet learned. The pictures and world files come from `python world/scenarios/tools/aerial_worlds.py` (see `web/README.md`, "Outdoor runs on Vexcel aerial photos").
- **Sample apartment** is the apartment drawn in code, where you drive the robot yourself.
- **i** shows notes about the space and the backend status.

Type a job (or tap a suggestion) and press **Design robot**. The plan panel follows the same steps as `robots-repo/web/`:

| Step | What it does | Backend calls |
| :-- | :-- | :-- |
| 1 The job | The prompt bar | |
| 2 The plan | Steps from the planner | `POST /plan` |
| 3 Show it once | Ask the headset to film each demonstration, then read it back; shows glove status | `POST /demos/request`, `GET /demos/{id}/read`, `POST /demos/stop`, `GET /gloves` |
| 4 The robot | The build agent's pick per slot when a plan carries `design` (the `RobotDesign` shape in `agent/design_flow/schemas.py`); until then, the parts it chooses between | |
| 5 Watch it work | Acts the job out in the sample apartment when it has a matching chore | |
| 6 Parts that fit | For "replace" jobs: search the shops for parts that fit an opening | `POST /parts/search`, `GET /parts/jobs/{id}` |

Close the panel with ×; the dark **Your plan** chip brings it back.

## Files

| File | What's in it |
| :-- | :-- |
| `index.html` | Markup: top bar, hero, "How it works", the scan view, and the studio UI (space bar, prompt bar, area card, plan panel) |
| `styles.css` | All styles. Colour and font tokens are at the top in `:root` |
| `main.js` | The page shell, the studio and the sample apartment, as one ES module (sections listed below); on the landing it renders the campus from `campus.js` |
| `campus.js` | The landing's scene: lights, drafting grid, neighbours, and the scroll camera (aerial, orbit, walk-in through the entrance) |
| `jrr-model.js` | JRR Hall: Vexcel footprint and height, the Collegiate Gothic facade, the aerial photo on the roof, limestone quoins and coping, the Gothic portal |
| `facade.js` | One 6 m bay of the facade painted on a canvas: argillite ashlar, limestone courses and surrounds, steel casement windows |
| `site-dressing.js` | The printed aerial ground, trees from the photo's canopy, and Scudder Plaza's reflecting pool |
| `pano-tour.js` | Our own 360 viewer for scans we serve ourselves (JRR Hall, people removed): drag to look, click the floor or W/S to move with a dolly and cross-fade, A/D to turn |
| `tour-glide.js` | Inside a Matterport embed (other scans): the start position and W/A/S/D glide controls |
| `assets/jrr-tour/` | JRR Hall's 66 panoramas with people removed, and the scan-point graph (`README.md` there says how they were made) |
| `assets/jrr-site.json` | Vexcel footprints and roof heights, roof-photo bounds and tree positions around JRR Hall, in metres around its centre |
| `assets/jrr-roof.jpg`, `assets/site-ground.jpg` | Vexcel aerial photo: JRR Hall's roof, and the 240 m square printed ink-on-paper (origin embedded in each file) |
| `backend.js` | Calls to the backend, plus the offline copies: worlds list, stand-in planner, parts catalog, job suggestions |
| `space.js` | The space picker, the Matterport tour, the Showcase SDK view buttons and the outside view |
| `flow.js` | The plan panel: plan, demonstrations, robot, watch, parts |

`main.js`, top to bottom:

1. **Task catalogue**: the apartment's task areas, tasks and measurements, and keyword matching for the "watch it work" preview
2. **Page shell**: studio enter and exit, scroll-to-enter, prompt bar and suggestions, area card
3. **Scene**: renderer, lighting, blueprint grid, and the apartment (shell, kitchen, dining, bathroom, living room, desk). Static furniture is merged into a few draw calls at the end
4. **Robot**: the humanoid on tracks, arm IK, occupancy grid and A* path planning, gold ribbon trails
5. **Chores**: robot stations, chore animations, and the scroll-driven landing tour
6. **Studio**: robot-eye controls, click and double-click handling, camera hand-off between views
7. **Main loop**: pauses while a scan covers the page

## Sample apartment controls

- W / S drive, A / D or the arrow keys turn
- Drag to look around
- Double-click the floor to drive there
- Click a glowing object for its tasks
- Scroll up or press Esc to go back to the landing page (in a scan, use the ← button)

## Keep in step with the repo

These are copies, so change them together with the originals:

| Here | Original |
| :-- | :-- |
| Bundled worlds in `backend.js` | `robots-repo/web/worlds.json` |
| `standInPlan` in `backend.js` | `make_plan` and `_JOBS` in `world/pathfinder/backend/server/flow.py` |
| `CATALOG` in `backend.js` | `robots-repo/agent/design_flow/catalog.py` |
| `TASKS` in `backend.js` | `TASKS` in `robots-repo/web/app.js` |

## Notes

- The planner behind `POST /plan` is still the backend's stand-in lookup table, and the build agent's design isn't served over HTTP yet, so step 4 shows the parts catalogue.
- The "Demo clip" upload isn't processed.
- The sample apartment's sizes are real-world metres.
- Rendering adapts to the device: shadows are drawn once, the pixel ratio drops automatically if the frame rate falls below about 50 fps, and the 3D loop rests while a scan covers the page.

## The landing's site model

`assets/jrr-site.json` comes from the Vexcel API (collection `us-pa-philadelphia-2026`): every building footprint in a 240 m square around 40.34912, -74.65559, with Vexcel's measured roof heights (JRR Hall: 16.57 m). Buildings without a measured height are drawn 9 m tall and marked `assumed`. JRR Hall is the footprint picked by eye against the aerial photo. The entrance the camera walks through is the facade facing the paved plaza west-south-west of the building, read off the photo rather than surveyed.

The building is drawn to be recognisable: JRR Hall is Charles Klauder's 1929 Frick Chemistry Laboratory, so the walls carry its Collegiate Gothic elevation (purple-grey argillite, Indiana limestone courses, quoins and window surrounds, steel casements; `facade.js` is a stylised bay, not a survey of each window). The roof is the aerial photo itself. Trees are placed where the photo shows canopy (`trees` in the site file); the reflecting pool's corners are read off the photo.

The inside is the CoStar team's Matterport scan of JRR Hall (`2K7G7cdukZV`), shown in our own viewer from 66 panoramas with every detected person removed (`assets/jrr-tour/README.md` has the method and its limits). It opens at the scan point just inside the main entrance doors, in the restored Gothic arcade, facing the atrium, and starts loading once the visitor is about halfway down the landing. Other scans (La Mirada) still use the Matterport embed. To go back to the embed for JRR Hall, remove its entry from `LOCAL_TOURS` in `space.js`.
