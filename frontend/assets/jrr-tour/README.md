# JRR Hall tour, with people removed

The studio shows JRR Hall through our own viewer (`pano-tour.js`) instead of the Matterport embed, so that no person appears anywhere in the tour.

## What's here

- `<sweep id>.jpg`: one 4096×2048 equirectangular panorama per scan point, 66 in all, with every detected person removed.
- `tour.json`: the scan points' positions, floors and links, plus the start view.

`tour.json` uses Matterport's own coordinates: metres, with `y` up and the camera at eye height. Each image's centre faces world −z (heading 0). Yaw is in degrees and increases to the left, matching Matterport and three.js's `camera.rotation.y`. The start view is just inside the main entrance doors, in the restored Gothic arcade, facing the atrium (`start.yaw` 270).

## Where it comes from

The source is the CoStar team's Matterport scan of JRR Hall (model `2K7G7cdukZV`), made available for the 2026 Princeton hackathon.

1. **Capture.** The Showcase SDK's `Renderer.takeEquirectangular()` was run at every scan point, each at heading 0. Our Model API key cannot download this model, but the SDK key can render it on `localhost`.
2. **Find people.** YOLO11x-seg (Ultralytics) segmented people in overlapping 768 px tiles. The tiles cover the band where people appear (14–95% of the image height), wrap across the 360° seam, and are followed by a whole-image pass for people close to the camera. Masks were grown by 10 px.
3. **Fill.** big-lama (LaMa) filled each masked area in a crop around it, at full resolution.
4. **Check.** Each cleaned panorama was scanned again and refilled if anyone was still found, up to three fills. `_log.tsv` (kept with the scratch tools, not shipped here) records how many people each pass found; the last pass must find none.

The scripts were run outside the repo: `depeople.py` and `pano_capture_all.py`. To regenerate, rerun both with the backend serving its `/web-config` SDK key on `localhost`.

## Limits

- **Detection, not proof.** Removal is detection-based. A person the detector can't see won't be removed: someone heavily blurred, or a tiny reflection in glass.
- **Filled areas.** These are plausible reconstructions, not photographs of the empty space, and a few may show soft smudges.
- **Licence.** The imagery belongs to the scan's owner. Use it for the hackathon demo, and ask before publishing it elsewhere.
