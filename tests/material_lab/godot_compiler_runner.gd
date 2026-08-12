extends SceneTree


const FIXTURE_ROOT := "res://tests/material_lab/generated_ci"

var _failures: Array[String] = []


func _initialize() -> void:
    var source := load(FIXTURE_ROOT + "/materials/wood_prop.tres") as SonicAcousticMaterial
    var target := load(FIXTURE_ROOT + "/materials/stone_floor.tres") as SonicAcousticMaterial
    var route_map := load(FIXTURE_ROOT + "/impact_route_map.tres") as SonicImpactRouteMap
    _expect(source != null, "source material did not load")
    _expect(target != null, "target material did not load")
    _expect(route_map != null, "route map did not load")
    if source != null:
        _expect(source.stable_id() == &"wood_prop", "source material identity drifted")
    if target != null:
        _expect(target.stable_family_id() == &"stone", "target family identity drifted")
    if source != null and target != null and route_map != null:
        var result: Dictionary = route_map.resolve_impact(source, target)
        _expect(bool(result.get("resolved", false)), "target-family route did not resolve")
        _expect(result.get("resolution") == &"target_family", "resolution tier drifted")
        _expect(result.get("route_id") == &"stone_family_fallback", "fallback identity drifted")
        var material := result.get("material") as SonicAcousticMaterial
        _expect(material != null, "route returned no output material")
        if material != null:
            _expect(material.stable_id() == &"wood_on_stone", "palette identity drifted")
            _expect(material.impact_gain_db.is_equal_approx(Vector2(-20.0, -4.0)), "impact gain range drifted")
            _expect(is_equal_approx(material.gain_variation_db, 0.75), "gain variation drifted")
            _expect(is_equal_approx(material.pitch_variation, 0.03), "pitch variation drifted")
            _expect(material.impact_variants.size() == 1, "variant count drifted")
            if material.impact_variants.size() == 1:
                var variant := material.impact_variants[0]
                _expect(variant != null, "variant did not load")
                if variant != null:
                    _expect(variant.stream != null, "variant stream did not load")
                    _expect(is_equal_approx(variant.weight, 2.5), "variant weight drifted")
                    _expect(is_equal_approx(variant.gain_db, -1.5), "variant gain drifted")
                    _expect(is_equal_approx(variant.pitch_scale, 0.96), "variant pitch drifted")
    if _failures.is_empty():
        print("MATERIAL_LAB_GODOT_COMPILER_OK")
        quit(0)
    else:
        for failure in _failures:
            push_error(failure)
        quit(1)


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
