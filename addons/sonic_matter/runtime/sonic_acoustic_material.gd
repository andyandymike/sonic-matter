@tool
extends Resource
class_name SonicAcousticMaterial

@export var material_id: StringName = &"default"
@export var impact_variants: Array[SonicSampleVariant] = []
@export var impact_gain_db: Vector2 = Vector2(-18.0, -3.0)
@export_range(0.0, 12.0, 0.1) var gain_variation_db: float = 1.0
@export_range(0.0, 0.5, 0.001) var pitch_variation: float = 0.04


func stable_id() -> StringName:
    if material_id == StringName():
        return &"default"
    return material_id


func intensity_gain_db(intensity: float) -> float:
    var low := minf(impact_gain_db.x, impact_gain_db.y)
    var high := maxf(impact_gain_db.x, impact_gain_db.y)
    return lerpf(low, high, clampf(intensity, 0.0, 1.0))

