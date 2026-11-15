---
name: Nothingburger
description: A site plan you can walk into. Paper, ink drafting grid and gold, around a survey-true model of the building the studio takes you inside.
colors:
  paper: "#F4EFE7"
  ink: "#17140F"
  ink-hover: "#2C2720"
  ink-2: "#5D564C"
  mute: "#A0988C"
  line: "rgba(23,20,15,.11)"
  on-ink: "#FBF8F3"
  field: "#FFFDFA"
  glass: "rgba(249,246,241,.8)"
  gold: "#C99A2E"
  gold-ink: "#8E6A16"
  sub: "#85600F"
  ok: "#3F8058"
  scan: "#3D6AA3"
  tape: "#AE6326"
  error: "#A9432C"
  scene-ink: "#2A231B"
  massing: "#FBF8F2"
typography:
  display:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(48px, 7.6vw, 120px)"
    fontWeight: 900
    lineHeight: 0.84
    letterSpacing: "-0.058em"
  display-sub:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.5em"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.048em"
  headline:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(40px, 4.8vw, 66px)"
    fontWeight: 900
    lineHeight: 0.92
    letterSpacing: "-0.05em"
  title:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 800
    lineHeight: 1.12
    letterSpacing: "-0.025em"
  title-sm:
    fontFamily: "Schibsted Grotesk, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 800
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  button:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1
  label:
    fontFamily: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.14em"
  measure:
    fontFamily: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1
    fontFeature: "tnum"
rounded:
  tag: "6px"
  control: "12px"
  row: "14px"
  field: "18px"
  card: "22px"
  bar: "24px"
  panel: "28px"
  pill: "999px"
spacing:
  tight: "6px"
  gap: "8px"
  inset: "12px"
  card: "18px"
  panel: "clamp(24px, 3.4vw, 42px)"
  gutter: "clamp(16px, 5vw, 72px)"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "13px 22px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-ghost:
    backgroundColor: "rgba(249,246,241,.6)"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "13px 22px"
  button-ghost-hover:
    backgroundColor: "#FFFFFF"
  button-sm:
    rounded: "{rounded.pill}"
    padding: "10px 16px"
  glass-panel:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
  glass-card:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "{spacing.card}"
  prompt-field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "6px 6px 6px 16px"
  list-row:
    backgroundColor: "rgba(255,253,250,.7)"
    textColor: "{colors.ink}"
    rounded: "{rounded.row}"
    padding: "10px 12px"
  list-row-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
  segment-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.pill}"
    padding: "8px 12px"
  site-caption:
    backgroundColor: "rgba(244,239,231,.86)"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  tag:
    backgroundColor: "color-mix(in srgb, var(--c) 6%, transparent)"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "4px 9px"
---

# Design System: Nothingburger

## Overview

**Creative North Star: "The Site Plan You Can Walk Into"**

Nothingburger is drawn, not rendered. Everything sits on warm drafting paper ruled with an ink grid, and the landing opens on a survey-true massing model of JRR Hall, built from Vexcel footprints and roof heights. The hall is solid paper-white with gold coping and a gold-framed, lit entrance. Its neighbours are ghosted ink line-work. A north arrow and a 0–30 m scale bar sit on the ground plane. Scrolling is one continuous camera move: an aerial three-quarter view, an orbit, a descent to eye height at the plaza, and a walk through the door that cross-fades into the live Matterport tour. The studio then opens in that same space.

The interface's panels, cards and bars float over the drawing as frosted glass: warm translucent panels with a white hairline edge and a soft, low, warm shadow, so the model always reads through. The typography gives the drawing its voice. Schibsted Grotesk sets heavy, tightly tracked two-tone titles (ink over deep gold). Geist carries the body text in plain words. Geist Mono handles anything that is a measurement, a step number, a status or a data credit. Gold is scarce and means one of two things: the subject (the hall's roof edge, its door, the bear mark) or a point of attention (area and pin dots, step-number badges, focus, hover, progress).

