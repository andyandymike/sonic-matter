extends RefCounted
class_name SonicVoiceAllocator

var _capacity: int = 0
var _sequence: int = 0
var _next_token: int = 1
var _slots: Array[Dictionary] = []
var _steal_count: int = 0


func configure(new_capacity: int) -> void:
    _capacity = clampi(new_capacity, 1, 8)
    _sequence = 0
    _next_token = 1
    _steal_count = 0
    _slots.clear()
    for index in _capacity:
        _slots.append(_empty_slot(index))


func allocate(event_id: int, priority: int, importance: int) -> Dictionary:
    if _slots.is_empty():
        configure(8)

    var selected_index := -1
    for index in _slots.size():
        if not bool(_slots[index]["active"]):
            selected_index = index
            break

    var stolen_event_id := -1
    if selected_index < 0:
        selected_index = _least_important_slot()
        stolen_event_id = int(_slots[selected_index]["event_id"])
        _steal_count += 1

    _sequence += 1
    var token := _next_token
    _next_token += 1
    _slots[selected_index] = {
        "index": selected_index,
        "active": true,
        "token": token,
        "event_id": event_id,
        "priority": priority,
        "importance": importance,
        "started_sequence": _sequence,
    }
    return {
        "index": selected_index,
        "token": token,
        "stolen": stolen_event_id >= 0,
        "stolen_event_id": stolen_event_id,
    }


func release(index: int, token: int) -> bool:
    if index < 0 or index >= _slots.size():
        return false
    if not bool(_slots[index]["active"]):
        return false
    if int(_slots[index]["token"]) != token:
        return false
    _slots[index] = _empty_slot(index)
    return true


func is_active(index: int) -> bool:
    return (
        index >= 0
        and index < _slots.size()
        and bool(_slots[index]["active"])
    )


func token_at(index: int) -> int:
    if not is_active(index):
        return 0
    return int(_slots[index]["token"])


func active_count() -> int:
    var count := 0
    for slot in _slots:
        if bool(slot["active"]):
            count += 1
    return count


func steal_count() -> int:
    return _steal_count


func capacity() -> int:
    return _capacity


func _least_important_slot() -> int:
    var selected_index := 0
    for index in range(1, _slots.size()):
        if _is_weaker(_slots[index], _slots[selected_index]):
            selected_index = index
    return selected_index


func _is_weaker(candidate: Dictionary, current: Dictionary) -> bool:
    if int(candidate["priority"]) != int(current["priority"]):
        return int(candidate["priority"]) < int(current["priority"])
    if int(candidate["importance"]) != int(current["importance"]):
        return int(candidate["importance"]) < int(current["importance"])
    if int(candidate["started_sequence"]) != int(current["started_sequence"]):
        return int(candidate["started_sequence"]) < int(current["started_sequence"])
    return int(candidate["index"]) < int(current["index"])


func _empty_slot(index: int) -> Dictionary:
    return {
        "index": index,
        "active": false,
        "token": 0,
        "event_id": -1,
        "priority": 0,
        "importance": 0,
        "started_sequence": 0,
    }

