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

# Make this repository script directly runnable from any working directory.
# The production package lives at the repository root, not inside scripts/.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.production import ProductionResponse


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
        output = root / "render.png"
        scene_script.write_text(
            """
import bpy
import os

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_set(1)
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

bpy.ops.object.camera_add(location=(0, -7, 1.5))
camera = bpy.context.object
camera.rotation_euler = (sphere.location - camera.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = camera

bpy.ops.wm.save_as_mainfile(filepath='BLEND')
result = bpy.ops.render.render(write_still=True)
if 'FINISHED' not in result:
    raise RuntimeError(f'Blender render operator did not finish: {result!r}')
if not os.path.isfile('OUTPUT') or os.path.getsize('OUTPUT') == 0:
    raise RuntimeError('Blender render completed but the configured output file was not written')
print('BLENDER_RENDER_OK:OUTPUT')
"""
            .replace("OUTPUT", str(output))
            .replace("BLEND", str(blend_file))
        )

        completed = subprocess.run(
            [blender, "-b", "--python", str(scene_script)],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        sentinel = f"BLENDER_RENDER_OK:{output}"
        if completed.returncode != 0 or sentinel not in stdout:
            diagnostics = (stderr + "\n" + stdout)[-8000:]
            raise RuntimeError(
                "Blender runtime verification did not complete the required render contract. "
                f"exit_code={completed.returncode}; expected_sentinel={sentinel!r}; "
                f"output_exists={output.is_file()}; diagnostics:\n{diagnostics}"
            )

        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(
                "Blender reported a completed render, but the required PNG artifact is missing or empty. "
                f"Output directory: {root}"
            )
        if not blend_file.is_file() or blend_file.stat().st_size == 0:
            raise RuntimeError("Blender did not produce the source .blend artifact")

        source_hash = sha256_file(scene_script)
        output_hash = sha256_file(output)
        response = ProductionResponse(
            "blender",
            (str(output),),
            {
                "execution": "subprocess",
                "engine_id": "blender",
                "engine_version": version.splitlines()[0],
                "license": "GPL-3.0-or-later",
                "quality_tier": "professional_3d",
                "canonical_source_hash": source_hash,
                "output_sha256": output_hash,
                "exit_code": completed.returncode,
            },
        )
        cas = ContentAddressedStore("runtime-artifacts")
        lineage = ArtifactLineageStore("runtime-artifacts/lineage.sqlite3")
        committed = ArtifactCommitter(cas, lineage).commit(
            response, stage="animate", source_hash=source_hash
        )
        if len(committed) != 1 or not committed[0].startswith("sha256:"):
            raise RuntimeError("real Blender output was not committed to the content-addressed store")

        evidence = {
            "engine_id": "blender",
            "engine_version": version.splitlines()[0],
            "executable": blender,
            "version_observation": version,
            "checkpoint_path": "not_required_for_blender_runtime",
            "checkpoint_sha256": None,
            "license_source": "https://github.com/blender/blender",
            "license_evidence": "Blender source repository declares GPL-3.0-or-later",
            "runtime_output_sha256": output_hash,
            "source_blend_sha256": sha256_file(blend_file),
            "canonical_source_sha256": source_hash,
            "artifact_address": committed[0],
            "artifact_lineage_stage": "animate",
            "output_bytes": output.stat().st_size,
        }
        Path("blender-runtime-evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        )
        Path("blender-runtime-render.png").write_bytes(output.read_bytes())
        Path("blender-runtime-source.blend").write_bytes(blend_file.read_bytes())
        shutil.copytree("runtime-artifacts", "blender-runtime-artifacts", dirs_exist_ok=True)
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
