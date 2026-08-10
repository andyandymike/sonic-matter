extends Node3D

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const IMPACT_ADAPTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_rigid_body_impact_adapter_3d.gd")
const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")

var _emitter: Node3D
var _bodies: Array[RigidBody3D] = []
var _initial_positions: Array[Vector3] = []
var _debug_label: Label
var _last_event: String = "waiting for impact"


func _ready() -> void:
    _build_world()
    _build_interface()
    _reset_all()


func _process(_delta: float) -> void:
    if _debug_label == null or _emitter == null:
        return
    var snapshot: Dictionary = _emitter.call("debug_snapshot")
    _debug_label.text = (
        "Space: drop all    1/2/3: drop one    R: reset\n"
        + "Synthetic fixtures only — not production Foley\n"
        + "submitted=%d  selected=%d  played=%d  active=%d/%d  steals=%d\n"
        + "no-repeat=%d  missing=%d  invalid=%d\nlast: %s"
    ) % [
        int(snapshot.get("submitted", 0)),
        int(snapshot.get("selected", 0)),
        int(snapshot.get("played", 0)),
        int(snapshot.get("active_voices", 0)),
        int(snapshot.get("voice_capacity", 0)),
        int(snapshot.get("voice_steals", 0)),
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

    _create_ground()

    _emitter = EMITTER_SCRIPT.new()
    _emitter.name = "SonicFoleyEmitter3D"
    _emitter.set("voice_limit", 8)
    add_child(_emitter)
    _emitter.connect("impact_played", _on_impact_played)

    var definitions := [
        {"id": &"wood", "x": -3.0, "color": Color("b77a45"), "mass": 0.8},
        {"id": &"metal", "x": 0.0, "color": Color("9eb4c5"), "mass": 2.2},
        {"id": &"stone", "x": 3.0, "color": Color("888b91"), "mass": 3.4},
    ]
    for index in definitions.size():
        _create_drop_body(index, definitions[index])


func _create_ground() -> void:
    var ground := StaticBody3D.new()
    ground.name = "Ground"
    ground.position = Vector3(0.0, -0.5, 0.0)
    add_child(ground)

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
    adapter.set("acoustic_material", TEST_AUDIO.create_material(definition["id"]))
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
    panel.custom_minimum_size = Vector2(620.0, 152.0)
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
    _last_event = "%s variant=%d voice=%d%s" % [
        String(details.get("material_id", &"unknown")),
        int(details.get("variant_index", -1)),
        int(details.get("voice_index", -1)),
        " (stole)" if bool(details.get("voice_stolen", false)) else "",
    ]

