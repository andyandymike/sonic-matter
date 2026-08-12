extends SceneTree

const GeneratedTestAudio = preload("res://examples/gate_a_3d/generated_test_audio.gd")
const WARMUP_CALLS := 1000
const TIMED_CALLS := 10000
const RUNS := 5
const ABSOLUTE_P99_LIMIT_USEC := 500
const RETENTION_CHUNKS := 10
const RETENTION_CALLS_PER_CHUNK := 10000
const RETENTION_PLATEAU_LIMIT_BYTES := 262144
const RETENTION_TOTAL_LIMIT_BYTES := 1048576

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    var run_metrics: Array[Dictionary] = []
    for run_index in RUNS:
        run_metrics.append(_timed_run(run_index))
    var retention := _retention_observation()
    _test_stats_snapshot_isolation()
    var report := {
        "scope": "main_thread_policy_not_audio_callback_or_device_latency",
        "engine": Engine.get_version_info().get("string", "unknown"),
        "warmup_calls_per_run": WARMUP_CALLS,
        "timed_calls_per_run": TIMED_CALLS,
        "runs": run_metrics,
        "retention": retention,
    }
    print("RUNTIME_V2_POLICY_METRIC %s" % JSON.stringify(report, "", true, true))

    if _failures.is_empty():
        print("RUNTIME_V2_POLICY_BENCHMARK_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("RUNTIME_V2_POLICY_BENCHMARK_FAILED count=%d" % _failures.size())
    quit(1)


func _timed_run(run_index: int) -> Dictionary:
    var material := GeneratedTestAudio.create_material(&"runtime_v2_benchmark")
    var selector := SonicSampleSelector.new()
    for index in WARMUP_CALLS:
        selector.select_impact(
            material,
            _impact_event(100000 + index, 200000 + index * 17),
        )
    selector.reset()

    var samples := PackedInt64Array()
    samples.resize(TIMED_CALLS)
    var selected_checksum := 0
    for index in TIMED_CALLS:
        var started := Time.get_ticks_usec()
        var selection := selector.select_impact(
            material,
            _impact_event(300000 + index, 400000 + index * 29),
        )
        samples[index] = Time.get_ticks_usec() - started
        selected_checksum += int(selection.get("variant_index", -1))
    samples.sort()
    var p50 := _percentile(samples, 0.50)
    var p95 := _percentile(samples, 0.95)
    var p99 := _percentile(samples, 0.99)
    var maximum := int(samples[-1])
    _expect(p99 < ABSOLUTE_P99_LIMIT_USEC, "run %d p99 exceeded 0.5 ms" % run_index)
    _expect(
        int(selector.stats().get("selected", 0)) == TIMED_CALLS,
        "run %d selected counter drifted" % run_index,
    )
    return {
        "run": run_index,
        "p50_usec": p50,
        "p95_usec": p95,
        "p99_usec": p99,
        "max_usec": maximum,
        "selected_checksum": selected_checksum,
    }


func _retention_observation() -> Dictionary:
    var material := GeneratedTestAudio.create_material(&"runtime_v2_retention")
    var selector := SonicSampleSelector.new()
    for index in 10000:
        selector.select_impact(
            material,
            _impact_event(500000 + index, 600000 + index * 31),
        )

    var samples := PackedInt64Array()
    samples.resize(RETENTION_CHUNKS + 1)
    samples[0] = int(Performance.get_monitor(Performance.MEMORY_STATIC))
    for chunk in RETENTION_CHUNKS:
        for offset in RETENTION_CALLS_PER_CHUNK:
            var index := chunk * RETENTION_CALLS_PER_CHUNK + offset
            selector.select_impact(
                material,
                _impact_event(700000 + index, 800000 + index * 37),
            )
        samples[chunk + 1] = int(Performance.get_monitor(Performance.MEMORY_STATIC))

    var last_five := PackedInt64Array()
    for index in range(samples.size() - 5, samples.size()):
        last_five.append(samples[index])
    var minimum := int(last_five[0])
    var maximum := int(last_five[0])
    for sample in last_five:
        minimum = mini(minimum, int(sample))
        maximum = maxi(maximum, int(sample))
    var plateau_delta := maximum - minimum
    var total_delta := int(samples[-1] - samples[0])
    _expect(
        plateau_delta <= RETENTION_PLATEAU_LIMIT_BYTES,
        "retention plateau exceeded 256 KiB",
    )
    _expect(
        total_delta <= RETENTION_TOTAL_LIMIT_BYTES,
        "retention total exceeded 1 MiB",
    )
    return {
        "warmup_calls": 10000,
        "chunks": RETENTION_CHUNKS,
        "calls_per_chunk": RETENTION_CALLS_PER_CHUNK,
        "samples_bytes": Array(samples),
        "last_five_plateau_delta_bytes": plateau_delta,
        "total_delta_bytes": total_delta,
        "claim_boundary": "retained static memory only; not transient allocation volume",
    }


func _test_stats_snapshot_isolation() -> void:
    var material := GeneratedTestAudio.create_material(&"runtime_v2_stats")
    var selector := SonicSampleSelector.new()
    selector.select_impact(material, _impact_event(1, 1))
    var before := selector.stats()
    for index in 1000:
        selector.stats()
    var after_snapshots := selector.stats()
    _expect(before == after_snapshots, "stats snapshots changed selector state")
    var mutated := selector.stats()
    mutated["submitted"] = -999
    mutated["selected"] = -999
    _expect(before == selector.stats(), "mutating stats copy changed selector state")


func _percentile(samples: PackedInt64Array, percentile: float) -> int:
    var index := int(floor(float(samples.size() - 1) * percentile))
    return int(samples[clampi(index, 0, samples.size() - 1)])


func _impact_event(event_id: int, seed: int) -> SonicFoleyEvent:
    return SonicFoleyEvent.impact(
        event_id,
        seed,
        0.65,
        Vector3.ZERO,
        0,
        SonicFoleyEvent.Evidence.ESTIMATED,
    )


func _expect(condition: bool, message: String) -> void:
    if not condition:
        _failures.append(message)
