extends SceneTree

const GeneratedTestAudio = preload("res://examples/gate_a_3d/generated_test_audio.gd")

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    _test_deterministic_trace()
    _test_no_adjacent_repeat()
    _test_invalid_and_missing_inputs()
    _test_pair_resolution_order()
    _test_pair_resolution_fail_closed()
    _test_voice_budget_and_stale_release()
    _test_generated_audio_fixture()

    if _failures.is_empty():
        print("GATE_A_TESTS_OK")
        quit(0)
        return

    for failure in _failures:
        push_error(failure)
    push_error("GATE_A_TESTS_FAILED count=%d" % _failures.size())
    quit(1)


func _test_deterministic_trace() -> void:
    var material := GeneratedTestAudio.create_material(&"wood")
    var first_selector := SonicSampleSelector.new()
    var second_selector := SonicSampleSelector.new()

    for event_index in 64:
        var event := _impact_event(event_index, 1000 + event_index * 37)
        var first := first_selector.select_impact(material, event)
        var second := second_selector.select_impact(material, event)
        _expect(not first.is_empty(), "deterministic trace produced no selection")
        _expect(
            first.get("variant_index") == second.get("variant_index"),
            "same trace selected different variants at event %d" % event_index,
        )
        _expect(
            is_equal_approx(
                float(first.get("pitch_scale", 0.0)),
                float(second.get("pitch_scale", 1.0)),
            ),
            "same trace produced different pitch at event %d" % event_index,
        )
        _expect(
            is_equal_approx(
                float(first.get("volume_db", 0.0)),
                float(second.get("volume_db", 1.0)),
            ),
            "same trace produced different gain at event %d" % event_index,
        )


func _test_no_adjacent_repeat() -> void:
    var material := GeneratedTestAudio.create_material(&"metal")
    var selector := SonicSampleSelector.new()
    var previous_index := -1

    for event_index in 128:
        var selection := selector.select_impact(
            material,
            _impact_event(500 + event_index, 9000 + event_index),
        )
        var selected_index := int(selection.get("variant_index", -1))
        _expect(selected_index >= 0, "no-repeat trace produced no selection")
        if previous_index >= 0:
            _expect(
                selected_index != previous_index,
                "adjacent repeat at event %d" % event_index,
            )
        previous_index = selected_index

    var stats := selector.stats()
    _expect(int(stats["selected"]) == 128, "selector selected counter drifted")
    _expect(
        int(stats["no_repeat_avoided"]) == 127,
        "no-repeat counter should record every event after the first",
    )


func _test_invalid_and_missing_inputs() -> void:
    var selector := SonicSampleSelector.new()
    var invalid_event := SonicFoleyEvent.new()
    var empty_material := SonicAcousticMaterial.new()
    empty_material.material_id = &"empty"

    _expect(
        selector.select_impact(null, invalid_event).is_empty(),
        "null material should fail closed",
    )
    _expect(
        selector.select_impact(empty_material, invalid_event).is_empty(),
        "invalid event should fail closed",
    )
    _expect(
        selector.select_impact(empty_material, _impact_event(1, 1)).is_empty(),
        "unmapped material should fail closed",
    )
    _test_non_finite_audio_parameters()
    _test_zero_weight_and_stats(selector)


func _test_non_finite_audio_parameters() -> void:
    var selector := SonicSampleSelector.new()
    var invalid_variant_gain := GeneratedTestAudio.create_material(
        &"invalid_variant_gain",
    )
    for variant in invalid_variant_gain.impact_variants:
        variant.gain_db = NAN
    _expect(
        selector.select_impact(
            invalid_variant_gain,
            _impact_event(2, 2),
        ).is_empty(),
        "non-finite variant gain should fail closed",
    )

    var invalid_variant_pitch := GeneratedTestAudio.create_material(
        &"invalid_variant_pitch",
    )
    for variant in invalid_variant_pitch.impact_variants:
        variant.pitch_scale = INF
    _expect(
        selector.select_impact(
            invalid_variant_pitch,
            _impact_event(3, 3),
        ).is_empty(),
        "non-finite variant pitch should fail closed",
    )

    var invalid_material := GeneratedTestAudio.create_material(&"invalid_material")
    invalid_material.pitch_variation = NAN
    _expect(
        selector.select_impact(
            invalid_material,
            _impact_event(4, 4),
        ).is_empty(),
        "non-finite material variation should fail closed",
    )

    var invalid_gain_variation := GeneratedTestAudio.create_material(
        &"invalid_gain_variation",
    )
    invalid_gain_variation.gain_variation_db = INF
    _expect(
        selector.select_impact(
            invalid_gain_variation,
            _impact_event(5, 5),
        ).is_empty(),
        "non-finite gain variation should fail closed",
    )

    var invalid_gain_range := GeneratedTestAudio.create_material(
        &"invalid_gain_range",
    )
    invalid_gain_range.impact_gain_db = Vector2(NAN, -3.0)
    _expect(
        selector.select_impact(
            invalid_gain_range,
            _impact_event(6, 6),
        ).is_empty(),
        "non-finite impact gain range should fail closed",
    )

    var finite_out_of_inspector_range := GeneratedTestAudio.create_material(
        &"finite_out_of_inspector_range",
    )
    finite_out_of_inspector_range.pitch_variation = 0.75
    finite_out_of_inspector_range.gain_variation_db = 18.0
    for variant in finite_out_of_inspector_range.impact_variants:
        variant.pitch_scale = -1.0
    var finite_selection := selector.select_impact(
        finite_out_of_inspector_range,
        _impact_event(7, 7),
    )
    _expect(
        not finite_selection.is_empty()
        and float(finite_selection.get("pitch_scale", 0.0)) == 0.25,
        "finite legacy values outside Inspector hints should remain clamped-compatible",
    )

    var overflow_material := GeneratedTestAudio.create_material(
        &"finite_overflow_material",
    )
    overflow_material.impact_gain_db = Vector2(-1.0e308, 1.0e308)
    var overflow_event := _impact_event(8, 8)
    var stats_before := selector.stats()
    _expect(
        selector.select_impact(overflow_material, overflow_event).is_empty(),
        "finite inputs that overflow output gain should fail closed",
    )
    var stats_after := selector.stats()
    _expect(
        int(stats_after["selected"]) == int(stats_before["selected"])
        and int(stats_after["no_repeat_avoided"])
        == int(stats_before["no_repeat_avoided"]),
        "overflow failure advanced selection history or success counters",
    )
    overflow_material.impact_gain_db = Vector2(-18.0, -3.0)
    var recovered := selector.select_impact(overflow_material, overflow_event)
    var fresh := SonicSampleSelector.new().select_impact(
        overflow_material,
        overflow_event,
    )
    _expect(
        not recovered.is_empty()
        and recovered.get("variant_index") == fresh.get("variant_index"),
        "overflow failure polluted no-repeat history",
    )


