from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .errors import AudioFormatError, ManifestError
from .io import (
    amplitude_to_db,
    portable_relative_path,
    read_wav_mono,
    sha256_file,
    write_stable_json,
    write_wav_pcm24,
)
from .rights import RightsAsset, RightsReport, publication_rights, validate_rights


RECIPE_SCHEMA = "sonic-impact-recipe/v1"
REPORT_SCHEMA = "sonic-impact-analysis/v1"
ALGORITHM_VERSION = "modal-residual-numpy/0.1"
MIN_MODES = 6
MAX_MODES = 12
MIN_ROUGHNESS_BANDS = 2
MAX_ROUGHNESS_BANDS = 4


@dataclass(frozen=True)
class AnalysisOptions:
    transient_ms: float = 20.0
    mode_count: int = 8
    roughness_band_count: int = 4
    max_seconds: float = 2.0
    source_material: str = "unknown-source"
    target_material: str = "unknown-target"

    def validate(self) -> None:
        if not 2.0 <= self.transient_ms <= 100.0:
            raise ManifestError("transient_ms must be in [2, 100]")
        if not MIN_MODES <= self.mode_count <= MAX_MODES:
            raise ManifestError(f"mode_count must be in [{MIN_MODES}, {MAX_MODES}]")
        if not MIN_ROUGHNESS_BANDS <= self.roughness_band_count <= MAX_ROUGHNESS_BANDS:
            raise ManifestError(
                f"roughness_band_count must be in [{MIN_ROUGHNESS_BANDS}, {MAX_ROUGHNESS_BANDS}]"
            )
        if not 0.1 <= self.max_seconds <= 2.0:
            raise ManifestError("max_seconds must be in [0.1, 2.0]")
        if not self.source_material.strip() or not self.target_material.strip():
            raise ManifestError("source_material and target_material must be non-empty")


@dataclass(frozen=True)
class _PreparedSignal:
    source_path: Path
    sha256: str
    onset_frame: int
    signal: np.ndarray


def _next_power_of_two(value: int) -> int:
    return 1 << max(0, (value - 1).bit_length())


def _detect_onset(signal: np.ndarray, sample_rate: int) -> int:
    absolute = np.abs(signal)
    window = max(1, int(round(sample_rate * 0.0005)))
    kernel = np.ones(window, dtype=np.float64) / window
    envelope = np.convolve(absolute, kernel, mode="same")
    noise_frames = min(len(envelope), max(32, int(sample_rate * 0.01)))
    # Tight game-SFX cuts often contain the onset inside the first 10 ms.  A
    # low percentile estimates the quiet floor without letting that onset
    # inflate the threshold and make the detector circular.
    noise_level = float(np.percentile(envelope[:noise_frames], 15.0))
    peak = float(np.max(envelope))
    threshold = max(noise_level * 8.0, peak * 0.03, 1e-6)
    hits = np.flatnonzero(envelope >= threshold)
    if hits.size == 0:
        raise AudioFormatError("impact onset could not be detected")
    pre_roll = int(round(sample_rate * 0.0005))
    return max(0, int(hits[0]) - pre_roll)


