"""Fetch Matterport's SDK bundle into web/_vendor/matterport (not committed), for web/viewer/tour.html.

    python web/fetch_sdk.py

The bundle is Matterport's own showcase player with the SDK built in; served from this machine it lets the
tour page add the robot to the scan's three.js scene. It needs MATTERPORT_SDK_KEY in .env, and that key
only works on pages served from localhost. Version pinned below; newer ones are listed at
https://matterport.github.io/showcase-sdk/sdkbundle_home.html
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "26.5.4_webgl-708-g332adb66f5"
URL = f"https://static.matterport.com/showcase-sdk/bundle/{VERSION}/showcase-bundle.zip"
DEST = Path(__file__).resolve().parent / "_vendor" / "matterport"


def main() -> int:
    print("fetching", URL)
    data = urllib.request.urlopen(URL, timeout=120).read()
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():  # nothing may land outside DEST
            if name.startswith("/") or ".." in Path(name).parts:
                sys.exit(f"refusing to unpack {name!r}")
        z.extractall(DEST)
    print("ok  ", DEST, f"({len(data) / 1e6:.1f} MB zipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
