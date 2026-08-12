extends SceneTree

const GeneratedTestAudio = preload("res://examples/gate_a_3d/generated_test_audio.gd")
const EmitterScript = preload(
    "res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd"
)
const SELECTOR_GOLDEN := "res://tests/runtime_v2/golden/gate_a_selector_v1.json"
const ALLOCATOR_GOLDEN := "res://tests/runtime_v2/golden/gate_a_allocator_v1.json"
const END_TO_END_GOLDEN := "res://tests/runtime_v2/golden/gate_a_end_to_end_v1.json"

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var selector_golden := _load_golden(SELECTOR_GOLDEN)
    var allocator_golden := _load_golden(ALLOCATOR_GOLDEN)
    var end_to_end_golden := _load_golden(END_TO_END_GOLDEN)
    _verify_metadata(selector_golden, "gate_a_selector_v1")
    _verify_metadata(allocator_golden, "gate_a_allocator_v1")
    _verify_metadata(end_to_end_golden, "gate_a_end_to_end_v1")
    _test_selector(selector_golden.get("selector", {}))
    _test_allocator(allocator_golden.get("allocator", {}))
    await _test_end_to_end(end_to_end_golden.get("end_to_end", {}))

    if _failures.is_empty():
        print("RUNTIME_V2_COMPAT_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("RUNTIME_V2_COMPAT_FAILED count=%d" % _failures.size())
    quit(1)


func _load_golden(path: String) -> Dictionary:
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        _failures.append("missing golden: %s" % path)
        return {}
    var parsed = JSON.parse_string(file.get_as_text())
    if not parsed is Dictionary:
        _failures.append("invalid golden JSON: %s" % path)
        return {}
    return parsed as Dictionary


func _verify_metadata(golden: Dictionary, expected_kind: String) -> void:
    _expect(int(golden.get("schema_version", 0)) == 1, "%s schema drifted" % expected_kind)
    _expect(golden.get("golden_kind") == expected_kind, "%s kind drifted" % expected_kind)
    _expect(
        golden.get("oracle_version") == "gate_a_legacy_v1",
        "%s oracle version drifted" % expected_kind,
    )
    var float_encoding: Dictionary = golden.get("float_encoding", {})
    _expect(
        float_encoding.get("sanity_1_0") == "000000000000f03f",
        "%s float encoding drifted" % expected_kind,
    )
    var captured_from: Dictionary = golden.get("captured_from", {})
    _expect(
        captured_from.get("commit") == "52a25dc5c7cef4ab0136563b55d9d434afadbd86",
        "%s provenance commit drifted" % expected_kind,
    )


func _test_selector(data: Dictionary) -> void:
    var primary_material := _material_from_description(data.get("primary_material", {}))
    var selector := SonicSampleSelector.new()
    _replay_selector_trace(
        selector,
        primary_material,
        data.get("primary_trace", []),
        "selector.primary",
    )
    _expect_canonical(selector.stats(), data.get("primary_stats", {}), "selector.primary.stats")

    selector.reset()
    _replay_selector_trace(
        selector,
        primary_material,
        data.get("reset_replay_trace", []),
        "selector.reset_replay",
    )
    _expect_canonical(
        selector.stats(),
        data.get("reset_replay_stats", {}),
        "selector.reset_replay.stats",
    )

    var edge_selector := SonicSampleSelector.new()
    var invalid_event := SonicFoleyEvent.new()
    var empty_material := SonicAcousticMaterial.new()
    empty_material.material_id = &"empty"
    var edge_cases: Array = data.get("edge_cases", [])
    var edge_actual: Array[Dictionary] = []
    edge_actual.append(_legacy_selection(edge_selector.select_impact(null, invalid_event), null))
    edge_actual.append(
        _legacy_selection(edge_selector.select_impact(empty_material, invalid_event), empty_material)
    )
    edge_actual.append(
        _legacy_selection(
            edge_selector.select_impact(empty_material, _impact_event(1, 1, 0.65)),
            empty_material,
        )
    )
    var zero_weight := GeneratedTestAudio.create_material(&"zero_weight")
    for variant in zero_weight.impact_variants:
        variant.weight = 0.0
    edge_actual.append(
        _legacy_selection(
            edge_selector.select_impact(zero_weight, _impact_event(2, 2, 0.65)),
            zero_weight,
        )
    )
    var non_finite := GeneratedTestAudio.create_material(&"non_finite")
    for variant in non_finite.impact_variants:
        variant.weight = INF
    edge_actual.append(
        _legacy_selection(
            edge_selector.select_impact(non_finite, _impact_event(3, 3, 0.65)),
            non_finite,
        )
    )
    _expect(edge_cases.size() == edge_actual.size(), "selector.edge case count drifted")
    for index in mini(edge_cases.size(), edge_actual.size()):
        _expect_canonical(
            edge_actual[index],
            edge_cases[index].get("legacy_observation", {}),
            "selector.edge.%d" % index,
        )
    _expect_canonical(edge_selector.stats(), data.get("edge_stats", {}), "selector.edge.stats")

    _replay_named_selector_case(
        data,
        "non_contiguous_material",
        "non_contiguous_trace",
        "non_contiguous_stats",
        "selector.non_contiguous",
    )
    _replay_named_selector_case(
        data,
        "single_material",
        "single_trace",
        "single_stats",
        "selector.single",
    )
    _replay_named_selector_case(
        data,
        "default_id_material",
        "default_id_trace",
        "default_id_stats",
        "selector.default_id",
    )


func _replay_named_selector_case(
        data: Dictionary,
        material_key: String,
        trace_key: String,
        stats_key: String,
        label: String,
) -> void:
    var material := _material_from_description(data.get(material_key, {}))
    var selector := SonicSampleSelector.new()
    _replay_selector_trace(selector, material, data.get(trace_key, []), label)
    _expect_canonical(selector.stats(), data.get(stats_key, {}), "%s.stats" % label)


func _replay_selector_trace(
        selector: SonicSampleSelector,
        material: SonicAcousticMaterial,
        trace: Array,
        label: String,
) -> void:
    for index in trace.size():
        var step: Dictionary = trace[index]
        var input: Dictionary = step.get("input", {})
        var event := _impact_event(
            int(input.get("event_id", -1)),
            int(input.get("seed", 0)),
            _float64_from_hex_le(String(input.get("intensity_bits", ""))),
        )
        var selection := selector.select_impact(material, event)
        _expect_canonical(
            _legacy_selection(selection, material),
            step.get("legacy_observation", {}),
            "%s.%d" % [label, index],
        )


func _material_from_description(description: Dictionary) -> SonicAcousticMaterial:
    var material_id := StringName(String(description.get("material_id", "default")))
    var family_id := StringName(String(description.get("family_id", material_id)))
    var material := GeneratedTestAudio.create_material(material_id, family_id, &"wood")
    material.impact_gain_db = Vector2(
        _float64_from_hex_le(String(description.get("impact_gain_db_x_bits", ""))),
        _float64_from_hex_le(String(description.get("impact_gain_db_y_bits", ""))),
    )
    material.gain_variation_db = _float64_from_hex_le(
        String(description.get("gain_variation_db_bits", ""))
    )
    material.pitch_variation = _float64_from_hex_le(
        String(description.get("pitch_variation_bits", ""))
    )
    var variants: Array = description.get("variants", [])
    for index in mini(variants.size(), material.impact_variants.size()):
        var variant_description: Dictionary = variants[index]
        var weight_bits := String(variant_description.get("weight_bits", ""))
        material.impact_variants[index].weight = (
            INF if weight_bits == "non_finite" else _float64_from_hex_le(weight_bits)
        )
        material.impact_variants[index].gain_db = _float64_from_hex_le(
            String(variant_description.get("gain_db_bits", ""))
        )
        material.impact_variants[index].pitch_scale = _float64_from_hex_le(
            String(variant_description.get("pitch_scale_bits", ""))
        )
    return material


func _legacy_selection(
        selection: Dictionary,
        material: SonicAcousticMaterial,
) -> Dictionary:
    var keys: Array[String] = []
    for key in selection.keys():
        keys.append(String(key))
    keys.sort()
    if selection.is_empty():
        return {"empty": true, "return_keys": keys}
    var stream_slot := -1
    if material != null:
        for index in material.impact_variants.size():
            if selection.get("stream") == material.impact_variants[index].stream:
                stream_slot = index
                break
    return {
        "empty": false,
        "return_keys": keys,
        "event_id": int(selection["event_id"]),
        "material_id": String(selection["material_id"]),
        "variant_index": int(selection["variant_index"]),
        "stream_slot": stream_slot,
        "pitch_scale_bits": _float64_hex_le(float(selection["pitch_scale"])),
        "volume_db_bits": _float64_hex_le(float(selection["volume_db"])),
    }


func _test_allocator(data: Dictionary) -> void:
    var allocator := SonicVoiceAllocator.new()
    allocator.configure(int(data.get("configured_capacity", 0)))
    var inputs: Array = data.get("operation_inputs", [])
    var outputs: Array = data.get("operations", [])
    var decisions: Dictionary = {}
    _expect(inputs.size() == outputs.size(), "allocator trace count drifted")
    for index in mini(inputs.size(), outputs.size()):
        var input: Dictionary = inputs[index]
        var label := String(input.get("operation", ""))
        var actual: Dictionary
        if label.begins_with("allocate_"):
            var decision := allocator.allocate(
                int(input.get("event_id", -1)),
                int(input.get("priority", 0)),
                int(input.get("importance", 0)),
            )
            decisions[label] = decision.duplicate(true)
            actual = _allocator_operation(label, decision, allocator)
        else:
            var source_label := String(input.get("index_from", ""))
            var source: Dictionary = decisions.get(source_label, {})
            actual = {
                "operation": label,
                "result": allocator.release(
                    int(source.get("index", -1)),
                    int(source.get("token", -1)),
                ),
                "active_count": allocator.active_count(),
                "steal_count": allocator.steal_count(),
            }
        _expect_canonical(actual, outputs[index], "allocator.%s" % label)

    allocator.configure(int(data.get("clamp_input_capacity", 99)))
    _expect_canonical(
        {
            "capacity": allocator.capacity(),
            "active_count": allocator.active_count(),
            "steal_count": allocator.steal_count(),
        },
        data.get("clamp_99", {}),
        "allocator.clamp",
    )
    var implicit := SonicVoiceAllocator.new()
    var implicit_input: Dictionary = data.get("implicit_configure_input", {})
    var implicit_decision := implicit.allocate(
        int(implicit_input.get("event_id", -1)),
        int(implicit_input.get("priority", 0)),
        int(implicit_input.get("importance", 0)),
    )
    _expect_canonical(
        _allocator_operation("allocate_without_configure", implicit_decision, implicit),
        data.get("implicit_configure", {}),
        "allocator.implicit",
    )


func _allocator_operation(
        label: String,
        decision: Dictionary,
        allocator: SonicVoiceAllocator,
) -> Dictionary:
    return {
        "operation": label,
        "decision": decision.duplicate(true),
        "active_count": allocator.active_count(),
        "capacity": allocator.capacity(),
        "steal_count": allocator.steal_count(),
    }


func _test_end_to_end(data: Dictionary) -> void:
    var source := GeneratedTestAudio.create_material(
        StringName(String(data.get("source_material_id", "wood_prop"))),
        &"wood",
        &"wood",
    )
    var target := GeneratedTestAudio.create_material(
        StringName(String(data.get("target_material_id", "stone_floor"))),
        &"stone",
        &"stone",
    )
    var output := _material_from_description(data.get("output_material", {}))
    var route := SonicImpactRoute.new()
    route.route_id = StringName(String(data.get("route_id", "wood-on-stone")))
    route.source_material_id = source.stable_id()
    route.target_material_id = target.stable_id()
    route.output_material = output
    var route_map := SonicImpactRouteMap.new()
    route_map.exact_routes.append(route)

    var emitter = EmitterScript.new()
    emitter.name = "RuntimeV2CompatEmitter"
    emitter.voice_limit = int(data.get("voice_limit", 2))
    emitter.impact_route_map = route_map
    root.add_child(emitter)
    await process_frame

    var trace: Array = data.get("trace", [])
    for index in trace.size():
        var step: Dictionary = trace[index]
        var input: Dictionary = step.get("input", {})
        var event := _impact_event(
            int(input.get("event_id", -1)),
            int(input.get("seed", 0)),
            _float64_from_hex_le(String(input.get("intensity_bits", ""))),
        )
        event.priority = int(input.get("priority", 0))
        var details: Dictionary = emitter.play_impact(source, target, event)
        _expect_canonical(
            _legacy_emitter_details(details, output),
            step.get("legacy_observation", {}),
            "end_to_end.details.%d" % index,
        )
        _expect_canonical(
            emitter.debug_snapshot(),
            step.get("snapshot", {}),
            "end_to_end.snapshot.%d" % index,
        )

    _expect_canonical(
        emitter.debug_snapshot(),
        data.get("snapshot_before_reset", {}),
        "end_to_end.before_reset",
    )
    emitter.reset_debug_state()
    _expect_canonical(
        emitter.debug_snapshot(),
        data.get("snapshot_after_reset", {}),
        "end_to_end.after_reset",
    )
    emitter.queue_free()
    await process_frame


func _legacy_emitter_details(
        details: Dictionary,
        output_material: SonicAcousticMaterial,
) -> Dictionary:
    var keys: Array[String] = []
    for key in details.keys():
        keys.append(String(key))
    keys.sort()
    if details.is_empty():
        return {"empty": true, "return_keys": keys}
    var stream_slot := -1
    for index in output_material.impact_variants.size():
        if details.get("stream") == output_material.impact_variants[index].stream:
            stream_slot = index
            break
    return {
        "empty": false,
        "return_keys": keys,
        "event_id": int(details["event_id"]),
        "material_id": String(details["material_id"]),
        "variant_index": int(details["variant_index"]),
        "stream_slot": stream_slot,
        "pitch_scale_bits": _float64_hex_le(float(details["pitch_scale"])),
        "volume_db_bits": _float64_hex_le(float(details["volume_db"])),
        "route_id": String(details["route_id"]),
        "route_resolution": String(details["route_resolution"]),
        "source_material_id": String(details["source_material_id"]),
        "target_material_id": String(details["target_material_id"]),
        "voice_index": int(details["voice_index"]),
        "voice_token": int(details["voice_token"]),
        "voice_stolen": bool(details["voice_stolen"]),
        "active_voices": int(details["active_voices"]),
    }


func _impact_event(event_id: int, seed: int, intensity: float) -> SonicFoleyEvent:
    return SonicFoleyEvent.impact(
        event_id,
        seed,
        intensity,
        Vector3.ZERO,
        0,
        SonicFoleyEvent.Evidence.ESTIMATED,
    )


func _float64_hex_le(value: float) -> String:
    return PackedFloat64Array([value]).to_byte_array().hex_encode()


func _float64_from_hex_le(value: String) -> float:
    if value.length() != 16:
        _failures.append("invalid binary64 hex: %s" % value)
        return 0.0
    var bytes := PackedByteArray()
    bytes.resize(8)
    for index in 8:
        bytes[index] = value.substr(index * 2, 2).hex_to_int()
    return bytes.decode_double(0)


func _expect_canonical(actual: Variant, expected: Variant, label: String) -> void:
    var actual_text := JSON.stringify(_normalize_json_numbers(actual), "", true, true)
    var expected_text := JSON.stringify(_normalize_json_numbers(expected), "", true, true)
    _expect(
        actual_text == expected_text,
        "%s drifted\nexpected=%s\nactual=%s" % [label, expected_text, actual_text],
    )



func _normalize_json_numbers(value: Variant) -> Variant:
    match typeof(value):
        TYPE_INT, TYPE_FLOAT:
            return float(value)
        TYPE_DICTIONARY:
            var normalized_dictionary: Dictionary = {}
            var dictionary: Dictionary = value
            for key in dictionary:
                normalized_dictionary[String(key)] = _normalize_json_numbers(dictionary[key])
            return normalized_dictionary
        TYPE_ARRAY:
            var normalized_array: Array = []
            var array: Array = value
            for item in array:
                normalized_array.append(_normalize_json_numbers(item))
            return normalized_array
        _:
            return value

func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
