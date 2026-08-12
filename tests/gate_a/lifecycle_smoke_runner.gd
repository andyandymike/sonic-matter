extends SceneTree

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const IMPACT_ADAPTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_rigid_body_impact_adapter_3d.gd")
const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")
const GATE_A_DEMO := preload("res://examples/gate_a_3d/gate_a_demo.tscn")

var _failures: Array[String] = []


class RecordingImpactEmitter:
    extends Node

    var calls: Array[Dictionary] = []

    func play_impact(
            source_material: SonicAcousticMaterial,
            target_material: SonicAcousticMaterial,
            event: SonicFoleyEvent,
    ) -> Dictionary:
        calls.append({
            "source_material": source_material,
            "target_material": target_material,
            "event": event,
        })
        return {"accepted": true}


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var fixture := _create_fixture()
    await _test_recreate_reset_pause_and_burst(fixture)
    await _test_voice_limit_reconfiguration(fixture)
    await _test_relative_speed_for_canonical_reporter()
    await _test_missing_route_is_observable(fixture)
    await _test_scene_transition()

    if _failures.is_empty():
        print("GATE_A_LIFECYCLE_OK")
        quit(0)
        return

    for failure in _failures:
        push_error(failure)
    push_error("GATE_A_LIFECYCLE_FAILED count=%d" % _failures.size())
    quit(1)


func _test_scene_transition() -> void:
    for cycle in 2:
        var demo := GATE_A_DEMO.instantiate()
        root.add_child(demo)
        await process_frame
        await process_frame

        var emitter := demo.get_node_or_null("SonicFoleyEmitter3D")
        _expect(
            emitter != null and emitter.has_method("debug_snapshot"),
            "scene transition cycle %d did not create the emitter" % cycle,
        )

        demo.queue_free()
        await process_frame
        _expect(
            not is_instance_valid(demo),
            "scene transition cycle %d did not free the demo" % cycle,
        )


func _test_recreate_reset_pause_and_burst(fixture: Dictionary) -> void:
    for cycle in 3:
        var emitter := EMITTER_SCRIPT.new()
        emitter.name = "LifecycleEmitter%d" % cycle
        emitter.set("impact_route_map", fixture["route_map"])
        emitter.set("voice_limit", 8)
        root.add_child(emitter)
        await process_frame

        paused = true
        paused = false
        for event_index in 32:
            var event := SonicFoleyEvent.impact(
                cycle * 1000 + event_index,
                0x7000 + event_index,
                0.8,
                Vector3(float(event_index), 0.0, 0.0),
                event_index % 3,
                SonicFoleyEvent.Evidence.AUTHORED,
                fixture["source"].stable_id(),
                fixture["target"].stable_id(),
                SonicFoleyEvent.Evidence.AUTHORED,
            )
            var details: Dictionary = emitter.call(
                "play_impact",
                fixture["source"],
                fixture["target"],
                event,
            )
            _expect(
                not details.is_empty(),
                "lifecycle cycle %d dropped burst event %d" % [cycle, event_index],
            )

        var snapshot: Dictionary = emitter.call("debug_snapshot")
        _expect(
            int(snapshot.get("played", 0)) == 32,
            "lifecycle cycle %d played counter drifted" % cycle,
        )
        _expect(
            int(snapshot.get("route_exact_ordered", 0)) == 32,
            "lifecycle cycle %d route counter drifted" % cycle,
        )
        _expect(
            int(snapshot.get("route_drops", 0)) == 0,
            "lifecycle cycle %d unexpectedly dropped a route" % cycle,
        )
        _expect(
            int(snapshot.get("voice_capacity", 0)) == 8,
            "lifecycle cycle %d changed voice capacity" % cycle,
        )
        _expect(
            int(snapshot.get("active_voices", 0)) <= 8,
            "lifecycle cycle %d exceeded voice capacity" % cycle,
        )

        emitter.call("reset_debug_state")
        var reset_snapshot: Dictionary = emitter.call("debug_snapshot")
        _expect(
            int(reset_snapshot.get("played", -1)) == 0,
            "lifecycle cycle %d did not reset played state" % cycle,
        )
        _expect(
            int(reset_snapshot.get("active_voices", -1)) == 0,
            "lifecycle cycle %d left voices active after reset" % cycle,
        )

        emitter.queue_free()
        await process_frame
        _expect(
            not is_instance_valid(emitter),
            "lifecycle cycle %d did not free the emitter" % cycle,
        )


func _test_missing_route_is_observable(fixture: Dictionary) -> void:
    var emitter := EMITTER_SCRIPT.new()
    emitter.name = "MissingRouteEmitter"
    root.add_child(emitter)
    await process_frame

    var event := SonicFoleyEvent.impact(
        9000,
        9000,
        0.5,
        Vector3.ZERO,
    )
    var details: Dictionary = emitter.call(
        "play_impact",
        fixture["source"],
        fixture["target"],
        event,
    )
    var invalid_details: Dictionary = emitter.call(
        "play_impact",
        fixture["source"],
        fixture["target"],
        SonicFoleyEvent.new(),
    )
    var snapshot: Dictionary = emitter.call("debug_snapshot")
    _expect(invalid_details.is_empty(), "invalid event should fail closed")
    _expect(
        int(snapshot.get("submitted", 0)) == 2,
        "emitter did not count every submission",
    )
    _expect(
        int(snapshot.get("invalid_events", 0)) == 1,
        "emitter did not count the early invalid event",
    )
    _expect(details.is_empty(), "missing route map should fail closed")
    _expect(
        int(snapshot.get("route_drops", 0)) == 1,
        "missing route map did not increment route_drops",
    )
    _expect(
        int(snapshot.get("active_voices", 0)) == 0,
        "missing route map allocated a voice",
    )

    emitter.queue_free()
    await process_frame


