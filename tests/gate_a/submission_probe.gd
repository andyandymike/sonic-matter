extends SceneTree

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var source := TEST_AUDIO.create_material(&"probe_source", &"wood", &"wood")
    var target := TEST_AUDIO.create_material(&"probe_target", &"stone", &"stone")
    var output := TEST_AUDIO.create_material(&"probe_output", &"wood", &"wood")
    var route := SonicImpactRoute.new()
    route.route_id = &"probe-route"
    route.source_material_id = source.stable_id()
    route.target_material_id = target.stable_id()
    route.output_material = output
    var route_map := SonicImpactRouteMap.new()
    route_map.exact_routes.append(route)

    var emitter := EMITTER_SCRIPT.new()
    emitter.impact_route_map = route_map
    emitter.voice_limit = 8
    root.add_child(emitter)
    await process_frame

    for count in [8, 32, 128]:
        emitter.reset_debug_state()
        var started_usec := Time.get_ticks_usec()
        for event_index in count:
            var event := SonicFoleyEvent.impact(
                count * 1000 + event_index,
                0xA000 + event_index,
                0.75,
                Vector3.ZERO,
                event_index % 4,
                SonicFoleyEvent.Evidence.AUTHORED,
                source.stable_id(),
                target.stable_id(),
                SonicFoleyEvent.Evidence.AUTHORED,
            )
            var result := emitter.play_impact(source, target, event)
            if result.is_empty():
                _failures.append(
                    "submission probe dropped event %d/%d" % [event_index, count],
                )
        var elapsed_usec := Time.get_ticks_usec() - started_usec
        var snapshot := emitter.debug_snapshot()
        var record := {
            "scope": "main_thread_submission_not_audio_callback",
            "events": count,
            "elapsed_usec": elapsed_usec,
            "usec_per_event": float(elapsed_usec) / float(count),
            "played": int(snapshot.get("played", 0)),
            "active_voices": int(snapshot.get("active_voices", 0)),
            "voice_steals": int(snapshot.get("voice_steals", 0)),
            "route_drops": int(snapshot.get("route_drops", 0)),
        }
        print("GATE_A_SUBMISSION_METRIC %s" % JSON.stringify(record))
        if int(snapshot.get("played", 0)) != count:
            _failures.append("played count drifted for %d events" % count)
        if int(snapshot.get("active_voices", 0)) > 8:
            _failures.append("voice cap exceeded for %d events" % count)
        if int(snapshot.get("route_drops", 0)) != 0:
            _failures.append("route dropped during %d-event probe" % count)

    emitter.queue_free()
    await process_frame
    if _failures.is_empty():
        print("GATE_A_SUBMISSION_PROBE_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("GATE_A_SUBMISSION_PROBE_FAILED count=%d" % _failures.size())
    quit(1)
