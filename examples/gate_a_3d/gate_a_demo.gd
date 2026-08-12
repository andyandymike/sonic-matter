extends Node3D

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const IMPACT_ADAPTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_rigid_body_impact_adapter_3d.gd")
const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")
const EXPORT_INVENTORY_ORACLE := (
    "res://examples/gate_a_3d/export_inventory_v1.json"
)
const FORBIDDEN_EXPORT_PREFIXES := [
    "res://spec/",
    "res://planning-private/",
    "res://.local/",
    "res://tests/",
    "res://tools/",
    "res://content-packs/",
    "res://.github/",
    "res://docs/",
    "res://packaging/",
]

var _emitter: Node3D
var _bodies: Array[RigidBody3D] = []
var _initial_positions: Array[Vector3] = []
var _source_materials: Dictionary = {}
var _ground_material: SonicAcousticMaterial
var _debug_label: Label
var _last_event: String = "waiting for impact"
var _voice_started_observed: int = 0
var _voice_start_failures: int = 0


func _ready() -> void:
    _build_world()
    _build_interface()
    _reset_all()
    var user_args := OS.get_cmdline_user_args()
    if user_args.has("--gate-a-export-inventory-observe"):
        call_deferred("_run_export_inventory_observe")
    elif user_args.has("--gate-a-export-smoke"):
        call_deferred("_run_export_smoke")


func _run_export_smoke() -> void:
    await get_tree().create_timer(4.0).timeout
    var snapshot: Dictionary = _emitter.call("debug_snapshot")
    snapshot["voice_started_observed"] = _voice_started_observed
    snapshot["voice_start_failures"] = _voice_start_failures
    print("GATE_A_EXPORT_SNAPSHOT %s" % JSON.stringify(snapshot))
    var inventory_result := _verify_export_inventory()
    print("GATE_A_EXPORT_INVENTORY %s" % JSON.stringify(inventory_result, "", true, true))

    var capacity := int(snapshot.get("voice_capacity", 0))
    var active := int(snapshot.get("active_voices", 0))
    var passed := (
        int(snapshot.get("submitted", 0)) >= 3
        and int(snapshot.get("selected", 0)) >= 3
        and int(snapshot.get("played", 0)) >= 3
        and _voice_started_observed >= 3
        and _voice_start_failures == 0
        and int(snapshot.get("invalid_events", 0)) == 0
        and int(snapshot.get("missing_mappings", 0)) == 0
        and int(snapshot.get("route_exact_ordered", 0)) >= 3
        and int(snapshot.get("route_drops", 0)) == 0
        and capacity == 8
        and active >= 0
        and active <= capacity
        and bool(inventory_result.get("ok", false))
    )
    if passed:
        print("GATE_A_EXPORT_SMOKE_OK")
        get_tree().quit(0)
        return
    push_error("GATE_A_EXPORT_SMOKE_FAILED snapshot or PCK inventory mismatch")
    get_tree().quit(1)


func _run_export_inventory_observe() -> void:
    await get_tree().process_frame
    var inventory := _build_export_inventory()
    var records: Array = inventory.get("records", [])
    var payload := {
        "schema_version": 1,
        "release": "0.1.0-rc1",
        "oracle_path": EXPORT_INVENTORY_ORACLE,
        "oracle_excluded_from_records": true,
        "records": records,
        "inventory_sha256": JSON.stringify(records, "", true, true).sha256_text(),
        "errors": inventory.get("errors", []),
    }
    print(
        "GATE_A_EXPORT_INVENTORY_OBSERVATION %s"
        % JSON.stringify(payload, "", true, true)
    )
    get_tree().quit(0 if (inventory.get("errors", []) as Array).is_empty() else 1)


