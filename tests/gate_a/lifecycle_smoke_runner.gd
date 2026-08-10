extends SceneTree

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")
const GATE_A_DEMO := preload("res://examples/gate_a_3d/gate_a_demo.tscn")

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var fixture := _create_fixture()
    await _test_recreate_reset_pause_and_burst(fixture)
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
