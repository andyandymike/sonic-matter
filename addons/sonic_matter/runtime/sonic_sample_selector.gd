extends RefCounted
class_name SonicSampleSelector

const WeightedChoiceV1 = preload(
    "res://addons/sonic_matter/runtime/internal/sonic_weighted_choice_v1.gd"
)
const UINT32_MASK: int = 0xFFFFFFFF
const UINT32_SCALE: float = 4294967296.0

var _last_variant_by_material: Dictionary = {}
var _choice_outcome := PackedInt32Array([0, -1, 0, 0])
var _stats: Dictionary = {
    "submitted": 0,
    "selected": 0,
    "invalid_events": 0,
    "missing_mappings": 0,
    "no_repeat_avoided": 0,
}


func select_impact(
        material: SonicAcousticMaterial,
        event: SonicFoleyEvent,
) -> Dictionary:
    _stats["submitted"] += 1

    if material == null or event == null or not event.is_valid():
        _stats["invalid_events"] += 1
        return {}
    if not _has_valid_impact_parameters(material):
        _stats["missing_mappings"] += 1
        return {}

    var eligible: Array[int] = []
    for index in material.impact_variants.size():
        var variant := material.impact_variants[index]
        if variant != null and variant.is_eligible():
            eligible.append(index)

    if eligible.is_empty():
        _stats["missing_mappings"] += 1
        return {}

    var material_key := String(material.stable_id())
    var previous_index := int(_last_variant_by_material.get(material_key, -1))
    var seed_base := (
        (event.seed & UINT32_MASK)
        ^ (event.event_id & UINT32_MASK)
        ^ _stable_text_hash32(material_key)
    )
    var selection_unit := _unit_float(_mix32(seed_base ^ 0x9E3779B9))
    WeightedChoiceV1.choose(
        material.impact_variants,
        eligible,
        previous_index,
        selection_unit,
        _choice_outcome,
    )
    if _choice_outcome[WeightedChoiceV1.SLOT_SELECTED] == 0:
        _stats["missing_mappings"] += 1
        return {}

    var selected_index := int(
        _choice_outcome[WeightedChoiceV1.SLOT_SOURCE_INDEX]
    )

    var selected_variant := material.impact_variants[selected_index]
    var pitch_random := _unit_float(_mix32(seed_base ^ 0xA341316C))
    var gain_random := _unit_float(_mix32(seed_base ^ 0xC8013EA4))
    var pitch_delta := lerpf(
        -material.pitch_variation,
        material.pitch_variation,
        pitch_random,
    )
    var gain_delta := lerpf(
        -material.gain_variation_db,
        material.gain_variation_db,
        gain_random,
    )
    var raw_pitch_scale := selected_variant.pitch_scale * (1.0 + pitch_delta)
    var raw_volume_db := (
        material.intensity_gain_db(event.normalized_intensity())
        + selected_variant.gain_db
        + gain_delta
    )
    if not is_finite(raw_pitch_scale) or not is_finite(raw_volume_db):
        _stats["missing_mappings"] += 1
        return {}
    var pitch_scale := clampf(raw_pitch_scale, 0.25, 4.0)
    var volume_db := clampf(raw_volume_db, -80.0, 6.0)

    _last_variant_by_material[material_key] = selected_index
    if _choice_outcome[WeightedChoiceV1.SLOT_NO_REPEAT] != 0:
        _stats["no_repeat_avoided"] += 1
    _stats["selected"] += 1
    return {
        "event_id": event.event_id,
        "material_id": material.stable_id(),
        "stream": selected_variant.stream,
        "variant_index": selected_index,
        "pitch_scale": pitch_scale,
        "volume_db": volume_db,
    }


func stats() -> Dictionary:
    return _stats.duplicate(true)


func reset() -> void:
    _last_variant_by_material.clear()
    for key in _stats:
        _stats[key] = 0


static func _has_valid_impact_parameters(
        material: SonicAcousticMaterial,
) -> bool:
    return (
        is_finite(material.impact_gain_db.x)
        and is_finite(material.impact_gain_db.y)
        and is_finite(material.gain_variation_db)
        and is_finite(material.pitch_variation)
    )


static func _mix32(value: int) -> int:
    var mixed := value & UINT32_MASK
    mixed = (1664525 * mixed + 1013904223) & UINT32_MASK
    mixed = (1664525 * mixed + 1013904223) & UINT32_MASK
    mixed = (1664525 * mixed + 1013904223) & UINT32_MASK
    return mixed


static func _unit_float(value: int) -> float:
    return float(value & UINT32_MASK) / UINT32_SCALE


static func _stable_text_hash32(text: String) -> int:
    var result: int = 2166136261
    for byte in text.to_utf8_buffer():
        result = (result ^ int(byte)) & UINT32_MASK
        result = (result * 16777619) & UINT32_MASK
    return result
