from pathlib import Path


def test_opentoonz_tiff_paths_are_absolute_from_repo_root():
    script = Path("scripts/install_engine.py").read_text()
    assert 'tiff_prefix = (tiff_dir / "ci-install").resolve()' in script
    assert 'tiff_private_include = (tiff_dir / "libtiff").resolve()' in script
    assert 'f"-DCMAKE_C_FLAGS=-I{tiff_private_include}"' in script
    assert 'f"-DCMAKE_CXX_FLAGS=-I{tiff_private_include}"' in script


def test_opentoonz_uses_supported_version_qualifier():
    script = Path("scripts/install_engine.py").read_text()
    assert 'run(str(opentoonz), "-version", timeout=120)' not in script
    assert 'subprocess.run(\n        [str(executable), "-version"]' in script
    assert 'result.returncode not in (0, 1)' in script
    assert 'OpenToonz\\s+v?(\\d+\\.\\d+(?:\\.\\d+)?)' in script


def test_opentoonz_version_probe_parses_observed_stdout_or_stderr():
    script = Path("scripts/install_engine.py").read_text()
    assert 'observed_output = "\\n".join(part for part in (result.stdout, result.stderr) if part)' in script
    assert 're.search(r"OpenToonz\\s+v?(\\d+\\.\\d+(?:\\.\\d+)?)", observed_output)' in script


def test_opentoonz_version_probe_does_not_mask_other_failures():
    script = Path("scripts/install_engine.py").read_text()
    assert 'if result.returncode not in (0, 1):' in script
    assert 'OpenToonz version probe failed with exit code' in script
    assert 'OpenToonz version probe did not report a parseable OpenToonz version' in script


def test_ltx_evidence_is_written_to_workflow_upload_path():
    script = Path("scripts/install_engine.py").read_text()
    assert 'evidence(engine_id, "https://github.com/Lightricks/LTX-Video", ROOT / engine_id, models, [])' in script
