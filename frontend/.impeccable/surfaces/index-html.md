---
version: 1
slug: "index-html"
primary_target: "index.html"
related_targets: ["main.js","styles.css"]
---

# Landing + studio entry

Scope: the Nothingburger landing (hero, how it works, step inside) and the hand-off into the studio. Mode: Persuade for the landing; the studio stays Operate (unchanged UI, now opening inside JRR Hall).
Audience: homeowners curious whether a robot could do their chores. Action: open the studio and describe a job.
Proof on hand: the real JRR Hall Matterport tour; Vexcel's real footprints and roof heights for the campus.
Constraints: plain HTML/CSS/JS, Three.js 0.160 from CDN; incumbent world (paper + ink grid + gold, Schibsted Grotesk / Geist) is kept; the code-drawn sample apartment stays as a studio space.
Build path: code-led (no image generation on this machine).

## Direction contract
THESIS: the landing is a site plan you can walk into. The category hero (product render or stock photo beside a headline) is refused: the page opens on the real building the studio takes you inside, drawn from survey data.
OWN-WORLD: incumbent paper (#F4EFE7) with the ink drafting grid; JRR Hall as a solid paper-white massing model with gold (#C99A2E) roof edges and a gold entrance mark; neighbouring buildings as thin ink line-work extrusions; a north arrow and scale bar in ink; Schibsted Grotesk 900 display, Geist body.
STORY: the visitor sees a real building, learns it is where their robot gets designed, reads four steps while circling it, then is carried through the front door into the actual hall, where the studio waits.
FIRST VIEWPORT: JRR Hall at three-quarter aerial view filling the right two-thirds, campus line-work fading to the grid at the edges; "Nothingburger" with "automate your life" beneath, bottom-left at incumbent scale; primary action "Open the studio" under the title; a small ink site caption naming the building.
FORM: brief-pinned (extension of the incumbent world, no concept roll); seed: none (unavailable)
SIGNATURE INTERACTION: scroll drives one continuous camera move: a quarter-to-full orbit around the building through the four steps, then a descent to the entrance and a cross-fade into the live Matterport tour.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
