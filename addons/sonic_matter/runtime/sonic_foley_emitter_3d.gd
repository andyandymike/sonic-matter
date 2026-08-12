@tool
extends Node3D

signal impact_played(details: Dictionary)

@export var impact_route_map: SonicImpactRouteMap
@export_range(1, 8, 1) var voice_limit: int = 8
@export var output_bus: StringName = &"Master"
@export_range(0.1, 100.0, 0.1) var unit_size: float = 4.0
@export_range(0.0, 1000.0, 0.1) var max_distance: float = 40.0

var _selector := SonicSampleSelector.new()
var _allocator := SonicVoiceAllocator.new()
var _players: Array[AudioStreamPlayer3D] = []
var _voice_tokens: Array[int] = []
var _stats: Dictionary = {
    "impact_submissions": 0,
    "invalid_submissions": 0,
    "played": 0,
    "bus_fallbacks": 0,
    "exact_ordered": 0,
    "exact_symmetric": 0,
    "target_family": 0,
    "source_family": 0,
    "global_default": 0,
    "route_drops": 0,
}


func _ready() -> void:
    if Engine.is_editor_hint():
        return
    _build_voice_pool()
    set_process(true)


func _process(_delta: float) -> void:
    for index in _players.size():
        if (
            _allocator.is_active(index)
            and not _players[index].playing
            and _voice_tokens[index] != 0
        ):
            _allocator.release(index, _voice_tokens[index])
            _voice_tokens[index] = 0


func play_impact(
        source_material: SonicAcousticMaterial,
        target_material: SonicAcousticMaterial,
        event: SonicFoleyEvent,
) -> Dictionary:
    if Engine.is_editor_hint():
        return {}
    _stats["impact_submissions"] += 1
    if event == null or not event.is_valid():
        _stats["invalid_submissions"] += 1
        return {}
    if _players.size() != clampi(voice_limit, 1, 8):
        _build_voice_pool()
    if impact_route_map == null:
        _stats["route_drops"] += 1
        return {}

    var route_result := impact_route_map.resolve_impact(
        source_material,
        target_material,
    )
    if not bool(route_result.get("resolved", false)):
        _stats["route_drops"] += 1
        return {}

    var resolution := String(route_result["resolution"])
    _stats[resolution] = int(_stats.get(resolution, 0)) + 1
    var material := route_result["material"] as SonicAcousticMaterial
    var selection := _selector.select_impact(material, event)
    if selection.is_empty():
        return {}

    var allocation := _allocator.allocate(
        event.event_id,
        event.priority,
        int(round(event.normalized_intensity() * 1000.0)),
    )
    var voice_index := int(allocation["index"])
    var voice_token := int(allocation["token"])
    var player := _players[voice_index]
    if player.playing:
        player.stop()

    var effective_bus := output_bus
    if AudioServer.get_bus_index(effective_bus) < 0:
        effective_bus = &"Master"
        _stats["bus_fallbacks"] += 1

    player.stream = selection["stream"] as AudioStream
    player.pitch_scale = float(selection["pitch_scale"])
    player.volume_db = float(selection["volume_db"])
    player.bus = effective_bus
    player.global_position = event.position
    _voice_tokens[voice_index] = voice_token
    player.play()
    if not player.playing:
        _allocator.release(voice_index, voice_token)
        _voice_tokens[voice_index] = 0
        player.stream = null
        return {}
    _stats["played"] += 1

    var details := selection.duplicate(true)
    details["route_id"] = route_result["route_id"]
    details["route_resolution"] = route_result["resolution"]
    details["source_material_id"] = route_result["source_material_id"]
    details["target_material_id"] = route_result["target_material_id"]
    details["voice_index"] = voice_index
    details["voice_token"] = voice_token
    details["voice_stolen"] = bool(allocation["stolen"])
    details["active_voices"] = _allocator.active_count()
    impact_played.emit(details)
    return details


func debug_snapshot() -> Dictionary:
    var snapshot := _selector.stats()
    var sample_submissions := int(snapshot["submitted"])
    var sample_invalid := int(snapshot["invalid_events"])
    var sample_missing := int(snapshot["missing_mappings"])
    snapshot["sample_submissions"] = sample_submissions
    snapshot["submitted"] = int(_stats["impact_submissions"])
    snapshot["invalid_events"] = sample_invalid + int(_stats["invalid_submissions"])
    snapshot["sample_missing_mappings"] = sample_missing
    snapshot["route_drops"] = int(_stats["route_drops"])
    snapshot["missing_mappings"] = sample_missing + int(_stats["route_drops"])
    snapshot["played"] = int(_stats["played"])
    snapshot["bus_fallbacks"] = int(_stats["bus_fallbacks"])
    snapshot["route_exact_ordered"] = int(_stats["exact_ordered"])
    snapshot["route_exact_symmetric"] = int(_stats["exact_symmetric"])
    snapshot["route_target_family"] = int(_stats["target_family"])
    snapshot["route_source_family"] = int(_stats["source_family"])
    snapshot["route_global_default"] = int(_stats["global_default"])
    snapshot["voice_capacity"] = _allocator.capacity()
    snapshot["active_voices"] = _allocator.active_count()
    snapshot["voice_steals"] = _allocator.steal_count()
    return snapshot


func reset_debug_state() -> void:
    for player in _players:
        player.stop()
    _selector.reset()
    _build_voice_pool()
    _allocator.configure(_players.size())
    _voice_tokens.resize(_players.size())
    _voice_tokens.fill(0)
    for key in _stats:
        _stats[key] = 0


func _build_voice_pool() -> void:
    var capacity := clampi(voice_limit, 1, 8)
    if _players.size() == capacity:
        return

    for player in _players:
        player.stop()
        remove_child(player)
        player.queue_free()
    _players.clear()
    _voice_tokens.clear()

    _allocator.configure(capacity)
    for index in capacity:
        var player := AudioStreamPlayer3D.new()
        player.name = "Voice%02d" % index
        player.max_polyphony = 1
        player.unit_size = unit_size
        player.max_distance = max_distance
        player.attenuation_filter_cutoff_hz = 20500.0
        player.top_level = true
        add_child(player)
        _players.append(player)
        _voice_tokens.append(0)
