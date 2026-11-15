# JRR Hall tour, with people removed

The studio shows JRR Hall through our own viewer (`pano-tour.js`) instead of the Matterport embed, so that no person appears anywhere in the tour.

## What's here

- `<sweep id>.jpg`: one 4096×2048 equirectangular panorama per scan point, 66 in all, with every detected person removed.
- `tour.json`: the scan points' positions, floors and links, plus the start view.

`tour.json` uses Matterport's own coordinates: metres, with `y` up and the camera at eye height. Each image's centre faces world −z (heading 0). Yaw is in degrees and increases to the left, matching Matterport and three.js's `camera.rotation.y`. The start view is just inside the main entrance doors, in the restored Gothic arcade, facing the atrium (`start.yaw` 270).

## Where it comes from

The source is the CoStar team's Matterport scan of JRR Hall (model `2K7G7cdukZV`), made available for the 2026 Princeton hackathon.

1. **Capture.** The Showcase SDK's `Renderer.takeEquirectangular()` was run at every scan point, each at heading 0. Our Model API key cannot download this model, but the SDK key can render it on `localhost`.
2. **Find people.** YOLO11x-seg (Ultralytics) segmented people in overlapping 768 px tiles. The tiles cover the band where people appear (14–95% of the image height), wrap across the 360° seam, and are followed by a whole-image pass for people close to the camera. Each person's mask is grown in proportion to their height: sideways for the smeared trail a walking person leaves, and downward for feet and shadow.
3. **Fill.** big-lama (LaMa) filled one group of people at a time, in a rectangle that contains the whole group, so no mask is cut by a crop edge. Crops larger than 1024 px are scaled down first, because LaMa stays coherent on holes at that scale.
4. **Re-check.** Each cleaned panorama was scanned again and refilled if anyone was still found, up to three fills.
5. **Independent audit.** A second detector family (RT-DETR-x) and YOLO11x scanned every cleaned panorama on a tile grid offset from the first, at lower thresholds. Every detection was reviewed by eye. Real people, mostly seen through glass railings or from above, were filled by box, and the audit was rerun on those panoramas until it found no more people. Every filled region was also reviewed by eye, and leftover ghosts were filled by hand-placed boxes. That covers a motion-blurred walker and a person-shaped shadow.

The scripts were run outside the repo: `pano_capture_all.py`, `depeople.py`, `audit_strong.py` and `fix_boxes.py`. To regenerate, rerun them with the backend serving its `/web-config` SDK key on `localhost`.

## Limits

- **Detection, not proof.** Removal rests on two detectors and a review by eye. A person all of these missed, such as a faint reflection in glass, would still be there.
- **Filled areas.** These are reconstructions, not photographs of the empty space. Where people sat or stood close to the camera, as in the atrium, the fill is a soft blur of floor and furniture rather than sharp detail.
- **Licence.** The imagery belongs to the scan's owner. Use it for the hackathon demo, and ask before publishing it elsewhere.