func _verify_export_inventory() -> Dictionary:
    var inventory := _build_export_inventory()
    var errors: Array = (inventory.get("errors", []) as Array).duplicate(true)
    var expected_records: Array = []
    var oracle_file := FileAccess.open(EXPORT_INVENTORY_ORACLE, FileAccess.READ)
    if oracle_file == null:
        errors.append("inventory oracle is missing")
    else:
        var parsed = JSON.parse_string(oracle_file.get_as_text())
        if not parsed is Dictionary:
            errors.append("inventory oracle is invalid JSON")
        else:
            var oracle: Dictionary = parsed
            if int(oracle.get("schema_version", 0)) != 1:
                errors.append("inventory oracle schema drifted")
            if oracle.get("release") != "0.1.0-rc1":
                errors.append("inventory oracle release drifted")
            if oracle.get("oracle_path") != EXPORT_INVENTORY_ORACLE:
                errors.append("inventory oracle path drifted")
            if not bool(oracle.get("oracle_excluded_from_records", false)):
                errors.append("inventory oracle self-exclusion is not declared")
            expected_records = oracle.get("records", [])

    var actual_records: Array = inventory.get("records", [])
    var result := validate_export_inventory_records(
        actual_records,
        expected_records,
        errors,
    )
    result["inventory_sha256"] = (
        JSON.stringify(actual_records, "", true, true).sha256_text()
    )
    result["oracle_path"] = EXPORT_INVENTORY_ORACLE
    return result


static func validate_export_inventory_records(
        actual_records: Array,
        expected_records: Array,
        existing_errors: Array = [],
) -> Dictionary:
    var errors: Array = existing_errors.duplicate(true)
    var forbidden_paths: Array[String] = []
    var mismatches: Array[Dictionary] = []

    for record_value in actual_records:
        if not record_value is Dictionary:
            errors.append("actual inventory contains a non-record")
            continue
        var record: Dictionary = record_value
        var path := String(record.get("path", ""))
        for prefix_value in FORBIDDEN_EXPORT_PREFIXES:
            var prefix := String(prefix_value)
            if path.begins_with(prefix):
                forbidden_paths.append(path)
                break

    if actual_records.size() != expected_records.size():
        errors.append(
            "inventory count expected=%d actual=%d"
            % [expected_records.size(), actual_records.size()]
        )
    for index in mini(actual_records.size(), expected_records.size()):
        var actual_value = actual_records[index]
        var expected_value = expected_records[index]
        if not actual_value is Dictionary or not expected_value is Dictionary:
            mismatches.append({"index": index, "reason": "non_record"})
            continue
        var actual: Dictionary = actual_value
        var expected: Dictionary = expected_value
        if (
            String(actual.get("path", "")) != String(expected.get("path", ""))
            or int(actual.get("size", -1)) != int(expected.get("size", -1))
            or String(actual.get("sha256", ""))
            != String(expected.get("sha256", ""))
        ):
            mismatches.append({
                "index": index,
                "expected": expected.duplicate(true),
                "actual": actual.duplicate(true),
            })

    return {
        "ok": errors.is_empty() and forbidden_paths.is_empty() and mismatches.is_empty(),
        "record_count": actual_records.size(),
        "expected_record_count": expected_records.size(),
        "errors": errors,
        "forbidden_paths": forbidden_paths,
        "mismatches": mismatches,
    }


func _build_export_inventory() -> Dictionary:
    var paths: Array[String] = []
    var errors: Array[String] = []
    _collect_export_paths("res://", paths, errors)
    paths.sort()

    var records: Array[Dictionary] = []
    for path in paths:
        if path == EXPORT_INVENTORY_ORACLE:
            continue
        var file := FileAccess.open(path, FileAccess.READ)
        if file == null:
            errors.append("cannot open exported member: %s" % path)
            continue
        var size := file.get_length()
        file.close()
        var digest := FileAccess.get_sha256(path).to_lower()
        if digest.length() != 64:
            errors.append("cannot hash exported member: %s" % path)
            continue
        records.append({
            "path": path,
            "size": size,
            "sha256": digest,
        })
    return {"records": records, "errors": errors}


func _collect_export_paths(
        directory_path: String,
        paths: Array[String],
        errors: Array[String],
) -> void:
    var directory := DirAccess.open(directory_path)
    if directory == null:
        errors.append("cannot open exported directory: %s" % directory_path)
        return

    var child_directories: Array[String] = []
    var child_files: Array[String] = []
    directory.list_dir_begin()
    var child_name := directory.get_next()
    while not child_name.is_empty():
        if child_name != "." and child_name != "..":
            if directory.current_is_dir():
                child_directories.append(child_name)
            else:
                child_files.append(child_name)
        child_name = directory.get_next()
    directory.list_dir_end()

    child_directories.sort()
    child_files.sort()
    for child_file in child_files:
        paths.append(directory_path.path_join(child_file))
    for child_directory in child_directories:
        _collect_export_paths(
            directory_path.path_join(child_directory),
            paths,
            errors,
        )


