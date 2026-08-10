extends SceneTree

const TEST_AUDIO := preload("res://examples/gate_a_3d/generated_test_audio.gd")

const PEAK_LIMIT: float = 0.95
const RMS_LIMIT: float = 0.35
const DC_LIMIT: float = 0.05

var _failures: Array[String] = []


func _initialize() -> void:
    call_deferred("_run")


func _run() -> void:
    for profile in [&"wood", &"metal", &"stone"]:
        var material := TEST_AUDIO.create_material(profile)
        for variant_index in material.impact_variants.size():
            var stream := (
                material.impact_variants[variant_index].stream
                as AudioStreamWAV
            )
            _inspect_stream(profile, variant_index, stream)

    if _failures.is_empty():
        print("GATE_A_AUDIO_SAFETY_OK")
        quit(0)
        return
    for failure in _failures:
        push_error(failure)
    push_error("GATE_A_AUDIO_SAFETY_FAILED count=%d" % _failures.size())
    quit(1)


func _inspect_stream(
        profile: StringName,
        variant_index: int,
        stream: AudioStreamWAV,
) -> void:
    var label := "%s[%d]" % [profile, variant_index]
    if stream == null:
        _failures.append("%s has no WAV stream" % label)
        return
    if stream.format != AudioStreamWAV.FORMAT_16_BITS or stream.stereo:
        _failures.append("%s is not 16-bit mono" % label)
        return
    if stream.mix_rate != 48000 or stream.data.is_empty():
        _failures.append("%s has invalid rate or empty PCM" % label)
        return

    var frame_count := stream.data.size() / 2
    var peak := 0.0
    var sum := 0.0
    var sum_squares := 0.0
    for frame in frame_count:
        var encoded := (
            int(stream.data[frame * 2])
            | (int(stream.data[frame * 2 + 1]) << 8)
        )
        var signed := encoded if encoded < 32768 else encoded - 65536
        var sample := float(signed) / 32768.0
        peak = maxf(peak, absf(sample))
        sum += sample
        sum_squares += sample * sample

    var mean := sum / float(frame_count)
    var rms := sqrt(sum_squares / float(frame_count))
    var metrics := {
        "profile": String(profile),
        "variant": variant_index,
        "frames": frame_count,
        "peak": peak,
        "rms": rms,
        "dc": mean,
    }
    print("GATE_A_AUDIO_METRIC %s" % JSON.stringify(metrics))
    if peak > PEAK_LIMIT:
        _failures.append("%s peak %.6f exceeds %.2f" % [label, peak, PEAK_LIMIT])
    if rms > RMS_LIMIT:
        _failures.append("%s RMS %.6f exceeds %.2f" % [label, rms, RMS_LIMIT])
    if absf(mean) > DC_LIMIT:
        _failures.append("%s DC %.6f exceeds %.2f" % [label, mean, DC_LIMIT])
