"""Lossless audio upload validation and browser-playback conversion."""

import json
import mimetypes
import os
import subprocess
import uuid

from flask import current_app

from backend.admin.settings import sanitize_upload_filename
from backend.core.models import AudioPlaybackVariant, FileRecord, db


class AudioProcessingError(ValueError):
    """An uploaded file could not be validated or converted safely."""


def _run_media_command(command, timeout=None):
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout or current_app.config['AUDIO_PROCESS_TIMEOUT_SECONDS'],
        )
    except FileNotFoundError as error:
        raise AudioProcessingError(f'缺少音频处理程序：{command[0]}。') from error
    except subprocess.TimeoutExpired as error:
        raise AudioProcessingError('音频处理超时，请尝试较短的文件。') from error


def probe_audio(path):
    """Return the first real audio stream reported by ffprobe."""
    result = _run_media_command(
        [
            current_app.config['FFPROBE_BINARY'],
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=codec_name,sample_fmt,sample_rate,channels,bits_per_raw_sample',
            '-show_entries',
            'format=format_name',
            '-of',
            'json',
            path,
        ],
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or '').strip().splitlines()
        raise AudioProcessingError(detail[-1] if detail else '文件不是可解码的音频。')
    try:
        payload = json.loads(result.stdout or '{}')
        stream = (payload.get('streams') or [])[0]
    except (ValueError, IndexError, TypeError) as error:
        raise AudioProcessingError('文件中没有可用的音频轨道。') from error
    stream['format_name'] = (payload.get('format') or {}).get('format_name', '')
    return stream


def _pcm_codec_for_stream(stream):
    sample_format = str(stream.get('sample_fmt') or '').lower().rstrip('p')
    raw_bits = int(stream.get('bits_per_raw_sample') or 0)
    if sample_format in {'dbl'}:
        return 'pcm_f64le'
    if sample_format in {'flt'}:
        return 'pcm_f32le'
    if raw_bits > 24 or sample_format in {'s32'}:
        return 'pcm_s32le'
    if raw_bits > 16 or sample_format in {'s24'}:
        return 'pcm_s24le'
    if sample_format in {'u8'}:
        return 'pcm_u8'
    return 'pcm_s16le'


def _source_mime(original_name, stream):
    guessed = mimetypes.guess_type(original_name or '')[0]
    if guessed and guessed.startswith('audio/'):
        return guessed
    format_name = str(stream.get('format_name') or '').split(',', 1)[0]
    aliases = {'flac': 'audio/flac', 'wav': 'audio/wav', 'mp3': 'audio/mpeg'}
    return aliases.get(format_name, f'audio/{format_name}' if format_name else 'application/octet-stream')


def save_audio_original(storage):
    """Save an untouched original after bounded size validation and ffprobe."""
    original_name = storage.filename or ''
    safe_name = sanitize_upload_filename(original_name)
    if not safe_name:
        raise AudioProcessingError('音频文件名无效。')

    storage.stream.seek(0, os.SEEK_END)
    size = storage.stream.tell()
    storage.stream.seek(0)
    limit = 100 * 1024 * 1024
    if size <= 0 or size > limit:
        raise AudioProcessingError('音频大小无效或超过 100 MB 限制。')

    extension = os.path.splitext(safe_name)[1].lower()[:20] or '.audio'
    filename = f'{uuid.uuid4().hex}{extension}'
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'music')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    storage.save(path)
    try:
        stream = probe_audio(path)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return filename, original_name[:128], stream


def create_wav_variant(record, stream):
    """Create an atomic, lossless PCM WAV copy and return its model."""
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'music')
    source_path = os.path.join(folder, record.filename)
    variant_name = f'{uuid.uuid4().hex}.wav'
    final_path = os.path.join(folder, variant_name)
    temporary_path = final_path + '.partial'
    codec = _pcm_codec_for_stream(stream)
    command = [
        current_app.config['FFMPEG_BINARY'],
        '-v',
        'error',
        '-y',
        '-i',
        source_path,
        '-map',
        '0:a:0',
        '-vn',
        '-c:a',
        codec,
    ]
    sample_rate = int(stream.get('sample_rate') or 0)
    channels = int(stream.get('channels') or 0)
    if sample_rate:
        command.extend(['-ar', str(sample_rate)])
    if channels:
        command.extend(['-ac', str(channels)])
    command.extend(['-f', 'wav', temporary_path])

    try:
        result = _run_media_command(command)
        if result.returncode != 0 or not os.path.isfile(temporary_path):
            detail = (result.stderr or '').strip().splitlines()
            raise AudioProcessingError(detail[-1] if detail else '无损 WAV 生成失败。')
        os.replace(temporary_path, final_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

    return AudioPlaybackVariant(
        file_record=record,
        filename=variant_name,
        source_mime_type=_source_mime(record.original_name, stream),
        mime_type='audio/wav',
        codec=codec,
        sample_rate=sample_rate or None,
        channels=channels or None,
    )


def remove_audio_files(record):
    """Delete an audio original and every generated playback file."""
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'music')
    filenames = [record.filename]
    if record.audio_variant:
        filenames.append(record.audio_variant.filename)
    for filename in filenames:
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            os.remove(path)


def backfill_audio_variants():
    """Generate missing variants for legacy audio rows."""
    created = 0
    for record in FileRecord.query.filter_by(file_type='music').all():
        if record.audio_variant:
            continue
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'music', record.filename)
        if not os.path.isfile(path):
            current_app.logger.warning(
                'Skipping missing legacy audio file during playback backfill: %s',
                record.filename,
            )
            continue
        stream = probe_audio(path)
        variant = create_wav_variant(record, stream)
        db.session.add(variant)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            variant_path = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                'music',
                variant.filename,
            )
            if os.path.isfile(variant_path):
                os.remove(variant_path)
            raise
        created += 1
    return created


def register_audio_cli(app):
    @app.cli.command('backfill-audio-variants')
    def backfill_audio_variants_command():
        count = backfill_audio_variants()
        print(f'Created {count} lossless WAV playback variant(s).')
