#!/usr/bin/env python3
"""Run a real Blender render and emit evidence from the actual output."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    blender = shutil.which("blender")
    if blender is None:
        raise RuntimeError("Blender executable is not installed on this worker")

    version = subprocess.run(
        [blender, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not version:
        raise RuntimeError("Blender did not report a version")

    with tempfile.TemporaryDirectory(prefix="sasquatch-blender-verify-") as temp:
        root = Path(temp)
        scene_script = root / "scene.py"
        blend_file = root / "verification.blend"
        output_prefix = root / "render"
        scene_script.write_text(
            """
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 320
scene.render.resolution_y = 180
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = 'OUTPUT'

bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
sphere = bpy.context.object
sphere.scale = (1.5, 1.5, 1.5)

bpy.ops.object.light_add(type='AREA', location=(3, -4, 5))
light = bpy.context.object
light.data.energy = 900
light.data.shape = 'DISK'
light.data.size = 4

bpy.ops.object.camera_add(location=(0, -7, 1.5), rotation=(1.45, 0, 0))
camera = bpy.context.object
scene.camera = camera

bpy.ops.wm.save_as_mainfile(filepath='BLEND')
bpy.ops.render.render(write_still=True)
"""
            .replace("OUTPUT", str(output_prefix))
            .replace("BLEND", str(blend_file))
        )

        completed = subprocess.run(
            [blender, "-b", "--python", str(scene_script)],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Blender render failed with exit code "
                f"{completed.returncode}: {(completed.stderr or completed.stdout).strip()}"
            )

        output = Path(f"{output_prefix}0001.png")
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("Blender exited successfully but produced no PNG render")
        if not blend_file.is_file() or blend_file.stat().st_size == 0:
            raise RuntimeError("Blender did not produce the source .blend artifact")

        evidence = {
            "engine_id": "blender",
            "engine_version": version.splitlines()[0],
            "executable": blender,
            "version_observation": version,
            "checkpoint_path": "not_required_for_blender_runtime",
            "checkpoint_sha256": hashlib.sha256(
                b"Blender runtime has no model checkpoint requirement"
            ).hexdigest(),
            "license_source": "https://github.com/blender/blender",
            "license_evidence": "Blender source repository declares GPL-3.0-or-later",
            "runtime_output_sha256": sha256_file(output),
            "source_blend_sha256": sha256_file(blend_file),
            "output_bytes": output.stat().st_size,
        }
        Path("blender-runtime-evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        )
        Path("blender-runtime-render.png").write_bytes(output.read_bytes())
        Path("blender-runtime-source.blend").write_bytes(blend_file.read_bytes())
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
