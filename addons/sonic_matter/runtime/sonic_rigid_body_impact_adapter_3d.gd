@tool
extends Node

@export var emitter_path: NodePath
@export var acoustic_material: SonicAcousticMaterial
@export_range(0, 1000000, 1) var stable_source_id: int = 1
@export var base_seed: int = 0x51A7
@export_range(0.1, 100.0, 0.1) var reference_speed_mps: float = 8.0
@export_range(0.0, 1.0, 0.01) var minimum_intensity: float = 0.05
@export_range(-100, 100, 1) var priority: int = 0

var _body: RigidBody3D
var _emitter: Node
var _event_sequence: int = 0


func _ready() -> void:
    if Engine.is_editor_hint():
        return

    _body = get_parent() as RigidBody3D
    if _body == null:
        push_error("SonicRigidBodyImpactAdapter3D must be a child of RigidBody3D.")
        set_process(false)
        return

    _emitter = get_node_or_null(emitter_path)
    if _emitter == null or not _emitter.has_method("play_impact"):
        push_error("SonicRigidBodyImpactAdapter3D requires a valid emitter_path.")
        set_process(false)
        return

    _body.contact_monitor = true
    _body.max_contacts_reported = maxi(_body.max_contacts_reported, 4)
    if not _body.body_entered.is_connected(_on_body_entered):
        _body.body_entered.connect(_on_body_entered)


func _exit_tree() -> void:
    if (
        _body != null
        and _body.body_entered.is_connected(_on_body_entered)
    ):
        _body.body_entered.disconnect(_on_body_entered)


func _on_body_entered(_other_body: Node) -> void:
    if acoustic_material == null or _emitter == null:
        return

    var intensity := clampf(
        _body.linear_velocity.length() / maxf(reference_speed_mps, 0.1),
        0.0,
        1.0,
    )
    if intensity < minimum_intensity:
        return

    _event_sequence += 1
    var event_id := stable_source_id * 1000000 + _event_sequence
    var event := SonicFoleyEvent.impact(
        event_id,
        base_seed ^ event_id,
        intensity,
        _body.global_position,
        priority,
        SonicFoleyEvent.Evidence.ESTIMATED,
    )
    _emitter.call("play_impact", acoustic_material, event)

