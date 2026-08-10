extends SceneTree

const GateADemo = preload("res://examples/gate_a_3d/gate_a_demo.tscn")


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var demo := GateADemo.instantiate()
    root.add_child(demo)
    await create_timer(4.0).timeout

    var emitter := demo.get_node_or_null("SonicFoleyEmitter3D")
    if emitter == null or not emitter.has_method("debug_snapshot"):
        push_error("GATE_A_SCENE_SMOKE_FAILED missing emitter")
        quit(1)
        return

    var snapshot: Dictionary = emitter.call("debug_snapshot")
    print("GATE_A_SCENE_SNAPSHOT %s" % JSON.stringify(snapshot))
    var capacity := int(snapshot.get("voice_capacity", 0))
    var active := int(snapshot.get("active_voices", 0))
    var passed := (
        int(snapshot.get("submitted", 0)) >= 3
        and int(snapshot.get("selected", 0)) >= 3
        and int(snapshot.get("played", 0)) >= 3
        and int(snapshot.get("invalid_events", 0)) == 0
        and int(snapshot.get("missing_mappings", 0)) == 0
        and int(snapshot.get("route_exact_ordered", 0)) >= 3
        and int(snapshot.get("route_drops", 0)) == 0
        and capacity == 8
        and active >= 0
        and active <= capacity
    )

    demo.queue_free()
    await process_frame
    if not passed:
        push_error("GATE_A_SCENE_SMOKE_FAILED unexpected snapshot")
        quit(1)
        return

    print("GATE_A_SCENE_SMOKE_OK")
    quit(0)
