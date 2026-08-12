@tool
extends Resource
class_name SonicSampleVariant

@export var stream: AudioStream
@export_range(0.0, 1000.0, 0.01, "or_greater") var weight: float = 1.0
@export_range(-24.0, 24.0, 0.1) var gain_db: float = 0.0
@export_range(0.25, 4.0, 0.001) var pitch_scale: float = 1.0


func is_eligible() -> bool:
    return (
        stream != null
        and is_finite(weight)
        and weight > 0.0
        and is_finite(gain_db)
        and is_finite(pitch_scale)
    )
