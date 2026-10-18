import json

from avaz.web import export_scales, scales_json, web_dir


def test_web_scales_match_scales_yaml():
    """web/scales.json must be re-exported (`avaz web --export-only`) after editing scales.yaml."""
    on_disk = json.loads((web_dir() / "scales.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(scales_json()))


def test_export_scales_writes_positions_and_labels(tmp_path):
    yaml_file = tmp_path / "scales.yaml"
    yaml_file.write_text("test:\n  positions: [0, 150, 1200]\n  labels: [t, k, o]\nplain: [0, 700]\n",
                         encoding="utf-8")
    out = export_scales(tmp_path / "scales.json", scales_path=yaml_file)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["test"] == {"positions": [0.0, 150.0, 1200.0], "labels": ["t", "k", "o"]}
    assert data["plain"]["positions"] == [0.0, 700.0]
    assert data["plain"]["labels"] == ["0", "700"]
