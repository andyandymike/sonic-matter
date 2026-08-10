extends RefCounted
class_name SonicGeneratedTestAudio

const MIX_RATE: int = 48000
const UINT32_MASK: int = 0xFFFFFFFF


static func create_material(material_name: StringName) -> SonicAcousticMaterial:
    var material := SonicAcousticMaterial.new()
    material.material_id = material_name
    material.impact_gain_db = Vector2(-20.0, -4.0)
    material.gain_variation_db = 0.8
    material.pitch_variation = 0.025

    for variant_index in 3:
        var variant := SonicSampleVariant.new()
        variant.stream = _make_impact_stream(
            String(material_name),
            variant_index,
        )
        variant.weight = 1.0 - float(variant_index) * 0.15
        variant.gain_db = -float(variant_index) * 0.25
        variant.pitch_scale = 1.0
        material.impact_variants.append(variant)
    return material


static func _make_impact_stream(profile: String, variant_index: int) -> AudioStreamWAV:
    var duration := 0.18
    var decay := 24.0
    match profile:
        "metal":
            duration = 0.48
            decay = 7.5
        "stone":
            duration = 0.14
            decay = 32.0
        _:
            duration = 0.20
            decay = 21.0

    var frame_count := int(round(duration * MIX_RATE))
    var pcm := PackedByteArray()
    pcm.resize(frame_count * 2)
    var noise_state := (0xB5297A4D ^ (variant_index * 0x68E31DA4)) & UINT32_MASK

    for frame in frame_count:
        var time := float(frame) / float(MIX_RATE)
        var envelope := exp(-decay * time)
        noise_state = (1664525 * noise_state + 1013904223) & UINT32_MASK
        var noise := float(noise_state) / 2147483648.0 - 1.0
        var sample := _profile_sample(profile, variant_index, time, noise)
        if frame < 48:
            sample += (1.0 - float(frame) / 48.0) * 0.22
        sample = clampf(sample * envelope * 0.65, -1.0, 1.0)
        var sample_i16 := clampi(int(round(sample * 32767.0)), -32768, 32767)
        pcm[frame * 2] = sample_i16 & 0xFF
        pcm[frame * 2 + 1] = (sample_i16 >> 8) & 0xFF

    var stream := AudioStreamWAV.new()
    stream.format = AudioStreamWAV.FORMAT_16_BITS
    stream.mix_rate = MIX_RATE
    stream.stereo = false
    stream.loop_mode = AudioStreamWAV.LOOP_DISABLED
    stream.data = pcm
    stream.tags = {
        "artist": "SonicMatter contributors",
        "title": "Gate A synthetic %s impact %d" % [profile, variant_index],
        "license": "CC0-1.0",
    }
    return stream


static func _profile_sample(
        profile: String,
        variant_index: int,
        time: float,
        noise: float,
) -> float:
    var detune := float(variant_index) * 0.035
    match profile:
        "metal":
            return (
                sin(TAU * (620.0 * (1.0 + detune)) * time) * 0.44
                + sin(TAU * (1190.0 * (1.0 - detune * 0.5)) * time) * 0.28
                + sin(TAU * (1810.0 * (1.0 + detune * 0.2)) * time) * 0.18
                + noise * 0.08
            )
        "stone":
            return (
                sin(TAU * (270.0 * (1.0 + detune)) * time) * 0.34
                + noise * 0.58
            )
        _:
            return (
                sin(TAU * (155.0 * (1.0 + detune)) * time) * 0.42
                + sin(TAU * (315.0 * (1.0 - detune)) * time) * 0.16
                + noise * 0.34
            )