Density is generous on the landing, where panels are left-docked, at most 620px wide, with long scroll runs between them, and compact in the studio, where glass panels dock to the viewport edges at a 12px inset around a full-bleed scene.

**Key Characteristics:**
- Warm paper (#F4EFE7) with a two-scale ink drafting grid, in both CSS and the 3D ground plane.
- A survey-true massing model as the hero subject, credited in a mono caption.
- In 3D, line weight is carried by opacity, not stroke width.
- Frosted glass over a live scene for every panel, card and bar.
- Two-tone display titles: an ink line, then a deep-gold sub-line.
- Mono for every measured or numbered fact.
- Scroll as a single continuous camera move, ending in a cross-fade into the real interior.

## Colors

A warm, low-chroma paper-and-ink palette with one metallic gold. A small set of evidence colours carries meaning on tags and status dots.

### Primary
- **Bear Gold** (`gold`): the one accent. It appears as the hall's roof coping and door frame in 3D, the gold door mark on the plaza, the area dots, the scroll progress bar, pin pulses, and hover and focus borders on inputs, chips and tasks. It is never text: at 2.25:1 on paper it fails legibility.
- **Gold Ink** (`gold-ink`): gold's legible deep shade. It is used for the focus ring (2px, offset 3px), step numerals, "Plan" task links and category tags.
- **Sub Gold** (`sub`): the colour of every display and headline sub-line ("Automate your life", "Zero manuals.", "JRR Hall."). It holds 4.99:1 on paper.

### Secondary (evidence colours)
- **Scan Blue** (`scan`): this value was measured from the scan. It also marks motion demos.
- **Tape Amber** (`tape`): this value came from a tape check, or a state needs care (offline, squeeze grip, fit not confirmed).
- **Verified Green** (`ok`): live, done or fits. It is used on the backend dot, completed run steps, agent-planned tags and the success toast.
- **Error Brick** (`error`): prompt validation messages only.

### Neutral
- **Drafting Paper** (`paper`): the page, the scene background and fog, the walk-in veil, and the tour backdrop.
- **Drafting Ink** (`ink`): UI text, primary buttons, and selected states (selected area row, selected segment, selected pin, toast).
- **Ink Hover** (`ink-hover`): the hover shade for dark pills and the plan chip.
- **Graphite** (`ink-2`): secondary text (lede, step copy, nav links, notes, hints, caption credit line). It holds 6.32:1.
- **Pencil** (`mute`): inactive dots (the backend status dot when unknown). It is not a text colour.
- **Hairline** (`line`): row dividers, card borders, and the glass panel's outer ring.
- **On-Ink** (`on-ink`): text on ink fills.
- **Field White** (`field`): input wells, task rows, measurement chips and part options.
- **Frost** (`glass`): the fill for every glass panel.
- **Scene Ink** (`scene-ink`): every line drawn inside WebGL (grid, edges, storey bands, windows, north arrow, scale bar and its labels). It is a softer ink than the UI's, and is always used at partial opacity.
- **Massing White** (`massing`): the hall's solid volume, lifted with a 0.22 paper emissive so it stays white under ACES tone mapping.

### Named Rules
**The Gold Is the Subject Rule.** In the scene, gold belongs only to the building you will enter: its coping strip, its door frame and its plaza mark. Neighbours never take gold. In the UI, gold marks points of attention: area and pin dots, the 16% gold badge behind plan-step numerals, and focus, hover and progress states. It is never a solid fill behind text.

**The Two Inks Rule.** UI ink (`ink`) is used opaque, on DOM text and fills. Scene ink (`scene-ink`) is used translucent, on WebGL line-work. Do not swap them.

**The Evidence Colour Rule.** Blue, amber and green say where a fact came from, or what state it is in: scan, tape or caution, verified. They appear only as tag tints (6% fill, 35% border, full-strength text), status dots and short status lines. They are never decoration.

## Typography

**Display Font:** Schibsted Grotesk (with Helvetica Neue, Arial). Loaded at 600–900.
**Body Font:** Geist (with ui-sans-serif, system-ui). Loaded at 400, 500 and 600.
**Label/Mono Font:** Geist Mono (with ui-monospace, SFMono-Regular, Menlo). Loaded at 400 and 500.

**Character:** a heavy, tightly tracked grotesk speaks like a drawing's title block. A plain, friendly sans carries the explanation. A mono acts as the draughtsman's lettering for numbers and credits.

### Hierarchy
- **Display** (Schibsted 900, clamp 62–146px, line-height 0.84, -0.058em): the hero title only. It is always followed by its display sub-line.
- **Display sub** (Schibsted 800, 0.5em of its parent, line-height 0.98, -0.048em, `sub` colour): the second line of every display and headline.
- **Headline** (Schibsted 900, clamp 40–66px, line-height 0.92, -0.05em): section titles on glass panels. The "Step inside" card narrows it to clamp 34–52px.
- **Title** (Schibsted 800, 20px, line-height 1.12, -0.025em): step titles. **Title small** (800, 15px, -0.01em) is used for studio panel headings. Studio card names use 26px with -0.035em.
- **Body** (Geist 400, 17px, line-height 1.6): page copy. The lede is 18px in `ink-2`, capped at 44ch. Panel copy steps down to 13.5–15px at line-height 1.45–1.5.
- **Button** (Geist 600, 15px, line-height 1). The small size is 14px and the extra-small 13px.
- **Label** (Geist Mono 500, 10.5–12px, 0.1–0.32em tracking, uppercase): status rows, run hints, the scroll cue, and tags (10px at 0.18em). The site caption is the exception: mixed case at 0.03em.
- **Note** (Geist Mono 400, 12–12.5px, line-height 1.5, `ink-2`): provenance notes, prompt messages, run-step detail and plan state lines.
- **Measure** (Geist Mono 500, 12.5px, tabular numerals): measurement values, dimension callouts in the scene (11px, 0.04em), step numerals "01–04" (11px, 0.2em, `gold-ink`).

### Named Rules
**The Two-Tone Title Rule.** Every display and headline is two lines: a statement in ink, then a short sub-line in `sub` gold, nested in the same heading element.

**The Measured-in-Mono Rule.** Anything measured, numbered, sourced or reporting status is set in Geist Mono. This covers dimensions, step numbers, the site caption and its data credit, provenance notes, run status, and scale-bar lettering. Titles, explanatory copy and buttons are never set in mono.

## Layout

The page is a fixed full-viewport WebGL canvas with document content scrolling over it. Stacking order, from back to front: scene (0), walk-in veil (1), landing (2), 3D labels and pins (3), tour view (4), nav (5), studio UI (6).

**The landing is a scroll timeline.** The hero is at least 92svh tall, with its content bottom-aligned at a 9vh bottom pad. The "How it works" section runs 135vh with its glass panel left-docked (max 620px). The "Step inside" section runs 115vh with its card bottom-left (max 560px). The horizontal gutter is clamp(16px, 5vw, 72px). Section heights set how long each camera beat lasts, so they are not arbitrary. On desktop the camera's view offset shifts the building 20–25% of viewport width to the right of the text column, then re-centres it for the walk-in between 62% and 76% of scroll. On phones the building is lifted into the upper half instead. Behind the hero title, a soft radial paper wash keeps the title legible over line-work.

**The studio is edge-docked.** Glass panels sit at a 12px inset around a full-bleed scene or tour. The space bar is top-left. The area card (340px) or plan panel (380px) is top-right and slides in 16px. The prompt bar sits bottom-centre (max 760px). The walk pad sits bottom-right. Gaps inside panels are 6–8px. Panel padding is 16–18px.

**Breakpoints.** At 900px, studio side panels, cards and the plan panel re-dock as full-width sheets 156px above the bottom, and chips scroll horizontally. At 760px, nav links hide and the site caption switches to its short form, left-aligned. At 540px, the four steps collapse to one column.

### The drafting grid
The CSS grid is fixed to the viewport: 1px ink lines at 7% opacity every 96px, and at 3.5% every 24px. The 3D ground plane repeats the same two-scale idea in metres: 10 m major lines at 0.15 alpha and 2 m minor lines at 0.06, fading out between 120 m and 300 m from the hall, into paper fog from 420 to 820. In the sample apartment the grid is 1 m and 0.25 m.

## Elevation & Depth

Depth comes from layering, not lift. Panels, cards and bars share one material, frosted glass, over a live scene. Annotations pinned to the scene (pins, dimension callouts, toasts, the site caption) are small opaque capsules instead: field white, ink, or 86–92% paper, with no blur. The glass is a warm translucent fill with a 20px backdrop blur and 1.15 saturate, a 1px white edge at 75% opacity, a hairline outer ring, and one long, soft, warm shadow with negative spread that pools beneath the panel rather than outlining it. Inside the 3D scene, depth comes from a single warm sun casting soft PCF shadows onto a 16% opacity warm shadow catcher, plus fog that fades the drawing back to paper.

### Shadow Vocabulary
- **Glass ambient** (`box-shadow: 0 0 0 1px var(--line), 0 24px 60px -36px rgba(45,32,12,.5)`): every glass panel, card, bar and control.
- **Pin lift** (`box-shadow: 0 0 0 1px var(--line), 0 8px 20px -12px rgba(40,30,15,.5)`): object pins floating over the scene.
- **Nav rule** (`box-shadow: 0 1px 0 var(--line)`): the scrolled nav, together with 82% paper fill and a 14px blur.
- **Gold focus halo** (`box-shadow: 0 0 0 3px rgba(201,154,46,.18)`): focused input wells and selects, together with a gold border.

### Named Rules
**The Glass Over the Drawing Rule.** Panels, cards and bars are translucent and blurred so the model reads through them. An opaque card over the scene breaks the world. Opaque surfaces are limited to small scene annotations and to field-white wells and rows inside glass.

**The Warm Shadow Rule.** Shadows are tinted warm brown (rgba 40–45, 30–32, 12–15), soft, and drawn with negative spread. They are never neutral grey and never hard-edged.

## Shapes

Corners are soft throughout and scale with the size of the surface: panels 28px, studio cards 22px, the prompt bar and space bar 24px, input wells 18px, list rows 14px, controls and the site caption 12px, measurement chips 6–7px. Every button, chip, tag, segment and pin is a full pill (999px). Dots and the round scroll-cue ring are circles. In 3D, the massing is a raw extrusion of the surveyed footprint with no bevel. Its storey lines are drawn every ~4.1 m, and its windows are drawn as ink rectangles on a 6 m bay rhythm, so the facade reads as a drawing rather than a render.

## Components

### Buttons
Confident, round and dark. Text buttons are always pills. Icon and list controls take the shape of their role: 36px and 32px circles for back, info and close, 42px squares at a 12px radius for the walk pad, and 12–14px-radius rows for tasks and areas.
- **Shape:** full pill (999px), 1px transparent border.
- **Primary (dark):** ink fill with on-ink text, Geist 600 at 15px, padding 13px 22px. The small size (10px 16px, 14px type) appears in the nav and inside panels. Extra-small: 8px 13px, 13px type.
- **Hover:** darkens to ink-hover and lifts 1px (0.2s transform and background).
- **Ghost:** 60% frost fill with a 22% ink border. On hover it turns white.
- **Disabled:** 45% opacity, no lift.
- **Focus:** a 2px gold-ink outline, offset 3px, everywhere.

### Chips
- **Style:** Geist 500 at 12.5px in an 80% field-white pill with a hairline border, padding 8px 11px. On hover the fill turns white and the border turns gold.
- **Variants:** the plan chip is ink-filled with on-ink text. The "More jobs" toggle uses a dashed border in `ink-2`. Below 900px the chip row scrolls horizontally without wrapping.

### Tags
A mono capsule (10px, 0.18em, uppercase) tinted by one evidence colour: 6% fill, 35% border, full-strength text. Category tags take `gold-ink`.

### Cards / Containers
- **Corner Style:** 28px for landing panels, 22px for studio cards and panels.
- **Background:** frost (`glass`) with the glass treatment from Elevation & Depth.
- **Border:** a 1px white edge plus the hairline ring. Inner sections are divided by 1px hairline rules, not boxes.
- **Internal Padding:** clamp(24px, 3.4vw, 42px) on the landing, 16–18px in the studio.
- **Entry:** studio cards slide in 16px from the right while fading in (0.35s).

### Inputs / Fields
- **Style:** a field-white well inside the glass prompt bar, 18px radius, hairline border, with a borderless 16px Geist 500 text input inside it.
- **Focus:** the well's border turns gold and gains the 3px gold halo. The attach control uses a dashed 25% ink border and turns gold on hover.
- **Error:** a mono 12.5px message in Error Brick below the well.

### Navigation
The landing nav is fixed and transparent over the hero. After scrolling it becomes 82% paper with a 14px blur and a hairline rule. It holds the bear mark and wordmark (Schibsted 800, 19px), links in Geist 500 at 14px (`ink-2`, ink on hover), and a small dark pill. Links hide below 760px. In the studio, the space bar is a glass capsule holding round 36px icon buttons, a pill-shaped space select with a status dot, and segmented controls: a 6% ink track, with the selected segment ink-filled.

### Site Caption
A mono label block (500, 12px, 0.03em) at the hero's lower right. It sits on 86% paper with a 12px radius and right-aligned text. The first line names the building. The second, in `ink-2`, credits the data source. On phones it moves to the left and shortens to "JRR Hall".

### Site Model (3D signature)
The landing's hero subject, drawn as an architectural model:
- **Hall:** massing-white extrusion (roughness 0.82). Edges are drawn in scene ink at 0.7 opacity, storey bands at 0.22, window rectangles at 0.2.
- **Gold:** a real coping strip along the roof edge (0.45 m × 0.55 m, metalness 0.6, emissive 0.25). A 0.22 m gold frame sits inside a 1.2 m-deep paper surround at the entrance (metalness 0.7). A gold ring marks the plaza, rising from 0.35 to 0.9 opacity as the camera arrives.
- **Entrance light:** a warm vertical gradient fills the opening, and a radial gold light spill falls on the plaza.
- **Neighbours:** paper volumes at 0.18 opacity, edged in scene ink at 0.15.
- **Drafting furniture:** a north arrow and a 0–30 m scale bar on the ground in scene ink at 0.55, lettered in Geist Mono at 70% alpha.
- **Light:** a warm hemisphere light (#FFF8EE over #D9CBB6, 1.15), a warm sun from the upper south-west (1.9), ACES filmic tone mapping at 0.95 exposure.
- **Line weight is opacity:** WebGL lines draw at 1px, so the hierarchy is 0.7 (subject edges), 0.55 (drafting furniture), 0.22 and 0.2 (facade detail), 0.15 (context). In 3D, weight that has to read as heavier becomes geometry, as the gold coping does, not a thicker line.

### Scroll Choreography (motion signature)
Scroll progress drives the camera through an exponential follow (rate 6/s). Beats use smoothstep windows, and the long moves use cubic ease-in-out.
- **0–10%, hero:** three-quarter aerial view (FOV 32°, elevation 0.66 rad, 262 m; 520 m on phones).
- **10–74%, orbit:** about 1.55π of a turn, lowering to 0.34 rad and ending square on the entrance.
- **74–97%, approach:** a descent to 1.7 m eye height on the plaza 26 m out, overlapping a walk to inside the door reveal. FOV opens from 32° to 70°.
- **Walk-in:** paper fades in as the camera reaches the door (keyed to the walk, not raw scroll). If the hall's tour has preloaded (from 45% scroll), the tour cross-fades in instead, and the landing fades four times faster. Reaching 98.5% of the progress bar opens the studio.
- **Pointer parallax:** pointer movement adds a small parallax of ±0.05 rad azimuth and ±0.025 rad elevation.
- **Reduced motion:** the azimuth is held, smoothing and parallax are dropped, and spinners, pulses and smooth scrolling are off. Scroll still carries the descent.

**UI motion:** 0.2s on hovers (background, border, a 1–2px lift or nudge), 0.3s on small fades, 0.35s on card and panel slides, 0.6s for the landing-to-studio cross-fade (studio UI delayed 0.2s), 0.7s on the tour view. Easing is the CSS default `ease`. Loading uses a 0.8s linear gold spinner. Pins pulse gold every 1.8s.

## Do's and Don'ts

### Do:
- **Do** keep every panel, card and bar on frosted glass (`glass` fill, 20px blur, white hairline edge, warm negative-spread shadow) so the scene reads through.
- **Do** write every display and headline as two lines: ink, then a `sub` gold sub-line.
- **Do** set measurements, step numbers, captions, data credits, notes and status in Geist Mono at weight 400 or 500.
- **Do** credit survey data in the mono site caption whenever the site model is shown.
- **Do** carry 3D line hierarchy with opacity tiers (0.7 / 0.55 / 0.22 / 0.2 / 0.15) in scene ink, and build heavy emphasis as geometry.
- **Do** reserve gold for the subject building in the scene, and for focus, hover, active and progress states in the UI.
- **Do** use the evidence colours only to say where a fact came from (scan blue, tape amber, verified green).
- **Do** give every scroll-driven move a reduced-motion path that holds the camera's azimuth and removes smoothing and parallax.

### Don't:
- **Don't** set text in `gold` (2.25:1) or `mute` (2.49:1). Use `gold-ink`, `sub` or `ink-2`.
- **Don't** give neighbouring buildings gold, solid fills or strong edges. Context stays at 0.18 fill and 0.15 line opacity.
- **Don't** place opaque cards over the scene. Opaque surfaces are limited to small annotation capsules and to wells and rows inside glass.
- **Don't** use neutral-grey or hard offset shadows. Shadows are soft and warm-tinted.
- **Don't** put a small tracked mono label above a heading as a kicker. Mono labels describe data, not sections.
- **Don't** use Unicode characters as icon controls or status marks. Draw icons as inline SVG, as the scroll cue does.
- **Don't** use overshoot or bounce easing. Panels arrive on the default ease.


## Site model, recognisable edition (2026-11-14)

JRR Hall is no longer a paper massing model. It now reads as the real building, while the ground stays the drafting world:

- **Walls:** `facade.js` paints a 6 m Collegiate Gothic bay. Argillite ashlar `#6E6670`–`#857B87` in mortar `#9E968F`; limestone `#DDD4C2` (shade `#C7BDA9`) for the plinth, string courses, window surrounds, mullions and coping; steel casements `#2A2E31` over glass shading `#7C8C96` to `#2F3A42`; Tudor-arched heads on the ground floor. Corner quoins and parapet coping are limestone geometry (`#DCD3C1`).
- **Roof:** Vexcel's aerial photo (`assets/jrr-roof.jpg`). Gold stays as a single line on the coping and the portal's arch.
- **Entrance:** a limestone Gothic portal (`#CFC5B0`) with a pointed arch, lit warm from inside (`#9C8762` to `#F8EAC6`), with a gold arch line and light spill.
- **Ground:** the aerial photo printed ink-on-paper (`#60564A` on paper, at most 55%), fading out to the paper by about 110 m; drafting grid lines lighter on top (0.045 / 0.12).
- **Trees:** low-poly flat-shaded crowns in `#7C986A`, `#6A8758`, `#8FAA78`, `#728F62`, with trunks `#6B5A48`, placed from the photo's canopy and kept off the walk-in path.
- **Scudder Plaza:** water `#5A6A72`, limestone rim, bronze `#4E3E2C`.
- **Neighbours:** still paper volumes with ink line-work (fill 0.32, edges 0.18), so JRR Hall leads.

**Studio over a tour:** the top-left keeps only the round back button (drawn arrow) and a dark key-hint pill (`rgba(23,20,15,.55)`), both placed below Matterport's logo.
