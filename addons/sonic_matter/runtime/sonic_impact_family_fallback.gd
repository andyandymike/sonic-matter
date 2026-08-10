@tool
extends Resource
class_name SonicImpactFamilyFallback

@export var fallback_id: StringName
@export var family_id: StringName
@export var output_material: SonicAcousticMaterial


func stable_id(role: StringName) -> StringName:
    if fallback_id != StringName():
        return fallback_id
    return StringName("%s-family:%s" % [role, family_id])
