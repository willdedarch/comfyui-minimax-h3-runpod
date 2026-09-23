"""Bounded reference decode: streaming resize/CFR first, then paired AV trimming.

FFmpeg uses source timestamps to normalize variable-frame-rate video before
ComfyUI materializes any IMAGE tensor. The temporary FFV1/PCM file introduces no
additional lossy video compression. H3 accepts 5 + 17*k frames, so up to 16 final
normalized frames are omitted, together with the corresponding audio tail.
This is reference conditioning, not an export of the user's original footage.
"""
from __future__ import annotations

import math
import json
from pathlib import Path
import subprocess
import tempfile

MAX_PIXELS = 1280 * 768
MAX_DURATION = 15.05


def _run_media(command, timeout=180):
    try:
        return subprocess.run(command, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("A preparação da referência excedeu o tempo limite.") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("Não foi possível preparar esta referência de vídeo. Verifique o arquivo enviado.") from exc


def normalize_reference(source, destination):
    """Stream source into a bounded, lossless, constant-24-fps intermediate."""
    probe = _run_media([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "v:0", "-show_entries",
        "format=duration:stream=duration,width,height", "-of", "json", str(source)], 25)
    info = json.loads(probe.stdout)
    streams = info.get("streams", [])
    if not streams:
        raise ValueError("A referência selecionada não contém vídeo.")
    stream = streams[0]
    durations = (stream.get("duration"), info.get("format", {}).get("duration"))
    duration = None
    for value in durations:
        try:
            duration = float(value)
            break
        except (TypeError, ValueError):
            continue
    if duration is None or not math.isfinite(duration) or not 2 <= duration <= MAX_DURATION:
        raise ValueError("A referência de vídeo precisa ter entre 2 e 15 segundos.")
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    if min(width, height) <= 0 or width * height > 3840 * 2160:
        raise ValueError("Use uma referência de vídeo com dimensões válidas, até 4K.")
    # Scaling is applied while decoding each frame. Never build a full 4K
    # float tensor and resize it afterwards. Quoting here is FFmpeg filter
    # syntax; subprocess receives separate arguments and does not use a shell.
    factor = f"min(1,sqrt({MAX_PIXELS}/(iw*ih)))"
    scale = (f"scale=w='max(32,trunc(iw*{factor}/32)*32)':"
             f"h='max(32,trunc(ih*{factor}/32)*32)':flags=lanczos")
    _run_media([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file,pipe", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
        "-vf", "setpts=PTS-STARTPTS,fps=fps=24:start_time=0," + scale,
        "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0",
        "-af", "aresample=32000:async=1:first_pts=0", "-ac", "2", "-c:a", "pcm_s16le",
        "-t", str(MAX_DURATION), str(destination)])


def frame_indices(count, source_fps):
    if type(count) is not int or count <= 0 or not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("A referência não possui quadros ou frequência válidos.")
    duration = count / source_fps
    if not 2 <= duration <= 15.05:
        raise ValueError("A referência de vídeo precisa ter entre 2 e 15 segundos.")
    length = round(duration * 24)
    return [min(count - 1, int(i * source_fps / 24)) for i in range(length)]


def legal_frame_count(count):
    if type(count) is not int or count < 5:
        raise ValueError("A referência não possui quadros suficientes para o H3.")
    return count - (count - 5) % 17


class H3MAXReferenceVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"file": ("STRING",)}}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "load"
    CATEGORY = "H3 MAX"

    @classmethod
    def IS_CHANGED(cls, file):
        import folder_paths
        from .studio_routes import input_path
        stat = input_path(folder_paths.get_input_directory(), file).stat()
        return (stat.st_mtime_ns, stat.st_size)

    def load(self, file):
        import folder_paths
        from comfy_api.latest import InputImpl
        from .studio_routes import input_path
        path = input_path(folder_paths.get_input_directory(), file)
        with tempfile.TemporaryDirectory(prefix="h3max-reference-") as temporary:
            normalized = Path(temporary) / "reference.mkv"
            normalize_reference(path, normalized)
            video = InputImpl.VideoFromFile(str(normalized))
            count = video.get_frame_count()
            rate = float(video.get_frame_rate())
            # FFmpeg's fps filter owns timing; average-FPS index selection is
            # not a valid VFR conversion. Fail rather than apply that shortcut.
            if not math.isclose(rate, 24.0, abs_tol=1e-6):
                raise ValueError("A normalização da referência não produziu 24 fps.")
            target = legal_frame_count(len(frame_indices(count, rate)))
            components = InputImpl.VideoFromFile(
                str(normalized), duration=target / 24).get_components()
            # Metadata may round a frame count up. Match both streams to the
            # decoded legal frame count, not to the optimistic metadata.
            actual = legal_frame_count(min(target, int(components.images.shape[0])))
            images = components.images[:actual]
            audio = components.audio
            if audio is not None:
                audio = dict(audio)
                sample_count = round(actual / 24 * audio["sample_rate"])
                audio["waveform"] = audio["waveform"][..., :sample_count]
            # No fabricated soundtrack for a silent video: Ref2VA accepts None.
            return (images, audio)
