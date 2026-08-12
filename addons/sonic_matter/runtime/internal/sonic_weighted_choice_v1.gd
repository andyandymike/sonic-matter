extends RefCounted

## Internal Gate A v1 weighted/no-repeat primitive.
##
## The public SonicSampleSelector remains the compatibility owner. This helper
## has no class_name and must not acquire route, event, stream, Node, bus, file,
## or persistent-state responsibilities.

const SLOT_SELECTED := 0
const SLOT_SOURCE_INDEX := 1
const SLOT_NO_REPEAT := 2
const SLOT_OUTCOME := 3

const OUTCOME_SELECTED := 1
const OUTCOME_NO_ELIGIBLE := 2
const OUTCOME_NONPOSITIVE_TOTAL_WEIGHT := 3


static func choose(
        variants: Array[SonicSampleVariant],
        eligible_indices: Array[int],
        previous_source_index: int,
        selection_unit: float,
        outcome: PackedInt32Array,
) -> void:
    if outcome.size() < 4:
        return

    outcome[SLOT_SELECTED] = 0
    outcome[SLOT_SOURCE_INDEX] = -1
    outcome[SLOT_NO_REPEAT] = 0
    outcome[SLOT_OUTCOME] = OUTCOME_NO_ELIGIBLE

    if eligible_indices.is_empty():
        return

    if eligible_indices.size() > 1 and eligible_indices.has(previous_source_index):
        eligible_indices.erase(previous_source_index)
        outcome[SLOT_NO_REPEAT] = 1

    var total_weight := 0.0
    for source_index in eligible_indices:
        total_weight += variants[source_index].weight
    if not is_finite(total_weight) or total_weight <= 0.0:
        outcome[SLOT_OUTCOME] = OUTCOME_NONPOSITIVE_TOTAL_WEIGHT
        return

    var target := selection_unit * total_weight
    var selected_source_index := eligible_indices[-1]
    var accumulated := 0.0
    for source_index in eligible_indices:
        accumulated += variants[source_index].weight
        if target < accumulated:
            selected_source_index = source_index
            break

    outcome[SLOT_SELECTED] = 1
    outcome[SLOT_SOURCE_INDEX] = selected_source_index
    outcome[SLOT_OUTCOME] = OUTCOME_SELECTED
