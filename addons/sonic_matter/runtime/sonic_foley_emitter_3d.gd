@tool
extends Node3D

signal impact_played(details: Dictionary)

@export_range(1, 8, 1) var voice_limit: int = 8
@export var output_bus: StringName = &"Master"
@export_range(0.1, 100.0, 0.1) var unit_size: float = 4.0
@export_range(0.0, 1000.0, 0.1) var max_distance: float = 40.0

var _selector := SonicSampleSelector.new()
var _allocator := SonicVoiceAllocator.new()
var _players: Array[AudioStreamPlayer3D] = []
var _voice_tokens: Array[int] = []
var _stats: Dictionary = {
    "played": 0,
    "bus_fallbacks": 0,
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
        material: SonicAcousticMaterial,
        event: SonicFoleyEvent,
) -> Dictionary:
    if Engine.is_editor_hint():
        return {}
    if _players.is_empty():
        _build_voice_pool()

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
    _stats["played"] += 1

    var details := selection.duplicate(true)
    details["voice_index"] = voice_index
    details["voice_token"] = voice_token
    details["voice_stolen"] = bool(allocation["stolen"])
    details["active_voices"] = _allocator.active_count()
    impact_played.emit(details)
    return details


func debug_snapshot() -> Dictionary:
    var snapshot := _selector.stats()
    snapshot["played"] = int(_stats["played"])
    snapshot["bus_fallbacks"] = int(_stats["bus_fallbacks"])
    snapshot["voice_capacity"] = _allocator.capacity()
    snapshot["active_voices"] = _allocator.active_count()
    snapshot["voice_steals"] = _allocator.steal_count()
    return snapshot


func reset_debug_state() -> void:
    for player in _players:
        player.stop()
    _selector.reset()
    _allocator.configure(clampi(voice_limit, 1, 8))
    _voice_tokens.resize(_players.size())
    _voice_tokens.fill(0)
    for key in _stats:
        _stats[key] = 0


func _build_voice_pool() -> void:
    if not _players.is_empty():
        return
    var capacity := clampi(voice_limit, 1, 8)
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