def _prepare_paths(
    paths: Iterable[Path], sample_rate: int | None, max_seconds: float
) -> tuple[int, list[_PreparedSignal]]:
    prepared: list[_PreparedSignal] = []
    expected_rate = sample_rate
    for path in paths:
        resolved = path.resolve()
        rate, signal = read_wav_mono(resolved)
        if expected_rate is None:
            expected_rate = rate
        elif rate != expected_rate:
            raise AudioFormatError(
                f"all analysis WAVs must share one sample rate; {resolved} is {rate}, expected {expected_rate}"
            )
        # Median is robust to an onset that lands inside this short baseline
        # window; a mean would turn the impact energy into a false DC offset.
        signal = signal - float(np.median(signal[: min(len(signal), max(1, rate // 200))]))
        onset = _detect_onset(signal, rate)
        max_frames = int(round(max_seconds * rate))
        aligned = signal[onset : onset + max_frames].copy()
        if aligned.size < int(rate * 0.05):
            raise AudioFormatError(f"impact is shorter than 50 ms after onset: {resolved}")
        prepared.append(
            _PreparedSignal(
                source_path=resolved,
                sha256=sha256_file(resolved),
                onset_frame=onset,
                signal=aligned,
            )
        )
    if expected_rate is None or not prepared:
        raise ManifestError("at least one impact WAV is required")
    return expected_rate, prepared


def _spectral_frames(signal: np.ndarray, nfft: int, hop: int) -> np.ndarray:
    if len(signal) < nfft:
        padded = np.zeros(nfft, dtype=np.float64)
        padded[: len(signal)] = signal
        return np.abs(np.fft.rfft(padded * np.hanning(nfft)))[None, :]
    frames = []
    for start in range(0, len(signal) - nfft + 1, hop):
        frames.append(np.abs(np.fft.rfft(signal[start : start + nfft] * np.hanning(nfft))))
        if len(frames) >= 32:
            break
    return np.asarray(frames)


def _estimate_t60(signal: np.ndarray, sample_rate: int, frequency_hz: float) -> float:
    nfft = min(4096, _next_power_of_two(max(512, min(len(signal), 4096))))
    nfft = max(512, nfft)
    hop = max(64, nfft // 4)
    frames = _spectral_frames(signal, nfft, hop)
    frequencies = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
    index = int(np.argmin(np.abs(frequencies - frequency_hz)))
    magnitude = np.maximum(frames[:, index], 1e-12)
    db = np.asarray(amplitude_to_db(magnitude), dtype=np.float64)
    db -= float(np.max(db))
    times = (np.arange(len(db), dtype=np.float64) * hop + nfft / 2) / sample_rate
    usable = (db <= -3.0) & (db >= -45.0)
    if np.count_nonzero(usable) < 4:
        usable = db >= -45.0
    if np.count_nonzero(usable) >= 4:
        slope, _ = np.polyfit(times[usable], db[usable], 1)
        if slope < -1.0:
            return float(np.clip(-60.0 / slope, 0.02, 2.0))
    return 0.18


def _candidate_modes(
    signal: np.ndarray,
    sample_rate: int,
    transient_frames: int,
    requested: int,
    variant_index: int,
) -> list[dict[str, float | int]]:
    decay = signal[min(transient_frames, len(signal) - 1) :]
    target_nfft = min(16384, max(1024, _next_power_of_two(min(len(decay), 16384))))
    nfft = target_nfft
    hop = max(128, nfft // 4)
    frames = _spectral_frames(decay, nfft, hop)
    weights = np.linspace(1.0, 0.35, len(frames), dtype=np.float64)[:, None]
    spectrum = np.sqrt(np.average(np.square(frames), axis=0, weights=weights[:, 0]))
    frequencies = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
    valid = (frequencies >= 40.0) & (frequencies <= min(18_000.0, 0.45 * sample_rate))
    local = np.zeros_like(valid)
    local[1:-1] = (spectrum[1:-1] > spectrum[:-2]) & (spectrum[1:-1] >= spectrum[2:])
    ranked = list(np.flatnonzero(valid & local))
    ranked.sort(key=lambda index: float(spectrum[index]), reverse=True)
    fallback = list(np.flatnonzero(valid))
    fallback.sort(key=lambda index: float(spectrum[index]), reverse=True)
    selected: list[int] = []
    for index in ranked + fallback:
        frequency = float(frequencies[index])
        if all(
            abs(1200.0 * math.log2(frequency / float(frequencies[other]))) >= 45.0
            for other in selected
        ):
            selected.append(index)
        if len(selected) >= max(requested * 3, MAX_MODES):
            break
    peak_score = max((float(spectrum[index]) for index in selected), default=1.0)
    result = []
    for index in selected:
        frequency = float(frequencies[index])
        result.append(
            {
                "frequency_hz": frequency,
                "t60_s": _estimate_t60(decay, sample_rate, frequency),
                "score": float(spectrum[index] / max(peak_score, 1e-12)),
                "variant": variant_index,
            }
        )
    return result


def _cluster_modes(
    signals: list[np.ndarray],
    sample_rate: int,
    transient_frames: int,
    count: int,
    role: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, float | int]] = []
    for variant, signal in enumerate(signals):
        candidates.extend(
            _candidate_modes(signal, sample_rate, transient_frames, count, variant)
        )
    candidates.sort(key=lambda item: float(item["score"]), reverse=True)
    clusters: list[list[dict[str, float | int]]] = []
    for candidate in candidates:
        frequency = float(candidate["frequency_hz"])
        match = None
        for cluster in clusters:
            center = float(np.median([float(item["frequency_hz"]) for item in cluster]))
            if abs(1200.0 * math.log2(frequency / center)) < 45.0:
                match = cluster
                break
        if match is None:
            clusters.append([candidate])
        else:
            match.append(candidate)
    clusters.sort(
        key=lambda cluster: (
            len({int(item["variant"]) for item in cluster}),
            max(float(item["score"]) for item in cluster),
        ),
        reverse=True,
    )
    chosen = clusters[:count]
    if len(chosen) < count:
        raise AudioFormatError(
            f"analysis found only {len(chosen)} stable frequency regions; need {count}"
        )
    raw_weights = np.asarray(
        [max(float(item["score"]) for item in cluster) for cluster in chosen],
        dtype=np.float64,
    )
    raw_weights = np.maximum(raw_weights, 1e-4)
    target_amplitudes = 0.18 * raw_weights / float(np.sum(raw_weights))
    modes: list[dict[str, Any]] = []
    for cluster, target_amplitude in zip(chosen, target_amplitudes, strict=True):
        weights = np.asarray([float(item["score"]) for item in cluster], dtype=np.float64)
        frequencies = np.asarray(
            [float(item["frequency_hz"]) for item in cluster], dtype=np.float64
        )
        t60_values = np.asarray([float(item["t60_s"]) for item in cluster], dtype=np.float64)
        frequency = float(np.average(frequencies, weights=np.maximum(weights, 1e-6)))
        t60 = float(np.median(t60_values))
        recurrence_gain = float(
            target_amplitude * max(0.05, abs(math.sin(2.0 * math.pi * frequency / sample_rate)))
        )
        modes.append(
            {
                "frequency_hz": round(frequency, 6),
                "t60_ms": round(float(np.clip(t60 * 1000.0, 20.0, 2000.0)), 6),
                "gain": round(recurrence_gain, 9),
                "role": role,
                "confidence": round(
                    len({int(item["variant"]) for item in cluster}) / len(signals), 6
                ),
            }
        )
    return sorted(modes, key=lambda item: item["frequency_hz"])


def _roughness_bands(
    signals: list[np.ndarray],
    sample_rate: int,
    modes: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    max_length = max(len(signal) for signal in signals)
    average = np.zeros(max_length, dtype=np.float64)
    for signal in signals:
        average[: len(signal)] += signal
    average /= len(signals)
    low = 150.0
    high = min(16_000.0, 0.44 * sample_rate)
    if high <= low * 1.5:
        low = max(40.0, high / 8.0)
    edges = np.geomspace(low, high, count + 1)
    knot_ms = np.asarray([0.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0])
    result: list[dict[str, Any]] = []
    for band_index in range(count):
        band_low = float(edges[band_index])
        band_high = float(edges[band_index + 1])
        center = math.sqrt(band_low * band_high)
        q = float(np.clip(center / max(1.0, band_high - band_low), 0.3, 8.0))
        envelope_db: list[float] = []
        for knot in knot_ms:
            center_frame = int(round(knot * sample_rate / 1000.0))
            frame_count = max(128, int(round(0.02 * sample_rate)))
            start = max(0, center_frame - frame_count // 4)
            segment = average[start : min(len(average), start + frame_count)]
            if len(segment) < 32:
                level_db = -96.0
            else:
                nfft = max(128, _next_power_of_two(len(segment)))
                windowed = np.zeros(nfft, dtype=np.float64)
                windowed[: len(segment)] = segment * np.hanning(len(segment))
                spectrum = np.abs(np.fft.rfft(windowed)) / max(1, len(segment))
                frequencies = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
                mask = (frequencies >= band_low) & (frequencies < band_high)
                for mode in modes:
                    frequency = float(mode["frequency_hz"])
                    mask &= np.abs(frequencies - frequency) > max(30.0, frequency * 0.03)
                energy = float(np.sqrt(np.sum(np.square(spectrum[mask])))) if np.any(mask) else 0.0
                level_db = float(amplitude_to_db(energy)) - 12.0
            envelope_db.append(round(float(np.clip(level_db, -96.0, -18.0)), 6))
        result.append(
            {
                "center_hz": round(center, 6),
                "q": round(q, 6),
                "envelope": [
                    {"time_ms": float(time_ms), "level_db": level}
                    for time_ms, level in zip(knot_ms, envelope_db, strict=True)
                ],
            }
        )
    return result


def _rights_for_inputs(
    paths: list[_PreparedSignal],
    tap_paths: list[_PreparedSignal],
    rights_manifest: Path | None,
    rights_root: Path | None,
) -> tuple[dict[str, Any], dict[str, RightsAsset]]:
    all_prepared = paths + tap_paths
    if rights_manifest is None:
        rights = publication_rights(
            review_state="unreviewed-local-only",
            parent_publication_eligible=False,
        )
        rights["rights_manifest_sha256"] = None
        return (
            rights,
            {},
        )
    report: RightsReport = validate_rights(
        rights_manifest, root=rights_root, target="parameter-fit"
    )
    matched: dict[str, RightsAsset] = {}
    for prepared in all_prepared:
        asset = report.asset_for_hash(prepared.sha256)
        if asset is None:
            raise ManifestError(
                f"rights manifest does not inventory analysis input SHA-256 {prepared.sha256}"
            )
        matched[prepared.sha256] = asset
    parent_publication_eligible = all(
        asset.actions["standalone_baked_audio_distribution"] == "allow"
        and asset.actions["material_kit_distribution"] == "allow"
        for asset in matched.values()
    )
    rights = publication_rights(
        review_state="validated",
        parent_publication_eligible=parent_publication_eligible,
    )
    rights["rights_manifest_sha256"] = sha256_file(rights_manifest)
    rights["rights_pack_id"] = report.pack_id
    return (
        rights,
        matched,
    )


def analyze_impacts(
    input_paths: list[Path],
    output_dir: Path,
    *,
    options: AnalysisOptions | None = None,
    source_taps: list[Path] | None = None,
    target_taps: list[Path] | None = None,
    rights_manifest: Path | None = None,
    rights_root: Path | None = None,
) -> dict[str, Any]:
    options = options or AnalysisOptions()
    options.validate()
    if not 1 <= len(input_paths) <= 3:
        raise ManifestError("analysis requires 1 to 3 impact WAVs")
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ManifestError(f"output directory must be empty: {output_dir}")
    sample_rate, impacts = _prepare_paths(input_paths, None, options.max_seconds)
    _, source_prepared = _prepare_paths(source_taps or [], sample_rate, options.max_seconds) if source_taps else (sample_rate, [])
    _, target_prepared = _prepare_paths(target_taps or [], sample_rate, options.max_seconds) if target_taps else (sample_rate, [])
    all_signals = impacts + source_prepared + target_prepared
    peak = max(float(np.max(np.abs(item.signal))) for item in all_signals)
    calibration_gain = min(1.0, 0.65 / max(peak, 1e-12))
    impacts = [
        _PreparedSignal(item.source_path, item.sha256, item.onset_frame, item.signal * calibration_gain)
        for item in impacts
    ]
    source_prepared = [
        _PreparedSignal(item.source_path, item.sha256, item.onset_frame, item.signal * calibration_gain)
        for item in source_prepared
    ]
    target_prepared = [
        _PreparedSignal(item.source_path, item.sha256, item.onset_frame, item.signal * calibration_gain)
        for item in target_prepared
    ]
    transient_frames = max(1, int(round(options.transient_ms * sample_rate / 1000.0)))
    if source_prepared or target_prepared:
        source_count = options.mode_count // 2 if source_prepared else 0
        target_count = options.mode_count - source_count if target_prepared else 0
        if source_prepared and not target_prepared:
            source_count = options.mode_count
        if target_prepared and not source_prepared:
            target_count = options.mode_count
        modes = []
        if source_prepared:
            modes.extend(
                _cluster_modes(
                    [item.signal for item in source_prepared],
                    sample_rate,
                    transient_frames,
                    source_count,
                    "source-body",
                )
            )
        if target_prepared:
            modes.extend(
                _cluster_modes(
                    [item.signal for item in target_prepared],
                    sample_rate,
                    transient_frames,
                    target_count,
                    "target-response",
                )
            )
    else:
        modes = _cluster_modes(
            [item.signal for item in impacts],
            sample_rate,
            transient_frames,
            options.mode_count,
            "pair-body",
        )
    roughness = _roughness_bands(
        [item.signal for item in impacts], sample_rate, modes, options.roughness_band_count
    )
    rights, matched_rights = _rights_for_inputs(
        impacts, source_prepared + target_prepared, rights_manifest, rights_root
    )
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sample_pool = []
    transients = []
    for index, prepared in enumerate(impacts):
        sample_path = audio_dir / f"sample-{index}.wav"
        transient_path = audio_dir / f"transient-{index}.wav"
        transient = prepared.signal[:transient_frames].copy()
        fade_frames = min(len(transient), max(1, int(round(sample_rate * 0.002))))
        transient[-fade_frames:] *= np.linspace(1.0, 0.0, fade_frames, endpoint=True)
        write_wav_pcm24(sample_path, sample_rate, prepared.signal)
        write_wav_pcm24(transient_path, sample_rate, transient)
        asset = matched_rights.get(prepared.sha256)
        sample_pool.append(
            {
                "path": portable_relative_path(sample_path, output_dir),
                "sha256": sha256_file(sample_path),
                "source_sha256": prepared.sha256,
                "rights_asset_id": asset.asset_id if asset else None,
            }
        )
        transients.append(
            {
                "path": portable_relative_path(transient_path, output_dir),
                "sha256": sha256_file(transient_path),
                "source_sha256": prepared.sha256,
                "rights_asset_id": asset.asset_id if asset else None,
            }
        )
    duration_ms = min(
        options.max_seconds * 1000.0,
        max(len(item.signal) for item in impacts) * 1000.0 / sample_rate,
    )
    recipe: dict[str, Any] = {
        "schema": RECIPE_SCHEMA,
        "status": "experimental",
        "event": "impact",
        "source_material": options.source_material,
        "target_material": options.target_material,
        "sample_rate": sample_rate,
        "algorithm": {
            "id": ALGORITHM_VERSION,
            "analysis_backend": "numpy-fft-no-training",
            "deterministic": True,
        },
        "rights": rights,
        "sample_pool": sample_pool,
        "transients": transients,
        "modal_body": {
            "mode_count": len(modes),
            "modes": modes,
            "excitation_pulse": [1.0, -0.45],
        },
        "roughness": {
            "band_count": len(roughness),
            "bands": roughness,
            "seed_namespace": "sonic-matter/impact-roughness/v1",
        },
        "mix": {
            "transient_gain_db": 0.0,
            "body_gain_db": 0.0,
            "roughness_gain_db": -3.0,
            "master_gain_db": -9.0,
        },
        "safety": {
            "peak_limit": 0.98,
            "max_render_ms": 2000.0,
            "mode_frequency_hz": [40.0, min(18_000.0, 0.45 * sample_rate)],
            "mode_t60_ms": [20.0, 2000.0],
            "roughness_q": [0.3, 8.0],
        },
        "render": {
            "duration_ms": round(duration_ms, 6),
            "variant_count": len(impacts),
            "pcm": "mono-signed-24-bit",
        },
    }
    recipe_path = output_dir / "recipe.json"
    write_stable_json(recipe_path, recipe)
    report = {
        "schema": REPORT_SCHEMA,
        "algorithm": ALGORITHM_VERSION,
        "recipe_sha256": sha256_file(recipe_path),
        "sample_rate": sample_rate,
        "input_calibration_gain_db": round(
            20.0 * math.log10(max(calibration_gain, 1e-12)), 6
        ),
        "inputs": [
            {
                "filename": item.source_path.name,
                "sha256": item.sha256,
                "onset_frame": item.onset_frame,
                "analyzed_frames": len(item.signal),
            }
            for item in impacts
        ],
        "source_taps": [item.sha256 for item in source_prepared],
        "target_taps": [item.sha256 for item in target_prepared],
        "mode_count": len(modes),
        "roughness_band_count": len(roughness),
        "publication_eligible": rights["publication_eligible"],
        "limitations": [
            "Mode identity is an FFT/decay estimate, not a physical-material ground truth.",
            "Without separate source/target taps, modes are labelled pair-body and are not decomposed.",
            "No trained model, neural inference, or automatic rights inference is used.",
        ],
    }
    write_stable_json(output_dir / "analysis-report.json", report)
    return {
        "recipe": recipe_path,
        "report": output_dir / "analysis-report.json",
        "recipe_sha256": report["recipe_sha256"],
        "mode_count": len(modes),
        "roughness_band_count": len(roughness),
        "publication_eligible": rights["publication_eligible"],
    }