func _test_pair_resolution_order() -> void:
    var wood_source := GeneratedTestAudio.create_material(
        &"wood_prop",
        &"wood",
        &"wood",
    )
    var stone_target := GeneratedTestAudio.create_material(
        &"stone_floor",
        &"stone",
        &"stone",
    )
    var metal_target := GeneratedTestAudio.create_material(
        &"metal_plate",
        &"metal",
        &"metal",
    )
    var glass_source := GeneratedTestAudio.create_material(
        &"glass_prop",
        &"glass",
        &"stone",
    )
    var glass_target := GeneratedTestAudio.create_material(
        &"glass_wall",
        &"glass",
        &"stone",
    )

    var exact_output := GeneratedTestAudio.create_material(&"exact_output")
    var symmetric_output := GeneratedTestAudio.create_material(&"symmetric_output")
    var target_output := GeneratedTestAudio.create_material(&"target_output")
    var source_output := GeneratedTestAudio.create_material(&"source_output")
    var default_output := GeneratedTestAudio.create_material(&"default_output")

    var route_map := SonicImpactRouteMap.new()
    route_map.exact_routes.append(
        _impact_route(
            &"wood-on-stone",
            wood_source.stable_id(),
            stone_target.stable_id(),
            exact_output,
        ),
    )
    route_map.exact_routes.append(
        _impact_route(
            &"metal-and-wood",
            metal_target.stable_id(),
            wood_source.stable_id(),
            symmetric_output,
            true,
        ),
    )
    route_map.target_family_fallbacks.append(
        _family_fallback(&"stone-target", &"stone", target_output),
    )
    route_map.source_family_fallbacks.append(
        _family_fallback(&"wood-source", &"wood", source_output),
    )
    route_map.global_default = default_output

    _expect_route(
        route_map.resolve_impact(wood_source, stone_target),
        &"exact_output",
        SonicImpactRouteMap.EXACT_ORDERED,
        "ordered exact route",
    )
    _expect_route(
        route_map.resolve_impact(wood_source, metal_target),
        &"symmetric_output",
        SonicImpactRouteMap.EXACT_SYMMETRIC,
        "explicit symmetric route",
    )
    _expect_route(
        route_map.resolve_impact(glass_source, stone_target),
        &"target_output",
        SonicImpactRouteMap.TARGET_FAMILY,
        "target-family fallback",
    )
    _expect_route(
        route_map.resolve_impact(wood_source, glass_target),
        &"source_output",
        SonicImpactRouteMap.SOURCE_FAMILY,
        "source-family fallback",
    )
    _expect_route(
        route_map.resolve_impact(glass_source, glass_target),
        &"default_output",
        SonicImpactRouteMap.GLOBAL_DEFAULT,
        "global fallback",
    )


