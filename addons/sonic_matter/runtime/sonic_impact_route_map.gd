@tool
extends Resource
class_name SonicImpactRouteMap

const EXACT_ORDERED: StringName = &"exact_ordered"
const EXACT_SYMMETRIC: StringName = &"exact_symmetric"
const TARGET_FAMILY: StringName = &"target_family"
const SOURCE_FAMILY: StringName = &"source_family"
const GLOBAL_DEFAULT: StringName = &"global_default"

@export var exact_routes: Array[SonicImpactRoute] = []
@export var target_family_fallbacks: Array[SonicImpactFamilyFallback] = []
@export var source_family_fallbacks: Array[SonicImpactFamilyFallback] = []
@export var global_default: SonicAcousticMaterial


func resolve_impact(
        source: SonicAcousticMaterial,
        target: SonicAcousticMaterial,
) -> Dictionary:
    var source_id := source.stable_id() if source != null else StringName()
    var target_id := target.stable_id() if target != null else StringName()

    var ordered := _find_exact(source_id, target_id, false)
    if bool(ordered.get("ambiguous", false)):
        return _failure(&"ambiguous_exact_ordered", source_id, target_id)
    if ordered.get("route") != null:
        return _route_result(
            ordered["route"] as SonicImpactRoute,
            EXACT_ORDERED,
            source_id,
            target_id,
        )

    var symmetric := _find_exact(source_id, target_id, true)
    if bool(symmetric.get("ambiguous", false)):
        return _failure(&"ambiguous_exact_symmetric", source_id, target_id)
    if symmetric.get("route") != null:
        return _route_result(
            symmetric["route"] as SonicImpactRoute,
            EXACT_SYMMETRIC,
            source_id,
            target_id,
        )

    if target != null:
        var target_fallback := _find_family(
            target_family_fallbacks,
            target.stable_family_id(),
        )
        if bool(target_fallback.get("ambiguous", false)):
            return _failure(&"ambiguous_target_family", source_id, target_id)
        if target_fallback.get("fallback") != null:
            return _fallback_result(
                target_fallback["fallback"] as SonicImpactFamilyFallback,
                TARGET_FAMILY,
                source_id,
                target_id,
            )

    if source != null:
        var source_fallback := _find_family(
            source_family_fallbacks,
            source.stable_family_id(),
        )
        if bool(source_fallback.get("ambiguous", false)):
            return _failure(&"ambiguous_source_family", source_id, target_id)
        if source_fallback.get("fallback") != null:
            return _fallback_result(
                source_fallback["fallback"] as SonicImpactFamilyFallback,
                SOURCE_FAMILY,
                source_id,
                target_id,
            )

    if global_default != null:
        return _success(
            global_default,
            GLOBAL_DEFAULT,
            &"global-default",
            source_id,
            target_id,
        )
    return _failure(&"missing_mapping", source_id, target_id)


func _find_exact(
        source_id: StringName,
        target_id: StringName,
        reverse_symmetric: bool,
) -> Dictionary:
    var matched_route: SonicImpactRoute
    for route in exact_routes:
        if route == null:
            continue
        var matched := (
            route.matches_symmetric_reverse(source_id, target_id)
            if reverse_symmetric
            else route.matches_ordered(source_id, target_id)
        )
        if not matched:
            continue
        if matched_route != null:
            return {"ambiguous": true}
        matched_route = route
    return {"route": matched_route, "ambiguous": false}


func _find_family(
        fallbacks: Array[SonicImpactFamilyFallback],
        family_id: StringName,
) -> Dictionary:
    var matched_fallback: SonicImpactFamilyFallback
    for fallback in fallbacks:
        if fallback == null or fallback.family_id != family_id:
            continue
        if matched_fallback != null:
            return {"ambiguous": true}
        matched_fallback = fallback
    return {"fallback": matched_fallback, "ambiguous": false}


func _route_result(
        route: SonicImpactRoute,
        resolution: StringName,
        source_id: StringName,
        target_id: StringName,
) -> Dictionary:
    if route.output_material == null:
        return _failure(&"invalid_exact_output", source_id, target_id)
    return _success(
        route.output_material,
        resolution,
        route.stable_id(),
        source_id,
        target_id,
    )


func _fallback_result(
        fallback: SonicImpactFamilyFallback,
        resolution: StringName,
        source_id: StringName,
        target_id: StringName,
) -> Dictionary:
    if fallback.output_material == null:
        return _failure(&"invalid_family_output", source_id, target_id)
    return _success(
        fallback.output_material,
        resolution,
        fallback.stable_id(resolution),
        source_id,
        target_id,
    )


func _success(
        material: SonicAcousticMaterial,
        resolution: StringName,
        route_id: StringName,
        source_id: StringName,
        target_id: StringName,
) -> Dictionary:
    return {
        "resolved": true,
        "material": material,
        "resolution": resolution,
        "route_id": route_id,
        "source_material_id": source_id,
        "target_material_id": target_id,
    }


func _failure(
        reason: StringName,
        source_id: StringName,
        target_id: StringName,
) -> Dictionary:
    return {
        "resolved": false,
        "reason": reason,
        "source_material_id": source_id,
        "target_material_id": target_id,
    }
