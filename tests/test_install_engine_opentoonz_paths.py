from pathlib import Path


def test_opentoonz_tiff_paths_are_absolute_from_repo_root():
    script = Path("scripts/install_engine.py").read_text()
    assert 'tiff_prefix = (tiff_dir / "ci-install").resolve()' in script
    assert 'tiff_private_include = tiff_dir / "libtiff"' in script
    assert 'f"-DCMAKE_C_FLAGS=-I{tiff_private_include}"' in script
    assert 'f"-DCMAKE_CXX_FLAGS=-I{tiff_private_include}"' in script
