import json
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from backend.admin.audio import (
    AudioProcessingError,
    _pcm_codec_for_stream,
    _run_media_command,
    backfill_audio_variants,
    create_wav_variant,
    probe_audio,
)
from backend.core.models import AudioPlaybackVariant, FileRecord, db


class AudioPipelineTests(unittest.TestCase):
    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.upload_dir.name,
            FFMPEG_BINARY='ffmpeg-test',
            FFPROBE_BINARY='ffprobe-test',
            AUDIO_PROCESS_TIMEOUT_SECONDS=3,
        )
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        os.makedirs(os.path.join(self.upload_dir.name, 'music'), exist_ok=True)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.upload_dir.cleanup()

    def test_probe_uses_real_audio_stream_metadata(self):
        payload = {
            'streams': [{
                'codec_name': 'flac',
                'sample_fmt': 's32',
                'sample_rate': '96000',
                'channels': 2,
                'bits_per_raw_sample': '24',
            }],
            'format': {'format_name': 'flac'},
        }
        result = SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        with patch('backend.admin.audio._run_media_command', return_value=result):
            stream = probe_audio('example.bin')

        self.assertEqual(stream['codec_name'], 'flac')
        self.assertEqual(stream['format_name'], 'flac')
        self.assertEqual(_pcm_codec_for_stream(stream), 'pcm_s32le')

    def test_probe_rejects_non_audio(self):
        result = SimpleNamespace(returncode=1, stdout='', stderr='Invalid data found')
        with patch('backend.admin.audio._run_media_command', return_value=result):
            with self.assertRaisesRegex(AudioProcessingError, 'Invalid data found'):
                probe_audio('not-audio.dat')

    def test_media_process_timeout_has_clear_error(self):
        with patch(
            'backend.admin.audio.subprocess.run',
            side_effect=subprocess.TimeoutExpired(['ffmpeg-test'], timeout=3),
        ):
            with self.assertRaisesRegex(AudioProcessingError, '超时'):
                _run_media_command(['ffmpeg-test'])

    def test_wav_variant_preserves_rate_channels_and_precision(self):
        source = os.path.join(self.upload_dir.name, 'music', 'source.flac')
        with open(source, 'wb') as output:
            output.write(b'original')
        record = FileRecord(
            filename='source.flac',
            original_name='source.flac',
            file_type='music',
            user_id=1,
        )
        db.session.add(record)
        db.session.flush()
        commands = []

        def fake_run(command, timeout=None):
            commands.append(command)
            with open(command[-1], 'wb') as output:
                output.write(b'RIFF-test')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        stream = {
            'sample_fmt': 's32',
            'bits_per_raw_sample': '24',
            'sample_rate': '96000',
            'channels': 2,
            'format_name': 'flac',
        }
        with patch('backend.admin.audio._run_media_command', side_effect=fake_run):
            variant = create_wav_variant(record, stream)

        command = commands[0]
        self.assertIn('pcm_s32le', command)
        self.assertEqual(command[command.index('-ar') + 1], '96000')
        self.assertEqual(command[command.index('-ac') + 1], '2')
        self.assertTrue(os.path.isfile(os.path.join(self.upload_dir.name, 'music', variant.filename)))

    def test_backfill_removes_variant_when_database_commit_fails(self):
        record = FileRecord(
            filename='legacy.flac',
            original_name='legacy.flac',
            file_type='music',
            user_id=1,
        )
        db.session.add(record)
        db.session.commit()
        original_path = os.path.join(self.upload_dir.name, 'music', 'legacy.flac')
        with open(original_path, 'wb') as output:
            output.write(b'fLaC-test')
        variant_path = os.path.join(self.upload_dir.name, 'music', 'orphan.wav')
        with open(variant_path, 'wb') as output:
            output.write(b'RIFF-test')
        def create_test_variant(file_record, stream):
            return AudioPlaybackVariant(
                file_record=file_record,
                filename='orphan.wav',
                source_mime_type='audio/flac',
                mime_type='audio/wav',
                codec='pcm_s32le',
                sample_rate=96000,
                channels=2,
            )

        with (
            patch('backend.admin.audio.probe_audio', return_value={}),
            patch('backend.admin.audio.create_wav_variant', side_effect=create_test_variant),
            patch.object(db.session, 'commit', side_effect=RuntimeError('disk full')),
        ):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                backfill_audio_variants()

        self.assertFalse(os.path.exists(variant_path))

    def test_backfill_skips_legacy_rows_whose_files_are_missing(self):
        record = FileRecord(
            filename='missing.flac',
            original_name='missing.flac',
            file_type='music',
            user_id=1,
        )
        db.session.add(record)
        db.session.commit()

        with patch('backend.admin.audio.probe_audio') as probe:
            created = backfill_audio_variants()

        self.assertEqual(created, 0)
        probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