func _process(_delta: float) -> void:
    if _debug_label == null or _emitter == null:
        return
    var snapshot: Dictionary = _emitter.call("debug_snapshot")
    _debug_label.text = (
        "Space: drop all    1/2/3: drop one    R: reset\n"
        + "Synthetic fixtures only — not production Foley\n"
        + "submitted=%d  selected=%d  played=%d  active=%d/%d  steals=%d\n"
        + "routes exact=%d sym=%d target=%d source=%d default=%d drops=%d\n"
        + "no-repeat=%d  missing=%d  invalid=%d\nlast: %s"
    ) % [
        int(snapshot.get("submitted", 0)),
        int(snapshot.get("selected", 0)),
        int(snapshot.get("played", 0)),
        int(snapshot.get("active_voices", 0)),
        int(snapshot.get("voice_capacity", 0)),
        int(snapshot.get("voice_steals", 0)),
        int(snapshot.get("route_exact_ordered", 0)),
        int(snapshot.get("route_exact_symmetric", 0)),
        int(snapshot.get("route_target_family", 0)),
        int(snapshot.get("route_source_family", 0)),
        int(snapshot.get("route_global_default", 0)),
        int(snapshot.get("route_drops", 0)),
        int(snapshot.get("no_repeat_avoided", 0)),
        int(snapshot.get("missing_mappings", 0)),
        int(snapshot.get("invalid_events", 0)),
        _last_event,
    ]


func _unhandled_key_input(event: InputEvent) -> void:
    if not (event is InputEventKey):
        return
    var key_event := event as InputEventKey
    if not key_event.pressed or key_event.echo:
        return
    match key_event.keycode:
        KEY_SPACE:
            _reset_all()
        KEY_1:
            _reset_body(0)
        KEY_2:
            _reset_body(1)
        KEY_3:
            _reset_body(2)
        KEY_R:
            _reset_all()


func _build_world() -> void:
    var camera := Camera3D.new()
    camera.name = "Camera3D"
    camera.position = Vector3(0.0, 6.0, 12.0)
    add_child(camera)
    camera.look_at(Vector3(0.0, 1.2, 0.0))

    var light := DirectionalLight3D.new()
    light.name = "DirectionalLight3D"
    light.rotation_degrees = Vector3(-55.0, -25.0, 0.0)
    light.light_energy = 1.2
    light.shadow_enabled = true
    add_child(light)

    var environment_node := WorldEnvironment.new()
    var environment := Environment.new()
    environment.background_mode = Environment.BG_COLOR
    environment.background_color = Color("182333")
    environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.ambient_light_color = Color("9bb4d1")
    environment.ambient_light_energy = 0.55
    environment_node.environment = environment
    add_child(environment_node)

    var definitions := [
        {"id": &"wood", "x": -3.0, "color": Color("b77a45"), "mass": 0.8},
        {"id": &"metal", "x": 0.0, "color": Color("9eb4c5"), "mass": 2.2},
        {"id": &"stone", "x": 3.0, "color": Color("888b91"), "mass": 3.4},
    ]
    for definition in definitions:
        var family_id := definition["id"] as StringName
        var source_id := StringName("%s_prop" % family_id)
        _source_materials[family_id] = TEST_AUDIO.create_material(
            source_id,
            family_id,
            family_id,
        )
    _ground_material = TEST_AUDIO.create_material(
        &"stone_ground",
        &"stone",
        &"stone",
    )
    _create_ground()

    _emitter = EMITTER_SCRIPT.new()
    _emitter.name = "SonicFoleyEmitter3D"
    _emitter.set("voice_limit", 8)
    _emitter.set("impact_route_map", _create_route_map(definitions))
    add_child(_emitter)
    _emitter.connect("impact_played", _on_impact_played)

    for index in definitions.size():
        _create_drop_body(index, definitions[index])


func _create_route_map(definitions: Array) -> SonicImpactRouteMap:
    var route_map := SonicImpactRouteMap.new()
    for definition in definitions:
        var family_id := definition["id"] as StringName
        var source := _source_materials[family_id] as SonicAcousticMaterial
        var route := SonicImpactRoute.new()
        route.route_id = StringName("%s-on-stone" % family_id)
        route.source_material_id = source.stable_id()
        route.target_material_id = _ground_material.stable_id()
        route.output_material = TEST_AUDIO.create_material(
            StringName("%s_on_stone" % family_id),
            family_id,
            family_id,
        )
        route_map.exact_routes.append(route)
    return route_map


