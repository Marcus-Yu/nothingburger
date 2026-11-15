"""The metric scale a scene package was published at, and the evidence behind it.

Matterport and Vexcel data is already metric, so an import records `method="survey"` with scale
1.0 (`pipeline.ingest`). `package.write_scene_json` writes the method into `scene.json`, and a
package with `method="none"` is flagged as not at true scale.
"""

from dataclasses import dataclass


@dataclass
class ScaleEstimate:
    # "survey" (a measured source: Matterport, Vexcel) | "known_dimension" | "none"
    method: str
    scale: float
    residual_m: float | None
    notes: str = ""
