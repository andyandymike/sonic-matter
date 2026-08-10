#!/usr/bin/env python3
"""Verify the addon archive in a blank Godot project and cycle its plugin."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile

from package_rc0 import AuditError, verify_archive

ROOT = Path(__file__).resolve().parents[1]
SMOKE_ENV = "SONIC_MATTER_PLUGIN_SMOKE"

PROJECT_TEMPLATE = """; Generated clean-install fixture.
config_version=5

[application]

config/name="SonicMatter clean install"
config/features=PackedStringArray("4.6", "GL Compatibility")

[editor_plugins]

enabled={enabled}

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""

RUNTIME_SMOKE = """extends SceneTree

const EmitterScript := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var source := SonicAcousticMaterial.new()
    source.material_id = &"clean_source"
    source.family_id = &"wood"

    var target := SonicAcousticMaterial.new()
    target.material_id = &"clean_target"
    target.family_id = &"stone"

    var output := SonicAcousticMaterial.new()
    output.material_id = &"clean_output"
    output.family_id = &"wood"
    var stream := AudioStreamWAV.new()
    stream.format = AudioStreamWAV.FORMAT_16_BITS
    stream.mix_rate = 48000
    stream.stereo = false
    stream.data = PackedByteArray()
    stream.data.resize(9600)
    var variant := SonicSampleVariant.new()
    variant.stream = stream
    output.impact_variants.append(variant)

    var route := SonicImpactRoute.new()
    route.route_id = &"clean-route"
    route.source_material_id = source.stable_id()
    route.target_material_id = target.stable_id()
    route.output_material = output
    var route_map := SonicImpactRouteMap.new()
    route_map.exact_routes.append(route)

    var emitter := EmitterScript.new()
    emitter.impact_route_map = route_map
    root.add_child(emitter)
    await process_frame

    var event := SonicFoleyEvent.impact(
        1,
        1,
        0.7,
        Vector3.ZERO,
        0,
        SonicFoleyEvent.Evidence.AUTHORED,
        source.stable_id(),
        target.stable_id(),
        SonicFoleyEvent.Evidence.AUTHORED,
    )
    var details: Dictionary = emitter.play_impact(source, target, event)
    var snapshot: Dictionary = emitter.debug_snapshot()
    var passed := (
        not details.is_empty()
        and int(snapshot.get("played", 0)) == 1
        and int(snapshot.get("route_exact_ordered", 0)) == 1
        and int(snapshot.get("route_drops", 0)) == 0
        and int(snapshot.get("active_voices", 0)) <= 8
    )
    emitter.queue_free()
    await process_frame

    if passed:
        print("CLEAN_ADDON_RUNTIME_OK")
        quit(0)
        return
    push_error("CLEAN_ADDON_RUNTIME_FAILED %s" % JSON.stringify(snapshot))
    quit(1)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--godot", default="godot")
    parser.add_argument("--keep", action="store_true")
    return parser.parse_args()


def extract_verified_archive(archive_path: Path, destination: Path) -> Path:
    verify_archive(archive_path)
    with zipfile.ZipFile(archive_path, "r") as archive:
        file_names = [name for name in archive.namelist() if not name.endswith("/")]
        root_names = {PurePosixPath(name).parts[0] for name in file_names}
        if len(root_names) != 1:
            raise AuditError("archive must contain one root")
        archive_root = next(iter(root_names))
        extracted_root = destination / archive_root
        for name in file_names:
            parts = PurePosixPath(name).parts
            if not parts or parts[0] != archive_root or ".." in parts:
                raise AuditError(f"unsafe archive member: {name}")
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return extracted_root


def write_project(project_root: Path, enabled: bool) -> None:
    enabled_value = (
        'PackedStringArray("res://addons/sonic_matter/plugin.cfg")'
        if enabled
        else "PackedStringArray()"
    )
    (project_root / "project.godot").write_text(
        PROJECT_TEMPLATE.format(enabled=enabled_value),
        encoding="utf-8",
        newline="\n",
    )


def run_godot(
    godot: str,
    project_root: Path,
    arguments: list[str],
) -> str:
    environment = os.environ.copy()
    environment[SMOKE_ENV] = "1"
    result = subprocess.run(
        [godot, "--headless", "--path", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=30,
    )
    combined = result.stdout + result.stderr
    print(combined, end="")
    if result.returncode != 0:
        raise AuditError(
            f"Godot command failed with {result.returncode}: {' '.join(arguments)}"
        )
    if "SCRIPT ERROR:" in combined or "\nERROR:" in combined:
        raise AuditError(f"Godot reported a script/runtime error: {' '.join(arguments)}")
    return combined


def verify_cycle(godot: str, project_root: Path) -> None:
    for cycle, enabled in enumerate((False, True, False, True), start=1):
        write_project(project_root, enabled)
        output = run_godot(
            godot,
            project_root,
            ["--editor", "--quit"],
        )
        entered = "SONIC_MATTER_PLUGIN_ENTERED" in output
        exited = "SONIC_MATTER_PLUGIN_EXITED" in output
        if enabled and (not entered or not exited):
            raise AuditError(
                f"plugin cycle {cycle} did not enter and exit while enabled"
            )
        if not enabled and (entered or exited):
            raise AuditError(
                f"plugin cycle {cycle} loaded while disabled"
            )


def main() -> int:
    args = parse_args()
    archive = args.archive.resolve()
    artifact_root = (ROOT / "artifacts" / "clean-install").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(prefix="sonic-matter-", dir=artifact_root)
    ).resolve()
    if workspace.parent != artifact_root:
        print(f"CLEAN_ADDON_INSTALL_FAILED unsafe workspace {workspace}", file=sys.stderr)
        return 1

    succeeded = False
    try:
        package_root = extract_verified_archive(archive, workspace / "archive")
        project_root = workspace / "target"
        project_root.mkdir()
        shutil.copytree(package_root / "addons", project_root / "addons")

        verify_cycle(args.godot, project_root)
        (project_root / "clean_addon_smoke.gd").write_text(
            RUNTIME_SMOKE,
            encoding="utf-8",
            newline="\n",
        )
        output = run_godot(
            args.godot,
            project_root,
            ["--script", "res://clean_addon_smoke.gd"],
        )
        if "CLEAN_ADDON_RUNTIME_OK" not in output:
            raise AuditError("clean addon runtime sentinel is missing")

        print("CLEAN_ADDON_INSTALL_OK")
        succeeded = True
        return 0
    except (
        AuditError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"CLEAN_ADDON_INSTALL_FAILED {error}", file=sys.stderr)
        print(f"CLEAN_ADDON_INSTALL_WORKSPACE {workspace}", file=sys.stderr)
        return 1
    finally:
        if succeeded and not args.keep:
            shutil.rmtree(workspace)


if __name__ == "__main__":
    raise SystemExit(main())
