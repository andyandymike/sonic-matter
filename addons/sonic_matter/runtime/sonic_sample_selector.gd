extends RefCounted
class_name SonicSampleSelector

const UINT32_MASK: int = 0xFFFFFFFF
const UINT32_SCALE: float = 4294967296.0

var _last_variant_by_material: Dictionary = {}
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
    if eligible.size() > 1 and eligible.has(previous_index):
        eligible.erase(previous_index)
        _stats["no_repeat_avoided"] += 1

    var total_weight := 0.0
    for index in eligible:
        total_weight += material.impact_variants[index].weight

    if not is_finite(total_weight) or total_weight <= 0.0:
        _stats["missing_mappings"] += 1
        return {}

    var seed_base := (
        (event.seed & UINT32_MASK)
        ^ (event.event_id & UINT32_MASK)
        ^ _stable_text_hash32(material_key)
    )
    var target := _unit_float(_mix32(seed_base ^ 0x9E3779B9)) * total_weight
    var selected_index := eligible[-1]
    var accumulated := 0.0
    for index in eligible:
        accumulated += material.impact_variants[index].weight
        if target < accumulated:
            selected_index = index
            break

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

    _last_variant_by_material[material_key] = selected_index
    _stats["selected"] += 1
    return {
        "event_id": event.event_id,
        "material_id": material.stable_id(),
        "stream": selected_variant.stream,
        "variant_index": selected_index,
        "pitch_scale": clampf(
            selected_variant.pitch_scale * (1.0 + pitch_delta),
            0.25,
            4.0,
        ),
        "volume_db": clampf(
            material.intensity_gain_db(event.normalized_intensity())
            + selected_variant.gain_db
            + gain_delta,
            -80.0,
            6.0,
        ),
    }


func stats() -> Dictionary:
    return _stats.duplicate(true)


func reset() -> void:
    _last_variant_by_material.clear()
    for key in _stats:
        _stats[key] = 0


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

