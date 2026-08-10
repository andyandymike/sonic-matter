@tool
extends Resource
class_name SonicImpactRoute

@export var route_id: StringName
@export var source_material_id: StringName
@export var target_material_id: StringName
@export var symmetric: bool = false
@export var output_material: SonicAcousticMaterial


func stable_id() -> StringName:
    if route_id != StringName():
        return route_id
    return StringName("%s->%s" % [source_material_id, target_material_id])


func matches_ordered(source_id: StringName, target_id: StringName) -> bool:
    return source_material_id == source_id and target_material_id == target_id


func matches_symmetric_reverse(source_id: StringName, target_id: StringName) -> bool:
    return (
        symmetric
        and source_material_id == target_id
        and target_material_id == source_id
    )