func _test_voice_limit_reconfiguration(fixture: Dictionary) -> void:
    var emitter := EMITTER_SCRIPT.new()
    emitter.name = "VoiceLimitEmitter"
    emitter.set("impact_route_map", fixture["route_map"])
    emitter.set("voice_limit", 2)
    root.add_child(emitter)
    await process_frame
    _expect(
        int(emitter.call("debug_snapshot").get("voice_capacity", 0)) == 2,
        "initial voice capacity did not use voice_limit=2",
    )

    emitter.set("voice_limit", 4)
    for event_index in 4:
        var details: Dictionary = emitter.call(
            "play_impact",
            fixture["source"],
            fixture["target"],
            SonicFoleyEvent.impact(
                12000 + event_index,
                13000 + event_index,
                0.8,
                Vector3.ZERO,
            ),
        )
        _expect(
            not details.is_empty()
            and int(details.get("voice_index", -1)) < 4,
            "voice-limit growth dropped or indexed event %d out of range"
            % event_index,
        )
    var grown_snapshot: Dictionary = emitter.call("debug_snapshot")
    _expect(
        int(grown_snapshot.get("voice_capacity", 0)) == 4,
        "voice-limit growth did not rebuild the player pool",
    )
    _expect(
        int(grown_snapshot.get("active_voices", 0)) == 4,
        "voice-limit growth did not expose four usable voices",
    )

    emitter.set("voice_limit", 1)
    emitter.call("reset_debug_state")
    var shrunk_snapshot: Dictionary = emitter.call("debug_snapshot")
    _expect(
        int(shrunk_snapshot.get("voice_capacity", 0)) == 1,
        "voice-limit shrink did not rebuild the player pool",
    )
    _expect(
        int(shrunk_snapshot.get("active_voices", -1)) == 0,
        "voice-limit shrink left an active allocation",
    )
    emitter.queue_free()
    await process_frame


func _test_relative_speed_for_canonical_reporter() -> void:
    var recording_emitter := RecordingImpactEmitter.new()
    recording_emitter.name = "RecordingImpactEmitter"
    root.add_child(recording_emitter)

    var stationary_body := RigidBody3D.new()
    stationary_body.name = "StationaryCanonicalBody"
    var stationary_adapter := IMPACT_ADAPTER_SCRIPT.new()
    stationary_adapter.name = "StationaryAdapter"
    stationary_adapter.emitter_path = recording_emitter.get_path()
    stationary_adapter.acoustic_material = TEST_AUDIO.create_material(
        &"stationary_source",
        &"wood",
        &"wood",
    )
    stationary_adapter.stable_source_id = 1
    stationary_adapter.reference_speed_mps = 10.0
    stationary_adapter.minimum_intensity = 0.05
    stationary_body.add_child(stationary_adapter)

    var fast_body := RigidBody3D.new()
    fast_body.name = "FastOtherBody"
    var fast_adapter := IMPACT_ADAPTER_SCRIPT.new()
    fast_adapter.name = "FastAdapter"
    fast_adapter.emitter_path = recording_emitter.get_path()
    fast_adapter.acoustic_material = TEST_AUDIO.create_material(
        &"fast_target",
        &"metal",
        &"metal",
    )
    fast_adapter.stable_source_id = 2
    fast_body.add_child(fast_adapter)

    root.add_child(stationary_body)
    root.add_child(fast_body)
    await process_frame
    stationary_body.linear_velocity = Vector3.ZERO
    fast_body.linear_velocity = Vector3(10.0, 0.0, 0.0)
    stationary_adapter.call("_on_body_entered", fast_body)

    _expect(
        recording_emitter.calls.size() == 1,
        "stationary canonical reporter swallowed a high-relative-speed impact",
    )
    if recording_emitter.calls.size() == 1:
        var event := recording_emitter.calls[0]["event"] as SonicFoleyEvent
        _expect(
            is_equal_approx(event.intensity, 1.0),
            "canonical reporter did not derive intensity from relative speed",
        )
    fast_adapter.call("_on_body_entered", stationary_body)
    _expect(
        recording_emitter.calls.size() == 1,
        "two adapters emitted duplicate canonical reports",
    )

    stationary_adapter.reference_speed_mps = NAN
    stationary_adapter.call("_on_body_entered", fast_body)
    _expect(
        recording_emitter.calls.size() == 1,
        "non-finite reference speed did not fail closed",
    )
    stationary_adapter.reference_speed_mps = 10.0
    stationary_adapter.minimum_intensity = NAN
    stationary_adapter.call("_on_body_entered", fast_body)
    _expect(
        recording_emitter.calls.size() == 1,
        "non-finite minimum intensity did not fail closed",
    )

    stationary_body.queue_free()
    fast_body.queue_free()
    recording_emitter.queue_free()
    await process_frame


func _create_fixture() -> Dictionary:
    var source := TEST_AUDIO.create_material(&"lifecycle_source", &"wood", &"wood")
    var target := TEST_AUDIO.create_material(&"lifecycle_target", &"stone", &"stone")
    var output := TEST_AUDIO.create_material(&"lifecycle_output", &"wood", &"wood")
    var route := SonicImpactRoute.new()
    route.route_id = &"lifecycle-route"
    route.source_material_id = source.stable_id()
    route.target_material_id = target.stable_id()
    route.output_material = output
    var route_map := SonicImpactRouteMap.new()
    route_map.exact_routes.append(route)
    return {
        "source": source,
        "target": target,
        "route_map": route_map,
    }


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
