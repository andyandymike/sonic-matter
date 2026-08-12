extends SceneTree

const GateADemoScript = preload("res://examples/gate_a_3d/gate_a_demo.gd")
const ORACLE_PATH := "res://examples/gate_a_3d/export_inventory_v1.json"

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    _test_valid_records()
    _test_forbidden_prefix()
    _test_missing_extra_and_tamper()
    _test_existing_error()
    _test_frozen_oracle_shape()
    if _failures.is_empty():
        print("RUNTIME_V2_EXPORT_INVENTORY_VALIDATOR_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("RUNTIME_V2_EXPORT_INVENTORY_VALIDATOR_FAILED count=%d" % _failures.size())
    quit(1)


func _test_valid_records() -> void:
    var records := [_record("res://addons/sonic_matter/runtime/example.gdc", 12, "a")]
    var result: Dictionary = GateADemoScript.validate_export_inventory_records(
        records,
        records.duplicate(true),
    )
    _expect(bool(result.get("ok", false)), "matching records should pass")


func _test_forbidden_prefix() -> void:
    for path in [
        "res://spec/private.md",
        "res://tests/fixture.json",
        "res://tools/helper.gd",
        "res://content-packs/ui/audio.ogg",
    ]:
        var records := [_record(path, 1, "b")]
        var result: Dictionary = GateADemoScript.validate_export_inventory_records(
            records,
            records.duplicate(true),
        )
        _expect(not bool(result.get("ok", true)), "forbidden path passed: %s" % path)
        _expect(
            (result.get("forbidden_paths", []) as Array).has(path),
            "forbidden path was not reported: %s" % path,
        )


func _test_missing_extra_and_tamper() -> void:
    var expected := [
        _record("res://addons/a.gdc", 10, "a"),
        _record("res://addons/b.gdc", 20, "b"),
    ]
    var missing: Dictionary = GateADemoScript.validate_export_inventory_records(
        [expected[0]],
        expected,
    )
    _expect(not bool(missing.get("ok", true)), "missing member passed")

    var extra_actual := expected.duplicate(true)
    extra_actual.append(_record("res://addons/c.gdc", 30, "c"))
    var extra: Dictionary = GateADemoScript.validate_export_inventory_records(
        extra_actual,
        expected,
    )
    _expect(not bool(extra.get("ok", true)), "extra member passed")

    var tampered := expected.duplicate(true)
    tampered[1] = _record("res://addons/b.gdc", 21, "tampered")
    var changed: Dictionary = GateADemoScript.validate_export_inventory_records(
        tampered,
        expected,
    )
    _expect(not bool(changed.get("ok", true)), "tampered member passed")
    _expect(
        not (changed.get("mismatches", []) as Array).is_empty(),
        "tampered member was not reported",
    )


func _test_existing_error() -> void:
    var records := [_record("res://addons/a.gdc", 10, "a")]
    var result: Dictionary = GateADemoScript.validate_export_inventory_records(
        records,
        records.duplicate(true),
        ["collector failed"],
    )
    _expect(not bool(result.get("ok", true)), "collector error passed")


func _test_frozen_oracle_shape() -> void:
    var file := FileAccess.open(ORACLE_PATH, FileAccess.READ)
    _expect(file != null, "frozen export oracle is missing")
    if file == null:
        return
    var parsed = JSON.parse_string(file.get_as_text())
    _expect(parsed is Dictionary, "frozen export oracle is invalid JSON")
    if not parsed is Dictionary:
        return
    var oracle: Dictionary = parsed
    _expect(int(oracle.get("schema_version", 0)) == 1, "oracle schema drifted")
    _expect(oracle.get("release") == "0.1.0-rc1", "oracle release drifted")
    var records: Array = oracle.get("records", [])
    _expect(records.size() == 40, "oracle member count drifted")
    var result: Dictionary = GateADemoScript.validate_export_inventory_records(
        records,
        records.duplicate(true),
    )
    _expect(bool(result.get("ok", false)), "frozen oracle contains forbidden/invalid records")


func _record(path: String, size: int, digest_seed: String) -> Dictionary:
    return {
        "path": path,
        "size": size,
        "sha256": digest_seed.repeat(64).substr(0, 64),
    }


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
