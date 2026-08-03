import io
import os
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

import requests
from PIL import Image
from flask import g
from docx import Document
from pypdf import PdfWriter

from backend.admin.hermes_attachments import build_attachment_content
from backend.admin.hermes import stream_hermes_response
from backend.core.app import create_app
from backend.core.models import (
    HermesAttachment,
    HermesChatJob,
    HermesConversation,
    HermesMessage,
    User,
    db,
)


class HermesStreamingTests(unittest.TestCase):
    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory()
        self.attachment_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                'TESTING': True,
                'LOCAL_DEV': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'UPLOAD_FOLDER': self.upload_dir.name,
                'HERMES_ATTACHMENT_FOLDER': self.attachment_dir.name,
                'WTF_CSRF_ENABLED': False,
                'RATELIMIT_ENABLED': False,
                'PROXY_FIX_ENABLED': False,
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        self.admin = User(username='stream-admin', is_admin=True)
        self.admin.set_password('password')
        self.other_admin = User(username='other-admin', is_admin=True)
        self.other_admin.set_password('password')
        db.session.add_all([self.admin, self.other_admin])
        db.session.commit()
        self.client = self.app.test_client()
        self._login(self.admin)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.upload_dir.cleanup()
        self.attachment_dir.cleanup()

    def _login(self, user):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def _post_stream(self, request_id, data):
        data['client_request_id'] = request_id
        with patch(
            'backend.admin.hermes.stream_hermes_response',
            return_value=iter(['**安全** ', '<script>alert(1)</script>完成']),
        ):
            response = self.client.post(
                '/api/hermes/chat/stream',
                data=data,
                content_type='multipart/form-data',
            )
            return response, response.get_data(as_text=True)

    def test_stream_saves_document_and_returns_fixed_events(self):
        request_id = uuid.uuid4().hex
        response, body = self._post_stream(
            request_id,
            {
                'message': '总结附件',
                'attachments': (io.BytesIO('中文内容'.encode('gb18030')), '说明.txt'),
            },
        )

        self.assertEqual(response.status_code, 200)
        for event in ('conversation', 'user_message', 'response_delta', 'response_complete'):
            self.assertIn(f'event: {event}', body)
        self.assertEqual(HermesAttachment.query.count(), 1)
        self.assertEqual(HermesChatJob.query.one().status, 'succeeded')
        self.assertIn('"content_html":"<p><strong>安全</strong> 完成</p>"', body)

    def test_editor_context_and_attachment_are_sent_without_saving_context(self):
        captured = {}

        def fake_stream(prompt, *_args):
            captured['prompt'] = prompt
            return iter(['完成'])

        with patch('backend.admin.hermes.stream_hermes_response', side_effect=fake_stream):
            response = self.client.post(
                '/api/hermes/chat/stream',
                data={
                    'message': '根据资料续写一段',
                    'context': '# 尚未保存的文章\n这是正文。',
                    'client_request_id': uuid.uuid4().hex,
                    'attachments': (io.BytesIO('参考资料'.encode()), 'reference.txt'),
                },
                content_type='multipart/form-data',
            )
            response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['prompt'][0]['type'], 'input_text')
        self.assertIn('尚未保存的文章', captured['prompt'][0]['text'])
        self.assertIn('根据资料续写一段', captured['prompt'][1]['text'])
        self.assertIn('参考资料', captured['prompt'][1]['text'])
        user_message = HermesMessage.query.filter_by(role='user').one()
        self.assertEqual(user_message.content, '根据资料续写一段')

    def test_editor_context_limit_rejects_before_creating_a_conversation(self):
        self.app.config['HERMES_EDITOR_CONTEXT_MAX_CHARS'] = 4
        response = self.client.post(
            '/api/hermes/chat/stream',
            data={
                'message': '继续写',
                'context': '12345',
                'client_request_id': uuid.uuid4().hex,
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('max 4 chars', response.get_json()['error'])
        self.assertEqual(HermesConversation.query.count(), 0)

    def test_writing_assist_uses_the_shared_editor_context_limit(self):
        self.app.config['HERMES_EDITOR_CONTEXT_MAX_CHARS'] = 4
        response = self.client.post(
            '/api/hermes/writing-assist',
            json={'action': 'translate', 'text': '12345'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('max 4 chars', response.get_json()['error'])

    def test_writing_assist_returns_sanitized_markdown_html(self):
        with patch(
            'backend.admin.hermes.get_writing_assist_response',
            return_value='**译文**<script>alert(1)</script>',
        ):
            response = self.client.post(
                '/api/hermes/writing-assist',
                json={'action': 'translate', 'text': '原文'},
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn('<strong>译文</strong>', data['content_html'])
        self.assertNotIn('<script>', data['content_html'])

    def test_stream_retries_one_connection_reset(self):
        self.app.config['HERMES_API_URL'] = 'http://127.0.0.1:8642/v1/chat/completions'
        response = Mock()
        response.iter_lines.return_value = [
            'data: {"type":"response.output_text.delta","delta":"ok"}',
            'data: [DONE]',
        ]
        with (
            patch(
                'backend.admin.hermes.requests.post',
                side_effect=[
                    requests.exceptions.ConnectionError('temporary reset'),
                    response,
                ],
            ) as post,
            patch('backend.admin.hermes.time.sleep'),
        ):
            result = ''.join(
                stream_hermes_response('test', 'conversation-key', 'session-key')
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(post.call_count, 2)
        response.close.assert_called_once()

    def test_stream_returns_friendly_connection_error(self):
        with patch(
            'backend.admin.hermes.stream_hermes_response',
            side_effect=requests.exceptions.ConnectionError('raw transport detail'),
        ):
            response = self.client.post(
                '/api/hermes/chat/stream',
                data={
                    'message': 'test',
                    'client_request_id': uuid.uuid4().hex,
                },
                content_type='multipart/form-data',
            )
            body = response.get_data(as_text=True)

        self.assertIn('event: error', body)
        self.assertIn('Hermes 服务连接已中断，请检查连接后重试。', body)
        self.assertNotIn('raw transport detail', body)

    def test_docx_and_pdf_attachments_are_extracted_and_saved(self):
        docx_stream = io.BytesIO()
        document = Document()
        document.add_paragraph('DOCX 中文内容')
        document.save(docx_stream)
        docx_stream.seek(0)

        pdf_stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(pdf_stream)
        pdf_stream.seek(0)

        response, _ = self._post_stream(
            uuid.uuid4().hex,
            {
                'message': '读取两个文档',
                'attachments': [
                    (docx_stream, '说明.docx'),
                    (pdf_stream, '空白.pdf'),
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        attachments = HermesAttachment.query.order_by(HermesAttachment.id).all()
        self.assertEqual([item.mime_type for item in attachments], [
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/pdf',
        ])
        extracted_path = os.path.join(
            self.attachment_dir.name,
            *attachments[0].extracted_text_name.split('/'),
        )
        with open(extracted_path, encoding='utf-8') as extracted:
            self.assertIn('DOCX 中文内容', extracted.read())

    def test_document_truncation_is_marked_for_the_model(self):
        self.app.config['HERMES_ATTACHMENT_TEXT_MAX_CHARS'] = 5
        _, _ = self._post_stream(
            uuid.uuid4().hex,
            {
                'message': '截断测试',
                'attachments': (io.BytesIO('123456789'.encode()), 'long.txt'),
            },
        )
        attachment = HermesAttachment.query.one()
        parts = build_attachment_content(attachment.message)

        self.assertTrue(attachment.truncated)
        self.assertIn('内容已截断', parts[0]['text'])
        self.assertIn('12345', parts[0]['text'])

    def test_attachment_count_limit_rejects_the_entire_turn(self):
        self.app.config['HERMES_ATTACHMENT_MAX_COUNT'] = 1
        response = self.client.post(
            '/api/hermes/chat/stream',
            data={
                'message': '太多附件',
                'client_request_id': uuid.uuid4().hex,
                'attachments': [
                    (io.BytesIO(b'one'), 'one.txt'),
                    (io.BytesIO(b'two'), 'two.txt'),
                ],
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HermesConversation.query.count(), 0)
        self.assertEqual(HermesAttachment.query.count(), 0)

    def test_request_uuid_is_idempotent(self):
        request_id = uuid.uuid4().hex
        first, _ = self._post_stream(request_id, {'message': '同一个请求'})
        second, replay = self._post_stream(request_id, {'message': '不应再次保存'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn('event: response_complete', replay)
        self.assertEqual(HermesChatJob.query.count(), 1)
        self.assertEqual(HermesConversation.query.one().messages[0].content, '同一个请求')

    def test_stop_and_retry_endpoints_update_persisted_jobs(self):
        _, _ = self._post_stream(uuid.uuid4().hex, {'message': '需要重试'})
        user_message = HermesConversation.query.one().messages[0]

        with patch('backend.admin.hermes.start_hermes_chat_job') as start_job:
            retry_response = self.client.post(
                f'/api/hermes/messages/{user_message.id}/retry'
            )
        self.assertEqual(retry_response.status_code, 202)
        retry_job = HermesChatJob.query.order_by(HermesChatJob.id.desc()).first()
        self.assertEqual(retry_job.status, 'pending')
        start_job.assert_called_once()

        cancel_response = self.client.post(
            f'/api/hermes/chat/jobs/{retry_job.job_key}/cancel'
        )
        self.assertEqual(cancel_response.status_code, 200)
        db.session.refresh(retry_job)
        self.assertEqual(retry_job.status, 'cancelled')

    def test_image_is_validated_and_private(self):
        image_stream = io.BytesIO()
        Image.new('RGB', (8, 8), '#336699').save(image_stream, format='PNG')
        image_stream.seek(0)
        _, body = self._post_stream(
            uuid.uuid4().hex,
            {'message': '看图', 'attachments': (image_stream, 'photo.png')},
        )
        attachment = HermesAttachment.query.one()

        own_response = self.client.get(f'/api/hermes/attachments/{attachment.id}')
        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response.mimetype, 'image/png')
        own_response.close()
        parts = build_attachment_content(attachment.message)
        self.assertEqual(parts[-1]['type'], 'input_image')
        self.assertTrue(parts[-1]['image_url'].startswith('data:image/png;base64,'))

        other_client = self.app.test_client()
        with other_client.session_transaction() as session:
            session['_user_id'] = str(self.other_admin.id)
            session['_fresh'] = True
        g.pop('_login_user', None)
        forbidden = other_client.get(f'/api/hermes/attachments/{attachment.id}')
        self.assertEqual(forbidden.status_code, 404)
        forbidden.close()

    def test_invalid_image_is_rejected_without_leftovers(self):
        response = self.client.post(
            '/api/hermes/chat/stream',
            data={
                'message': '坏图',
                'client_request_id': uuid.uuid4().hex,
                'attachments': (io.BytesIO(b'not-a-png'), '../fake.png'),
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HermesAttachment.query.count(), 0)
        self.assertFalse(any(os.scandir(self.attachment_dir.name)))

    def test_delete_conversation_cleans_private_files(self):
        _, _ = self._post_stream(
            uuid.uuid4().hex,
            {'message': '保存后删除', 'attachments': (io.BytesIO(b'plain text'), 'note.md')},
        )
        conversation = HermesConversation.query.one()
        attachment = HermesAttachment.query.one()
        stored_path = os.path.join(self.attachment_dir.name, *attachment.stored_name.split('/'))
        self.assertTrue(os.path.isfile(stored_path))

        response = self.client.delete(f'/api/hermes/conversations/{conversation.id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(HermesConversation.query.count(), 0)
        self.assertFalse(os.path.exists(stored_path))


if __name__ == '__main__':
    unittest.main()
