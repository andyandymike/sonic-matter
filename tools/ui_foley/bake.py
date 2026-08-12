from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import wave
from pathlib import Path
from typing import Any, Iterable


GENERATOR_ID = "sonicmatter.ui-paper-baker"
GENERATOR_VERSION = "1.0.0"
SCHEMA_ID = "sonic-ui-paper/v1"
_TAU = math.tau
_MASK_64 = (1 << 64) - 1
_PCM24_MAX = (1 << 23) - 1
_PCM24_MIN = -(1 << 23)
_LAYERS = (
    "friction",
    "fiber_grains",
    "micro_buckle",
    "body_flex",
    "landing_slap",
)
_D015_RESTRICTED_ACTIONS = (
    "source_repo_distribution",
    "material_kit_distribution",
    "game_source_distribution",
    "game_binary_embedding",
    "standalone_baked_audio_distribution",
    "training_or_parameter_fitting",
    "evaluation_use",
    "evaluation_stimulus_publication",
    "private_embeddings",
    "index_redistribution",
)


class BakeError(RuntimeError):
    """Raised when a recipe or output would violate the bake contract."""


class Pcg32:
    """Small deterministic PRNG with explicitly selected streams."""

    _MULTIPLIER = 6364136223846793005

    def __init__(self, seed: int, stream: int) -> None:
        self._state = 0
        self._increment = ((stream & _MASK_64) << 1 | 1) & _MASK_64
        self._next_uint32()
        self._state = (self._state + (seed & _MASK_64)) & _MASK_64
        self._next_uint32()

    def _next_uint32(self) -> int:
        previous = self._state
        self._state = (
            previous * self._MULTIPLIER + self._increment
        ) & _MASK_64
        xorshifted = ((previous >> 18) ^ previous) >> 27
        rotation = previous >> 59
        return (
            (xorshifted >> rotation)
            | (xorshifted << ((-rotation) & 31))
        ) & 0xFFFFFFFF

    def random(self) -> float:
        return self._next_uint32() / 4294967296.0

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def signed(self) -> float:
        return self.random() * 2.0 - 1.0


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _domain_rng(
    recipe_id: str,
    user_seed: int,
    profile_id: str,
    variant: int,
    domain: str,
) -> Pcg32:
    payload = (
        f"{GENERATOR_ID}\0{GENERATOR_VERSION}\0{recipe_id}\0"
        f"{user_seed}\0{profile_id}\0{variant}\0{domain}"
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    seed = int.from_bytes(digest[0:8], "little")
    stream = int.from_bytes(digest[8:16], "little")
    return Pcg32(seed, stream)


def _require_number(
    mapping: dict[str, Any],
    name: str,
    low: float,
    high: float,
) -> float:
    value = mapping.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BakeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise BakeError(f"{name} must be between {low} and {high}")
    return result


def _require_range(
    mapping: dict[str, Any],
    name: str,
    low: float,
    high: float,
) -> tuple[float, float]:
    value = mapping.get(name)
    if not isinstance(value, list) or len(value) != 2:
        raise BakeError(f"{name} must contain exactly two values")
    first = float(value[0])
    second = float(value[1])
    if not low <= first <= second <= high:
        raise BakeError(f"{name} must be ordered within {low} and {high}")
    return first, second


def _validate_profile(profile: Any) -> None:
    if not isinstance(profile, dict):
        raise BakeError("each profile must be an object")
    profile_id = profile.get("id")
    cue_id = profile.get("cue_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise BakeError("profile id must be a non-empty string")
    if not isinstance(cue_id, str) or not cue_id.startswith("ui.foley."):
        raise BakeError(f"profile {profile_id} has an invalid cue_id")
    _require_number(profile, "duration_ms", 40.0, 1000.0)
    _require_number(profile, "target_peak_dbfs", -24.0, -1.0)

    pan = profile.get("pan")
    if not isinstance(pan, dict):
        raise BakeError(f"profile {profile_id} pan must be an object")
    _require_number(pan, "start", -1.0, 1.0)
    _require_number(pan, "end", -1.0, 1.0)

    friction = profile.get("friction")
    if not isinstance(friction, dict):
        raise BakeError(f"profile {profile_id} friction must be an object")
    _require_number(friction, "amplitude", 0.0, 1.0)
    _require_number(friction, "highpass_hz", 20.0, 18000.0)
    low_start = _require_number(
        friction, "lowpass_start_hz", 100.0, 22000.0
    )
    low_end = _require_number(
        friction, "lowpass_end_hz", 100.0, 22000.0
    )
    highpass = float(friction["highpass_hz"])
    if low_start <= highpass or low_end <= highpass:
        raise BakeError(f"profile {profile_id} friction band is empty")
    _require_number(friction, "am_rate_hz", 0.1, 200.0)

    grains = profile.get("fiber_grains")
    if not isinstance(grains, dict):
        raise BakeError(f"profile {profile_id} fiber_grains must be an object")
    _require_number(grains, "rate_hz", 0.0, 1000.0)
    _require_range(grains, "duration_ms", 0.2, 50.0)
    _require_range(grains, "frequency_hz", 50.0, 22000.0)
    _require_number(grains, "amplitude", 0.0, 1.0)

    buckle = profile.get("micro_buckle")
    if not isinstance(buckle, dict):
        raise BakeError(f"profile {profile_id} micro_buckle must be an object")
    count = buckle.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 64:
        raise BakeError(f"profile {profile_id} buckle count is invalid")
    _require_range(buckle, "duration_ms", 0.5, 100.0)
    _require_number(buckle, "amplitude", 0.0, 1.0)

    modes = profile.get("body_modes")
    if not isinstance(modes, list) or not 1 <= len(modes) <= 16:
        raise BakeError(f"profile {profile_id} needs 1 to 16 body modes")
    for mode in modes:
        if not isinstance(mode, dict):
            raise BakeError(f"profile {profile_id} body mode is invalid")
        _require_number(mode, "frequency_hz", 20.0, 22000.0)
        _require_number(mode, "amplitude", 0.0, 1.0)
        _require_number(mode, "decay_ms", 1.0, 2000.0)

    landing = profile.get("landing")
    if not isinstance(landing, dict):
        raise BakeError(f"profile {profile_id} landing must be an object")
    _require_number(landing, "position", 0.1, 0.95)
    _require_number(landing, "amplitude", 0.0, 1.0)
    _require_number(landing, "decay_ms", 1.0, 1000.0)


def _validate_recipe(recipe: Any) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise BakeError("recipe root must be an object")
    if recipe.get("schema") != SCHEMA_ID:
        raise BakeError(f"recipe schema must be {SCHEMA_ID}")
    recipe_id = recipe.get("recipe_id")
    if not isinstance(recipe_id, str) or not recipe_id:
        raise BakeError("recipe_id must be a non-empty string")
    generator = recipe.get("generator")
    if not isinstance(generator, dict):
        raise BakeError("generator metadata is missing")
    if generator.get("id") != GENERATOR_ID:
        raise BakeError(f"generator id must be {GENERATOR_ID}")
    if generator.get("version") != GENERATOR_VERSION:
        raise BakeError(f"generator version must be {GENERATOR_VERSION}")

    render = recipe.get("render")
    if not isinstance(render, dict):
        raise BakeError("render metadata is missing")
    sample_rate = render.get("sample_rate_hz")
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not 8000 <= sample_rate <= 192000
    ):
        raise BakeError("sample_rate_hz is invalid")
    if render.get("channels") != 2:
        raise BakeError("only stereo recipes are supported")
    if render.get("sample_format") != "PCM_S24LE":
        raise BakeError("only PCM_S24LE masters are supported")
    variants = render.get("variants_per_profile")
    if (
        isinstance(variants, bool)
        or not isinstance(variants, int)
        or not 1 <= variants <= 32
    ):
        raise BakeError("variants_per_profile must be between 1 and 32")
    seed = render.get("user_seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BakeError("user_seed must be an integer")

    profiles = recipe.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise BakeError("at least one profile is required")
    profile_ids: set[str] = set()
    cue_ids: set[str] = set()
    for profile in profiles:
        _validate_profile(profile)
        profile_id = str(profile["id"])
        cue_id = str(profile["cue_id"])
        if profile_id in profile_ids or cue_id in cue_ids:
            raise BakeError("profile ids and cue ids must be unique")
        profile_ids.add(profile_id)
        cue_ids.add(cue_id)

    rights = recipe.get("rights")
    if not isinstance(rights, dict):
        raise BakeError("rights metadata is mandatory")
    if rights.get("output_license") != "UNDECIDED":
        raise BakeError("Experiment U0 must not infer an outbound audio license")
    if rights.get("output_rights_decision_id") != "D-015":
        raise BakeError("Experiment U0 output rights must remain bound to D-015")
    if rights.get("recorded_parents") != [] or rights.get("external_assets") != []:
        raise BakeError("Experiment U0 accepts no recorded or external parents")
    for action in (
        "local_preview",
        "private_game_source_use",
        "source_repo_distribution",
        "material_kit_distribution",
        "game_source_distribution",
        "game_binary_embedding",
        "standalone_baked_audio_distribution",
        "training_or_parameter_fitting",
        "evaluation_use",
        "evaluation_stimulus_publication",
        "private_embeddings",
        "index_redistribution",
    ):
        if rights.get(action) not in {"allow", "deny", "unknown"}:
            raise BakeError(f"rights action {action} is invalid")
    if rights["local_preview"] != "allow":
        raise BakeError("local_preview must be allowed for this experiment")
    for restricted_action in _D015_RESTRICTED_ACTIONS:
        if rights[restricted_action] == "allow":
            raise BakeError(f"{restricted_action} must remain fail-closed")
    return recipe


def load_recipe(path: Path | str) -> dict[str, Any]:
    recipe_path = Path(path)
    try:
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BakeError(f"cannot read recipe {recipe_path}: {exc}") from exc
    return _validate_recipe(recipe)


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _motion_envelope(index: int, length: int) -> float:
    if length <= 1:
        return 0.0
    position = index / (length - 1)
    attack = _smoothstep(position / 0.075)
    release = _smoothstep((1.0 - position) / 0.17)
    arch = math.sin(math.pi * position) ** 0.45
    return attack * release * arch


def _lowpass_alpha(cutoff_hz: float, sample_rate: int) -> float:
    safe_cutoff = max(10.0, min(cutoff_hz, sample_rate * 0.45))
    return math.exp(-_TAU * safe_cutoff / sample_rate)


def _render_friction(
    profile: dict[str, Any],
    length: int,
    sample_rate: int,
    rng: Pcg32,
) -> list[float]:
    config = profile["friction"]
    amplitude = float(config["amplitude"])
    highpass_hz = float(config["highpass_hz"])
    low_start = float(config["lowpass_start_hz"])
    low_end = float(config["lowpass_end_hz"])
    am_rate = float(config["am_rate_hz"])
    am_phase = rng.uniform(0.0, _TAU)
    low_state = 0.0
    highpass_state = 0.0
    high_alpha = _lowpass_alpha(highpass_hz, sample_rate)
    output = [0.0] * length
    for index in range(length):
        position = index / max(1, length - 1)
        sweep = _smoothstep(position)
        cutoff = low_start + (low_end - low_start) * sweep
        low_alpha = _lowpass_alpha(cutoff, sample_rate)
        white = rng.signed()
        low_state = (1.0 - low_alpha) * white + low_alpha * low_state
        highpass_state = (
            (1.0 - high_alpha) * low_state + high_alpha * highpass_state
        )
        band = low_state - highpass_state
        flutter = 0.78 + 0.22 * math.sin(
            _TAU * am_rate * index / sample_rate + am_phase
        )
        output[index] = (
            band * amplitude * flutter * _motion_envelope(index, length)
        )
    return output


def _render_fiber_grains(
    profile: dict[str, Any],
    length: int,
    sample_rate: int,
    rng: Pcg32,
) -> list[float]:
    config = profile["fiber_grains"]
    rate_hz = float(config["rate_hz"])
    duration_low, duration_high = map(float, config["duration_ms"])
    frequency_low, frequency_high = map(float, config["frequency_hz"])
    amplitude = float(config["amplitude"])
    duration_seconds = length / sample_rate
    expected = rate_hz * duration_seconds
    count = int(expected)
    if rng.random() < expected - count:
        count += 1
    output = [0.0] * length
    for _ in range(count):
        center = int(rng.uniform(0.06, 0.93) * length)
        grain_length = max(
            2,
            int(rng.uniform(duration_low, duration_high) * sample_rate / 1000.0),
        )
        frequency = rng.uniform(frequency_low, frequency_high)
        phase = rng.uniform(0.0, _TAU)
        gain = amplitude * rng.uniform(0.55, 1.0)
        start = max(0, center - grain_length // 2)
        end = min(length, start + grain_length)
        for index in range(start, end):
            local = (index - start) / max(1, grain_length - 1)
            window = math.sin(math.pi * local) ** 2
            carrier = 0.72 * math.sin(
                _TAU * frequency * (index - start) / sample_rate + phase
            )
            carrier += 0.28 * rng.signed()
            output[index] += gain * window * carrier
    return output


def _render_micro_buckle(
    profile: dict[str, Any],
    length: int,
    sample_rate: int,
    rng: Pcg32,
) -> list[float]:
    config = profile["micro_buckle"]
    count = int(config["count"])
    duration_low, duration_high = map(float, config["duration_ms"])
    amplitude = float(config["amplitude"])
    output = [0.0] * length
    for buckle_index in range(count):
        lane = (buckle_index + 1) / (count + 1)
        center_position = max(0.08, min(0.88, lane + rng.uniform(-0.11, 0.11)))
        start = int(center_position * length)
        buckle_length = max(
            3,
            int(rng.uniform(duration_low, duration_high) * sample_rate / 1000.0),
        )
        start_frequency = rng.uniform(650.0, 1700.0)
        end_frequency = rng.uniform(2200.0, 6200.0)
        phase = rng.uniform(0.0, _TAU)
        gain = amplitude * rng.uniform(0.7, 1.0)
        accumulated_phase = phase
        for local_index in range(buckle_length):
            index = start + local_index
            if index >= length:
                break
            position = local_index / max(1, buckle_length - 1)
            frequency = start_frequency + (
                end_frequency - start_frequency
            ) * position
            accumulated_phase += _TAU * frequency / sample_rate
            envelope = math.sin(math.pi * position) ** 1.4
            noisy_fold = math.tanh(
                1.8 * math.sin(accumulated_phase) + 0.22 * rng.signed()
            )
            output[index] += gain * envelope * noisy_fold
    return output


def _render_body_flex(
    profile: dict[str, Any],
    length: int,
    sample_rate: int,
    rng: Pcg32,
) -> list[float]:
    output = [0.0] * length
    start = int(rng.uniform(0.07, 0.14) * length)
    for mode in profile["body_modes"]:
        frequency = float(mode["frequency_hz"]) * rng.uniform(0.985, 1.015)
        amplitude = float(mode["amplitude"]) * rng.uniform(0.9, 1.08)
        decay_seconds = float(mode["decay_ms"]) / 1000.0
        phase = rng.uniform(-0.18, 0.18)
        for index in range(start, length):
            elapsed = (index - start) / sample_rate
            envelope = math.exp(-elapsed / decay_seconds)
            onset = _smoothstep(min(1.0, elapsed * sample_rate / 12.0))
            output[index] += (
                amplitude
                * envelope
                * onset
                * math.sin(_TAU * frequency * elapsed + phase)
            )
    return output


def _render_landing_slap(
    profile: dict[str, Any],
    length: int,
    sample_rate: int,
    rng: Pcg32,
) -> list[float]:
    config = profile["landing"]
    center_position = float(config["position"]) + rng.uniform(-0.012, 0.012)
    start = int(max(0.0, min(0.97, center_position)) * length)
    amplitude = float(config["amplitude"]) * rng.uniform(0.88, 1.08)
    decay_seconds = float(config["decay_ms"]) / 1000.0
    frequency = rng.uniform(105.0, 180.0)
    noise_state = 0.0
    noise_alpha = _lowpass_alpha(rng.uniform(1900.0, 3300.0), sample_rate)
    output = [0.0] * length
    for index in range(start, length):
        elapsed = (index - start) / sample_rate
        envelope = math.exp(-elapsed / decay_seconds)
        white = rng.signed()
        noise_state = (1.0 - noise_alpha) * white + noise_alpha * noise_state
        thump = math.sin(_TAU * frequency * elapsed) * math.exp(
            -elapsed / max(0.008, decay_seconds * 0.55)
        )
        output[index] = amplitude * envelope * (0.34 * thump + 0.66 * noise_state)
    return output


def _stereo_pan(
    mono: list[float],
    start_pan: float,
    end_pan: float,
) -> tuple[list[float], list[float]]:
    length = len(mono)
    left = [0.0] * length
    right = [0.0] * length
    for index, sample in enumerate(mono):
        position = index / max(1, length - 1)
        pan = start_pan + (end_pan - start_pan) * _smoothstep(position)
        angle = (pan + 1.0) * math.pi * 0.25
        left[index] = sample * math.cos(angle)
        right[index] = sample * math.sin(angle)
    return left, right


def _condition_stereo(
    stereo: tuple[list[float], list[float]],
    sample_rate: int,
) -> tuple[list[float], list[float]]:
    length = len(stereo[0])
    if length == 0 or len(stereo[1]) != length:
        raise BakeError("invalid stereo buffer")
    fade_in = max(1, int(sample_rate * 0.0015))
    fade_out = max(1, int(sample_rate * 0.004))
    window = [1.0] * length
    for index in range(min(fade_in, length)):
        window[index] *= _smoothstep(index / fade_in)
    for offset in range(min(fade_out, length)):
        index = length - 1 - offset
        window[index] *= _smoothstep(offset / fade_out)
    window_sum = sum(window)
    if window_sum <= 0.0:
        raise BakeError("conditioning window is empty")
    conditioned: list[list[float]] = []
    for source in stereo:
        weighted_mean = sum(
            sample * weight for sample, weight in zip(source, window)
        ) / window_sum
        channel = [
            (sample - weighted_mean) * weight
            for sample, weight in zip(source, window)
        ]
        conditioned.append(channel)
    return conditioned[0], conditioned[1]


def _mix_stereo(
    buffers: Iterable[tuple[list[float], list[float]]],
    length: int,
) -> tuple[list[float], list[float]]:
    left = [0.0] * length
    right = [0.0] * length
    for source_left, source_right in buffers:
        if len(source_left) != length or len(source_right) != length:
            raise BakeError("cannot mix buffers with different lengths")
        for index in range(length):
            left[index] += source_left[index]
            right[index] += source_right[index]
    return left, right


def _scale_stereo(
    stereo: tuple[list[float], list[float]],
    gain: float,
) -> tuple[list[float], list[float]]:
    return (
        [sample * gain for sample in stereo[0]],
        [sample * gain for sample in stereo[1]],
    )


def _peak(stereo: tuple[list[float], list[float]]) -> float:
    return max(
        max(abs(sample) for sample in stereo[0]),
        max(abs(sample) for sample in stereo[1]),
    )


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return -200.0
    return 20.0 * math.log10(value)


def _linear_true_peak(stereo: tuple[list[float], list[float]]) -> float:
    peak = _peak(stereo)
    for channel in stereo:
        for index in range(len(channel) - 1):
            first = channel[index]
            delta = channel[index + 1] - first
            for phase in (0.25, 0.5, 0.75):
                peak = max(peak, abs(first + delta * phase))
    return peak


def _measure_stereo(
    stereo: tuple[list[float], list[float]],
    sample_rate: int,
) -> dict[str, Any]:
    length = len(stereo[0])
    combined_energy = 0.0
    zero_crossings = 0
    channel_means: list[float] = []
    for channel in stereo:
        combined_energy += sum(sample * sample for sample in channel)
        channel_means.append(sum(channel) / max(1, length))
        previous = channel[0] if channel else 0.0
        for sample in channel[1:]:
            if (previous < 0.0 <= sample) or (previous >= 0.0 > sample):
                zero_crossings += 1
            previous = sample
    rms = math.sqrt(combined_energy / max(1, length * 2))
    peak = _peak(stereo)
    true_peak = _linear_true_peak(stereo)
    return {
        "frames": length,
        "duration_ms": round(length * 1000.0 / sample_rate, 6),
        "sample_rate_hz": sample_rate,
        "channels": 2,
        "peak_dbfs": round(_dbfs(peak), 6),
        "linear_true_peak_dbfs": round(_dbfs(true_peak), 6),
        "rms_dbfs": round(_dbfs(rms), 6),
        "crest_factor_db": round(_dbfs(peak / max(rms, 1.0e-12)), 6),
        "max_dc_offset": round(max(abs(value) for value in channel_means), 12),
        "zero_crossings": zero_crossings,
        "clipped_samples": sum(
            1 for channel in stereo for sample in channel if abs(sample) >= 1.0
        ),
    }


def _wav_pcm24_bytes(
    stereo: tuple[list[float], list[float]],
    sample_rate: int,
    dither_rng: Pcg32,
) -> bytes:
    if len(stereo[0]) != len(stereo[1]):
        raise BakeError("stereo channels have different lengths")
    payload = bytearray()
    for left, right in zip(stereo[0], stereo[1]):
        for sample in (left, right):
            if not math.isfinite(sample):
                raise BakeError("render contains a non-finite sample")
            dither = dither_rng.random() - dither_rng.random()
            quantized = int(round(sample * _PCM24_MAX + dither))
            quantized = max(_PCM24_MIN, min(_PCM24_MAX, quantized))
            packed = quantized & 0xFFFFFF
            payload.extend(
                (packed & 0xFF, (packed >> 8) & 0xFF, (packed >> 16) & 0xFF)
            )
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(3)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(payload))
    return output.getvalue()


def _render_variant(
    recipe_id: str,
    user_seed: int,
    profile: dict[str, Any],
    variant: int,
    sample_rate: int,
) -> tuple[
    dict[str, tuple[list[float], list[float]]],
    tuple[list[float], list[float]],
    float,
]:
    profile_id = str(profile["id"])
    length = round(float(profile["duration_ms"]) * sample_rate / 1000.0)
    if length < 2:
        raise BakeError(f"profile {profile_id} is too short")
    renderers = {
        "friction": _render_friction,
        "fiber_grains": _render_fiber_grains,
        "micro_buckle": _render_micro_buckle,
        "body_flex": _render_body_flex,
        "landing_slap": _render_landing_slap,
    }
    start_pan = float(profile["pan"]["start"])
    end_pan = float(profile["pan"]["end"])
    layers: dict[str, tuple[list[float], list[float]]] = {}
    for layer_name in _LAYERS:
        rng = _domain_rng(
            recipe_id,
            user_seed,
            profile_id,
            variant,
            f"layer:{layer_name}",
        )
        mono = renderers[layer_name](profile, length, sample_rate, rng)
        layers[layer_name] = _condition_stereo(
            _stereo_pan(mono, start_pan, end_pan),
            sample_rate,
        )

    raw_master = _mix_stereo(layers.values(), length)
    raw_peak = _peak(raw_master)
    if raw_peak <= 1.0e-9:
        raise BakeError(f"profile {profile_id} variant {variant} is silent")
    target_peak = 10.0 ** (float(profile["target_peak_dbfs"]) / 20.0)
    gain = target_peak / raw_peak
    scaled_layers = {
        name: _scale_stereo(buffer, gain) for name, buffer in layers.items()
    }
    master = _mix_stereo(scaled_layers.values(), length)
    if _peak(master) >= 1.0:
        raise BakeError(f"profile {profile_id} variant {variant} clips")
    return scaled_layers, master, gain


def _output_record(
    relative_path: str,
    kind: str,
    profile: dict[str, Any],
    variant: int,
    wav_data: bytes,
    measurements: dict[str, Any],
    component: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": relative_path,
        "kind": kind,
        "profile_id": profile["id"],
        "cue_id": profile["cue_id"],
        "variant": variant,
        "sha256": _sha256_bytes(wav_data),
        "size_bytes": len(wav_data),
        "audio": measurements,
    }
    if component is not None:
        record["component"] = component
    return record


def _commit_files(
    output_root: Path,
    files: dict[str, bytes],
    allow_overwrite: bool,
) -> None:
    conflicts: list[str] = []
    for relative_path, content in files.items():
        destination = output_root / relative_path
        if destination.exists() and destination.read_bytes() != content:
            conflicts.append(relative_path)
    if conflicts and not allow_overwrite:
        joined = ", ".join(sorted(conflicts)[:8])
        raise BakeError(
            "refusing to overwrite divergent evidence; review it and pass "
            f"allow_overwrite=True: {joined}"
        )
    for relative_path, content in sorted(files.items()):
        destination = output_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)


def bake_recipe(
    recipe: dict[str, Any],
    output_root: Path | str,
    *,
    write_stems: bool = True,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    recipe = _validate_recipe(recipe)
    recipe_sha256 = _sha256_bytes(_canonical_json(recipe))
    recipe_id = str(recipe["recipe_id"])
    render = recipe["render"]
    sample_rate = int(render["sample_rate_hz"])
    user_seed = int(render["user_seed"])
    variants_per_profile = int(render["variants_per_profile"])
    pending_files: dict[str, bytes] = {}
    output_records: list[dict[str, Any]] = []
    profile_summaries: list[dict[str, Any]] = []

    for profile in recipe["profiles"]:
        profile_measurements: list[dict[str, Any]] = []
        for variant in range(1, variants_per_profile + 1):
            layers, master, normalization_gain = _render_variant(
                recipe_id,
                user_seed,
                profile,
                variant,
                sample_rate,
            )
            base_name = f"page_turn_{profile['id']}_{variant:02d}"
            master_path = f"masters/{base_name}.wav"
            master_rng = _domain_rng(
                recipe_id,
                user_seed,
                str(profile["id"]),
                variant,
                "dither:master",
            )
            master_bytes = _wav_pcm24_bytes(master, sample_rate, master_rng)
            master_measurements = _measure_stereo(master, sample_rate)
            pending_files[master_path] = master_bytes
            output_records.append(
                _output_record(
                    master_path,
                    "master",
                    profile,
                    variant,
                    master_bytes,
                    master_measurements,
                )
            )
            profile_measurements.append(
                {
                    "variant": variant,
                    "normalization_gain": round(normalization_gain, 12),
                    **master_measurements,
                }
            )

            if not write_stems:
                continue
            for layer_name in _LAYERS:
                stem = layers[layer_name]
                stem_path = (
                    f"stems/{profile['id']}_{variant:02d}/{layer_name}.wav"
                )
                stem_rng = _domain_rng(
                    recipe_id,
                    user_seed,
                    str(profile["id"]),
                    variant,
                    f"dither:stem:{layer_name}",
                )
                stem_bytes = _wav_pcm24_bytes(stem, sample_rate, stem_rng)
                pending_files[stem_path] = stem_bytes
                output_records.append(
                    _output_record(
                        stem_path,
                        "stem",
                        profile,
                        variant,
                        stem_bytes,
                        _measure_stereo(stem, sample_rate),
                        layer_name,
                    )
                )

                ablation = _mix_stereo(
                    (
                        buffer
                        for name, buffer in layers.items()
                        if name != layer_name
                    ),
                    len(master[0]),
                )
                ablation_path = (
                    f"ablations/{profile['id']}_{variant:02d}/"
                    f"without_{layer_name}.wav"
                )
                ablation_rng = _domain_rng(
                    recipe_id,
                    user_seed,
                    str(profile["id"]),
                    variant,
                    f"dither:ablation:without:{layer_name}",
                )
                ablation_bytes = _wav_pcm24_bytes(
                    ablation,
                    sample_rate,
                    ablation_rng,
                )
                pending_files[ablation_path] = ablation_bytes
                output_records.append(
                    _output_record(
                        ablation_path,
                        "ablation",
                        profile,
                        variant,
                        ablation_bytes,
                        _measure_stereo(ablation, sample_rate),
                        f"without_{layer_name}",
                    )
                )
        profile_summaries.append(
            {
                "profile_id": profile["id"],
                "cue_id": profile["cue_id"],
                "target_peak_dbfs": profile["target_peak_dbfs"],
                "variants": profile_measurements,
            }
        )

    kind_counts = {
        kind: sum(1 for record in output_records if record["kind"] == kind)
        for kind in ("master", "stem", "ablation")
    }
    manifest_rights = dict(recipe["rights"])
    manifest_rights["publication_eligible"] = False
    manifest_rights["publication_blockers"] = [
        "project_output_audio_grant_unknown"
    ]
    manifest: dict[str, Any] = {
        "schema": "sonic-ui-foley-bake-manifest/v1",
        "recipe_id": recipe_id,
        "recipe_sha256": recipe_sha256,
        "created_date": recipe["created_date"],
        "generator": {
            "id": GENERATOR_ID,
            "version": GENERATOR_VERSION,
            "runtime_dependencies": ["python-standard-library"],
            "training_required": False,
            "model_required": False,
        },
        "determinism": {
            "prng": "PCG-XSH-RR-32",
            "domain_derivation": "SHA-256 named domains",
            "dither": "deterministic TPDF at one PCM24 LSB",
            "overwrite_policy": "byte-identical verify or explicit reviewed overwrite",
        },
        "render": {
            "sample_rate_hz": sample_rate,
            "channels": 2,
            "sample_format": "PCM_S24LE",
            "variants_per_profile": variants_per_profile,
            "user_seed": user_seed,
        },
        "rights": manifest_rights,
        "profiles": profile_summaries,
        "outputs": sorted(output_records, key=lambda record: record["path"]),
        "summary": {
            "profile_count": len(recipe["profiles"]),
            "master_count": kind_counts["master"],
            "stem_count": kind_counts["stem"],
            "ablation_count": kind_counts["ablation"],
            "supporting_evidence_written": write_stems,
            "recorded_parent_count": 0,
            "external_asset_count": 0,
        },
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    pending_files["manifest.json"] = manifest_bytes
    _commit_files(Path(output_root), pending_files, allow_overwrite)
    return manifest