func _create_ground() -> void:
    var ground := StaticBody3D.new()
    ground.name = "Ground"
    ground.position = Vector3(0.0, -0.5, 0.0)
    add_child(ground)

    var material_binding := SonicMaterialBinding3D.new()
    material_binding.name = "SonicMaterialBinding3D"
    material_binding.acoustic_material = _ground_material
    ground.add_child(material_binding)

    var collision := CollisionShape3D.new()
    var shape := BoxShape3D.new()
    shape.size = Vector3(12.0, 1.0, 8.0)
    collision.shape = shape
    ground.add_child(collision)

    var mesh_instance := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = shape.size
    mesh_instance.mesh = mesh
    var surface := StandardMaterial3D.new()
    surface.albedo_color = Color("34495e")
    surface.roughness = 0.92
    mesh_instance.material_override = surface
    ground.add_child(mesh_instance)


func _create_drop_body(index: int, definition: Dictionary) -> void:
    var body := RigidBody3D.new()
    body.name = "%sDrop" % String(definition["id"]).capitalize()
    body.mass = float(definition["mass"])
    body.continuous_cd = true
    body.can_sleep = true
    add_child(body)

    var collision := CollisionShape3D.new()
    var shape := BoxShape3D.new()
    shape.size = Vector3(1.25, 1.25, 1.25)
    collision.shape = shape
    body.add_child(collision)

    var mesh_instance := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = shape.size
    mesh_instance.mesh = mesh
    var surface := StandardMaterial3D.new()
    surface.albedo_color = definition["color"] as Color
    surface.metallic = 0.75 if definition["id"] == &"metal" else 0.0
    surface.roughness = 0.35 if definition["id"] == &"metal" else 0.75
    mesh_instance.material_override = surface
    body.add_child(mesh_instance)

    var adapter := IMPACT_ADAPTER_SCRIPT.new()
    adapter.name = "SonicImpactAdapter3D"
    adapter.set("emitter_path", _emitter.get_path())
    adapter.set("acoustic_material", _source_materials[definition["id"]])
    adapter.set("stable_source_id", index + 1)
    adapter.set("base_seed", 0x51A7 + index * 101)
    adapter.set("reference_speed_mps", 8.0)
    body.add_child(adapter)

    _bodies.append(body)
    _initial_positions.append(Vector3(float(definition["x"]), 4.0 + index, 0.0))


func _build_interface() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var panel := PanelContainer.new()
    panel.position = Vector2(24.0, 24.0)
    panel.custom_minimum_size = Vector2(720.0, 184.0)
    layer.add_child(panel)
    _debug_label = Label.new()
    _debug_label.add_theme_font_size_override("font_size", 18)
    panel.add_child(_debug_label)


func _reset_all() -> void:
    for index in _bodies.size():
        _reset_body(index)


func _reset_body(index: int) -> void:
    if index < 0 or index >= _bodies.size():
        return
    var body := _bodies[index]
    body.freeze = true
    body.global_position = _initial_positions[index]
    body.rotation = Vector3(0.15 * index, 0.25 * index, 0.1)
    body.linear_velocity = Vector3.ZERO
    body.angular_velocity = Vector3.ZERO
    body.freeze = false
    body.sleeping = false


func _on_impact_played(details: Dictionary) -> void:
    var voice_index := int(details.get("voice_index", -1))
    var player := _emitter.get_node_or_null("Voice%02d" % voice_index)
    if player is AudioStreamPlayer3D and (player as AudioStreamPlayer3D).playing:
        _voice_started_observed += 1
    else:
        _voice_start_failures += 1
    _last_event = "%s -> %s via %s (%s) variant=%d voice=%d%s" % [
        String(details.get("source_material_id", &"unknown")),
        String(details.get("target_material_id", &"unknown")),
        String(details.get("route_id", &"unknown")),
        String(details.get("route_resolution", &"unknown")),
        int(details.get("variant_index", -1)),
        voice_index,
        " (stole)" if bool(details.get("voice_stolen", false)) else "",
    ]