func _test_pair_resolution_fail_closed() -> void:
    var source := GeneratedTestAudio.create_material(&"source", &"wood", &"wood")
    var target := GeneratedTestAudio.create_material(&"target", &"stone", &"stone")
    var output := GeneratedTestAudio.create_material(&"output")

    var missing_map := SonicImpactRouteMap.new()
    var missing := missing_map.resolve_impact(source, target)
    _expect(
        not bool(missing.get("resolved", false)),
        "unmapped pair should fail closed",
    )
    _expect(
        missing.get("reason") == &"missing_mapping",
        "unmapped pair reason drifted",
    )

    var ambiguous_map := SonicImpactRouteMap.new()
    ambiguous_map.exact_routes.append(
        _impact_route(&"duplicate-a", &"source", &"target", output),
    )
    ambiguous_map.exact_routes.append(
        _impact_route(&"duplicate-b", &"source", &"target", output),
    )
    var ambiguous := ambiguous_map.resolve_impact(source, target)
    _expect(
        not bool(ambiguous.get("resolved", false)),
        "ambiguous exact routes should fail closed",
    )
    _expect(
        ambiguous.get("reason") == &"ambiguous_exact_ordered",
        "ambiguous exact route reason drifted",
    )

    var invalid_map := SonicImpactRouteMap.new()
    invalid_map.exact_routes.append(
        _impact_route(&"invalid-output", &"source", &"target", null),
    )
    var invalid := invalid_map.resolve_impact(source, target)
    _expect(
        not bool(invalid.get("resolved", false)),
        "exact route without output should fail closed",
    )
    _expect(
        invalid.get("reason") == &"invalid_exact_output",
        "invalid exact output reason drifted",
    )


func _impact_route(
        route_id: StringName,
        source_id: StringName,
        target_id: StringName,
        output: SonicAcousticMaterial,
        symmetric: bool = false,
) -> SonicImpactRoute:
    var route := SonicImpactRoute.new()
    route.route_id = route_id
    route.source_material_id = source_id
    route.target_material_id = target_id
    route.output_material = output
    route.symmetric = symmetric
    return route


func _family_fallback(
        fallback_id: StringName,
        family_id: StringName,
        output: SonicAcousticMaterial,
) -> SonicImpactFamilyFallback:
    var fallback := SonicImpactFamilyFallback.new()
    fallback.fallback_id = fallback_id
    fallback.family_id = family_id
    fallback.output_material = output
    return fallback


func _expect_route(
        result: Dictionary,
        expected_material_id: StringName,
        expected_resolution: StringName,
        label: String,
) -> void:
    _expect(
        bool(result.get("resolved", false)),
        "%s did not resolve" % label,
    )
    var material := result.get("material") as SonicAcousticMaterial
    _expect(material != null, "%s returned no material" % label)
    if material != null:
        _expect(
            material.stable_id() == expected_material_id,
            "%s selected the wrong output material" % label,
        )
    _expect(
        result.get("resolution") == expected_resolution,
        "%s reported the wrong resolution tier" % label,
    )


func _test_zero_weight_and_stats(selector: SonicSampleSelector) -> void:

    var zero_weight_material := GeneratedTestAudio.create_material(&"stone")
    for variant in zero_weight_material.impact_variants:
        variant.weight = 0.0
    _expect(
        selector.select_impact(
            zero_weight_material,
            _impact_event(2, 2),
        ).is_empty(),
        "zero total weight should fail closed",
    )

    var stats := selector.stats()
    _expect(int(stats["invalid_events"]) == 2, "invalid event count mismatch")
    _expect(int(stats["missing_mappings"]) == 2, "missing mapping count mismatch")


func _test_voice_budget_and_stale_release() -> void:
    var allocator := SonicVoiceAllocator.new()
    allocator.configure(2)
    var weak := allocator.allocate(10, 0, 0)
    var strong := allocator.allocate(11, 2, 10)

    _expect(allocator.active_count() == 2, "voice pool should be full")
    var replacement := allocator.allocate(12, 1, 5)
    _expect(bool(replacement["stolen"]), "third voice should steal")
    _expect(int(replacement["stolen_event_id"]) == 10, "weakest voice was not stolen")
    _expect(allocator.steal_count() == 1, "steal count mismatch")
    _expect(allocator.active_count() == 2, "steal exceeded capacity")

    _expect(
        not allocator.release(int(weak["index"]), int(weak["token"])),
        "stale token released a replacement voice",
    )
    _expect(
        allocator.release(int(strong["index"]), int(strong["token"])),
        "current token failed to release its voice",
    )
    _expect(allocator.active_count() == 1, "release count mismatch")
    _expect(allocator.capacity() == 2, "configured capacity changed")

    allocator.configure(99)
    _expect(allocator.capacity() == 8, "allocator must clamp to the Gate A cap")


func _test_generated_audio_fixture() -> void:
    var material := GeneratedTestAudio.create_material(&"wood")
    _expect(material.impact_variants.size() == 3, "fixture should provide three variants")
    for variant_index in material.impact_variants.size():
        var variant := material.impact_variants[variant_index]
        _expect(variant.stream is AudioStreamWAV, "fixture stream must be AudioStreamWAV")
        if variant.stream is AudioStreamWAV:
            var stream := variant.stream as AudioStreamWAV
            _expect(stream.mix_rate == 48000, "fixture mix rate must be 48 kHz")
            _expect(not stream.data.is_empty(), "fixture PCM must not be empty")


func _impact_event(event_id: int, seed: int) -> SonicFoleyEvent:
    return SonicFoleyEvent.impact(
        event_id,
        seed,
        0.65,
        Vector3.ZERO,
        0,
        SonicFoleyEvent.Evidence.ESTIMATED,
    )


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
