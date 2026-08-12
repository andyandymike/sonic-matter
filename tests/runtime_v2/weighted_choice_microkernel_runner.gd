extends SceneTree

const WeightedChoiceV1 = preload(
    "res://addons/sonic_matter/runtime/internal/sonic_weighted_choice_v1.gd"
)

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    _test_empty()
    _test_single()
    _test_no_repeat_and_original_index()
    _test_non_contiguous_order()
    _test_nonpositive_total()
    _test_small_scratch_fails_without_write()
    if _failures.is_empty():
        print("RUNTIME_V2_MICROKERNEL_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("RUNTIME_V2_MICROKERNEL_FAILED count=%d" % _failures.size())
    quit(1)


func _test_empty() -> void:
    var outcome := PackedInt32Array([9, 9, 9, 9])
    WeightedChoiceV1.choose([], [], -1, 0.5, outcome)
    _expect_outcome(
        outcome,
        0,
        -1,
        0,
        WeightedChoiceV1.OUTCOME_NO_ELIGIBLE,
        "empty",
    )


func _test_single() -> void:
    var variants := _variants([2.0])
    var eligible: Array[int] = [0]
    var outcome := PackedInt32Array([0, -1, 0, 0])
    WeightedChoiceV1.choose(variants, eligible, 0, 0.99, outcome)
    _expect_outcome(
        outcome,
        1,
        0,
        0,
        WeightedChoiceV1.OUTCOME_SELECTED,
        "single",
    )


func _test_no_repeat_and_original_index() -> void:
    var variants := _variants([1.0, 3.0, 2.0])
    var eligible: Array[int] = [0, 1, 2]
    var outcome := PackedInt32Array([0, -1, 0, 0])
    WeightedChoiceV1.choose(variants, eligible, 1, 0.0, outcome)
    _expect_outcome(
        outcome,
        1,
        0,
        1,
        WeightedChoiceV1.OUTCOME_SELECTED,
        "no_repeat",
    )
    _expect(eligible == [0, 2], "no_repeat eligible ordering drifted")


func _test_non_contiguous_order() -> void:
    var variants := _variants([1.0, 100.0, 2.0])
    var eligible: Array[int] = [0, 2]
    var outcome := PackedInt32Array([0, -1, 0, 0])
    WeightedChoiceV1.choose(variants, eligible, -1, 0.999999, outcome)
    _expect_outcome(
        outcome,
        1,
        2,
        0,
        WeightedChoiceV1.OUTCOME_SELECTED,
        "non_contiguous",
    )


func _test_nonpositive_total() -> void:
    var variants := _variants([1.0e308, 1.0e308])
    var eligible: Array[int] = [0, 1]
    var outcome := PackedInt32Array([0, -1, 0, 0])
    WeightedChoiceV1.choose(variants, eligible, -1, 0.5, outcome)
    _expect_outcome(
        outcome,
        0,
        -1,
        0,
        WeightedChoiceV1.OUTCOME_NONPOSITIVE_TOTAL_WEIGHT,
        "nonpositive_total",
    )


func _test_small_scratch_fails_without_write() -> void:
    var variants := _variants([1.0])
    var eligible: Array[int] = [0]
    var outcome := PackedInt32Array([7, 8, 9])
    WeightedChoiceV1.choose(variants, eligible, -1, 0.5, outcome)
    _expect(outcome == PackedInt32Array([7, 8, 9]), "small scratch was mutated")


func _variants(weights: Array[float]) -> Array[SonicSampleVariant]:
    var variants: Array[SonicSampleVariant] = []
    for weight in weights:
        var variant := SonicSampleVariant.new()
        variant.weight = weight
        variants.append(variant)
    return variants


func _expect_outcome(
        outcome: PackedInt32Array,
        selected: int,
        source_index: int,
        no_repeat: int,
        outcome_class: int,
        label: String,
) -> void:
    _expect(outcome.size() >= 4, "%s outcome too small" % label)
    if outcome.size() < 4:
        return
    _expect(outcome[WeightedChoiceV1.SLOT_SELECTED] == selected, "%s selected drifted" % label)
    _expect(
        outcome[WeightedChoiceV1.SLOT_SOURCE_INDEX] == source_index,
        "%s source index drifted" % label,
    )
    _expect(
        outcome[WeightedChoiceV1.SLOT_NO_REPEAT] == no_repeat,
        "%s no-repeat drifted" % label,
    )
    _expect(
        outcome[WeightedChoiceV1.SLOT_OUTCOME] == outcome_class,
        "%s outcome class drifted" % label,
    )


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
