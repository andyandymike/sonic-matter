@tool
extends Node
class_name SonicMaterialBinding3D

@export var acoustic_material: SonicAcousticMaterial


func get_sonic_acoustic_material() -> SonicAcousticMaterial:
    return acoustic_material


func _get_configuration_warnings() -> PackedStringArray:
    if get_parent() == null or get_parent() is CollisionObject3D:
        return PackedStringArray()
    return PackedStringArray([
        "SonicMaterialBinding3D should be a direct child of CollisionObject3D.",
    ])
