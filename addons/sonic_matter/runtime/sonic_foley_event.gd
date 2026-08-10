extends RefCounted
class_name SonicFoleyEvent

enum Kind {
    IMPACT,
}

enum Evidence {
    MEASURED,
    ESTIMATED,
    AUTHORED,
    UNAVAILABLE,
}

var kind: Kind = Kind.IMPACT
var event_id: int = -1
var seed: int = 0
var intensity: float = 0.0
var intensity_evidence: Evidence = Evidence.UNAVAILABLE
var position: Vector3 = Vector3.ZERO
var priority: int = 0


static func impact(
        new_event_id: int,
        new_seed: int,
        new_intensity: float,
        new_position: Vector3,
        new_priority: int = 0,
        evidence: Evidence = Evidence.AUTHORED,
) -> SonicFoleyEvent:
    var event := SonicFoleyEvent.new()
    event.kind = Kind.IMPACT
    event.event_id = new_event_id
    event.seed = new_seed
    event.intensity = new_intensity
    event.intensity_evidence = evidence
    event.position = new_position
    event.priority = new_priority
    return event


func is_valid() -> bool:
    return (
        kind == Kind.IMPACT
        and event_id >= 0
        and is_finite(intensity)
        and position.is_finite()
    )


func normalized_intensity() -> float:
    return clampf(intensity, 0.0, 1.0)
