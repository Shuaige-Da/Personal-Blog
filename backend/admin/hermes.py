# -*- coding: utf-8 -*-
"""Hermes Agent integration module.

This module handles:
1. Standalone chat page (/chat)
2. AJAX chat API (/api/hermes/chat)
3. AI writing assistant API (/api/hermes/writing-assist)

When HERMES_API_URL is not configured, returns mock responses for local dev.
"""

import json
import re
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
from flask import Response, current_app, jsonify, request, send_file, stream_with_context
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from backend.admin.auth import admin_required
from backend.admin.blog import render_markdown_to_html
from backend.admin.hermes_attachments import (
    AttachmentError,
    attachment_path,
    build_attachment_content,
    remove_attachment_files,
    save_attachments,
    serialize_attachment,
)
from backend.admin.settings import render_with_background
from backend.core.constants import HERMES_WRITING_ACTIONS
from backend.core.models import (
    HermesAttachment,
    HermesChatJob,
    HermesConversation,
    HermesMessage,
    db,
    utc_now,
)

MAX_CHAT_HISTORY_MESSAGES = 6
MAX_CHAT_MESSAGE_CHARS = 500
DEFAULT_CHAT_TITLE = 'New chat'
CHAT_JOB_PENDING = 'pending'
CHAT_JOB_RUNNING = 'running'
CHAT_JOB_SUCCEEDED = 'succeeded'
CHAT_JOB_FAILED = 'failed'
CHAT_JOB_CANCELLED = 'cancelled'
WRITING_SYSTEM_PROMPTS = {
    'polish': (
        'You are a professional text polishing assistant. '
        'Refine and optimize the user text to make it smoother and more elegant. '
        'Keep the original meaning, only improve the expression.'
    ),
    'expand': (
        'You are a writing assistant. Expand the user outline or short text '
        'into a fuller, more detailed paragraph. Keep the style consistent, '
        'add appropriate details and examples.'
    ),
    'summarize': (
        'You are a summarization assistant. Condense and summarize the user '
        'content, extracting key information into a concise summary.'
    ),
    'translate': (
        'You are a translation assistant. If the content is in Chinese, '
        'translate it to English; if in English, translate it to Chinese. '
        'Preserve the original tone and style.'
    ),
}


def trim_chat_history(history, max_messages=MAX_CHAT_HISTORY_MESSAGES):
    """Keep a bounded slice of recent OpenAI-style chat messages."""
    if not isinstance(history, list):
        return []

    clean_history = []
    for message in history:
        if not isinstance(message, dict):
            continue

        role = message.get('role')
        content = message.get('content')
        if role not in {'user', 'assistant'}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue

        clean_history.append(
            {'role': role, 'content': content.strip()[:MAX_CHAT_MESSAGE_CHARS]}
        )

    return clean_history[-max_messages:]


def build_chat_messages(prompt, *, history=None, system_prompt=None):
    """Build the stateless chat-completions message list sent to Hermes."""
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})

    messages.extend(trim_chat_history(history or []))
    messages.append({'role': 'user', 'content': prompt})
    return messages


def build_conversation_key(user_id):
    """Build a stable Hermes conversation key for one website chat thread."""
    return f'rainwave-web-{user_id}-{uuid.uuid4().hex}'


def responses_url_from_api_url(api_url):
    """Convert a configured Hermes chat-completions URL to responses URL."""
    parsed = urlsplit(api_url)
    path = parsed.path.rstrip('/')
    if path.endswith('/chat/completions'):
        path = path[: -len('/chat/completions')] + '/responses'
    elif not path.endswith('/responses'):
        path = path + '/responses'
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def parse_hermes_response_text(data):
    """Extract assistant text from Hermes responses or chat-completions payloads."""
    output_text = data.get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = data.get('output')
    if isinstance(output, list):
        parts = []
        for item in output:
            for content in item.get('content', []) if isinstance(item, dict) else []:
                text = content.get('text') if isinstance(content, dict) else None
                if isinstance(text, str) and text:
                    parts.append(text)
        if parts:
            return '\n'.join(parts)

    choices = data.get('choices', [])
    if choices:
        return choices[0].get('message', {}).get('content', '')
    return data.get('response', data.get('result', ''))


def isoformat_or_empty(value):
    """Serialize an optional datetime consistently for JSON responses."""
    return value.isoformat() if value else ''


def serialize_conversation(conversation):
    """Return conversation metadata for JSON APIs."""
    return {
        'id': conversation.id,
        'title': conversation.title,
        'conversation_key': conversation.conversation_key,
        'created_at': isoformat_or_empty(conversation.created_at),
        'updated_at': isoformat_or_empty(conversation.updated_at),
    }


def serialize_message(message):
    """Return one saved chat message for JSON APIs."""
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'content_html': render_markdown_to_html(message.content) if message.role == 'assistant' else '',
        'attachments': [serialize_attachment(item) for item in message.attachments],
        'created_at': isoformat_or_empty(message.created_at),
    }


def serialize_chat_job(job):
    """Return one background chat job for JSON APIs."""
    return {
        'id': job.id,
        'job_key': job.job_key,
        'status': job.status,
        'error': job.error or '',
        'created_at': isoformat_or_empty(job.created_at),
        'updated_at': isoformat_or_empty(job.updated_at),
        'conversation_id': job.conversation_id,
        'assistant_message_id': job.assistant_message_id,
    }


def build_chat_title(prompt):
    """Create a compact history title from the first user message."""
    title = ' '.join((prompt or '').split())
    return (title[:40] or DEFAULT_CHAT_TITLE)


def create_hermes_conversation(user, title=None):
    """Create a local website thread mapped to one Hermes conversation."""
    conversation = HermesConversation(
        user_id=user.id,
        conversation_key=build_conversation_key(user.id),
        title=title or DEFAULT_CHAT_TITLE,
    )
    db.session.add(conversation)
    db.session.flush()
    return conversation


def get_user_conversation_or_404(conversation_id, *, include_messages=False):
    """Load an owned conversation, optionally with its full display history."""
    query = HermesConversation.query.filter_by(
        id=conversation_id,
        user_id=current_user.id,
    )
    if include_messages:
        query = query.options(
            selectinload(HermesConversation.messages).selectinload(
                HermesMessage.attachments
            )
        )
    return query.first_or_404()


def get_user_conversations(user_id):
    """Return a user's conversations with the most recently updated first."""
    return HermesConversation.query.filter_by(user_id=user_id).order_by(
        HermesConversation.updated_at.desc()
    ).all()


def build_fallback_history(conversation, user_message_id):
    """Build local history for the stateless fallback without duplicating prompt."""
    recent_messages = (
        HermesMessage.query.filter_by(conversation_id=conversation.id)
        .order_by(HermesMessage.created_at.desc(), HermesMessage.id.desc())
        .limit(MAX_CHAT_HISTORY_MESSAGES + 1)
        .all()
    )
    return [
        {'role': saved.role, 'content': saved.content}
        for saved in reversed(recent_messages)
        if saved.id != user_message_id
    ]


def get_user_chat_job_or_404(job_key):
    """Load a background chat job owned by the current user."""
    return HermesChatJob.query.filter_by(
        job_key=job_key,
        user_id=current_user.id,
    ).first_or_404()


def get_user_message_or_404(message_id):
    """Load a saved chat message owned by the current administrator."""
    return (
        HermesMessage.query.join(HermesConversation)
        .filter(
            HermesMessage.id == message_id,
            HermesConversation.user_id == current_user.id,
        )
        .first_or_404()
    )


def run_hermes_chat_job(app, job_id):
    """Run a Hermes request outside the browser request/response cycle."""
    with app.app_context():
        job = db.session.get(HermesChatJob, job_id)
        if not job:
            return

        job.status = CHAT_JOB_RUNNING
        db.session.commit()

        try:
            conversation = db.session.get(HermesConversation, job.conversation_id)
            user_message = db.session.get(HermesMessage, job.user_message_id)
            if not conversation or not user_message:
                raise RuntimeError('Chat job conversation or message no longer exists')

            session_key = f'agent:main:rainwave:web:{job.user_id}'
            prompt = build_attachment_content(user_message) or user_message.content
            try:
                response = call_hermes_responses_api(
                    prompt,
                    conversation.conversation_key,
                    session_key,
                )
                if response is None:
                    response = call_hermes_api(
                        prompt,
                        history=build_fallback_history(conversation, user_message.id),
                        session_id=session_key,
                    )
            except requests.exceptions.RequestException as error:
                app.logger.warning('Hermes responses API failed: %s', error)
                response = call_hermes_api(
                    prompt,
                    history=build_fallback_history(conversation, user_message.id),
                    session_id=session_key,
                )

            db.session.refresh(job)
            if job.status == CHAT_JOB_CANCELLED:
                return

            assistant_message = HermesMessage(
                conversation=conversation,
                role='assistant',
                content=response or '',
            )
            conversation.updated_at = utc_now()
            db.session.add(assistant_message)
            db.session.flush()

            job.assistant_message_id = assistant_message.id
            job.status = CHAT_JOB_SUCCEEDED
            job.error = None
            db.session.commit()
        except Exception as error:  # pragma: no cover - logged operational fallback.
            db.session.rollback()
            app.logger.exception('Hermes chat job failed')
            job = db.session.get(HermesChatJob, job_id)
            if job:
                job.status = CHAT_JOB_FAILED
                job.error = str(error)
                db.session.commit()


def start_hermes_chat_job(app, job_id):
    """Start one background chat job in this Gunicorn worker."""
    thread = threading.Thread(
        target=run_hermes_chat_job,
        args=(app, job_id),
        daemon=True,
    )
    thread.start()


def get_hermes_api_config():
    """Return the configured Hermes endpoint and optional bearer token."""
    return (
        current_app.config.get('HERMES_API_URL', ''),
        current_app.config.get('HERMES_API_KEY', ''),
    )


def build_hermes_headers(api_key, session_key=None, *, include_session_id=False):
    """Build shared JSON headers for Hermes API requests."""
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if session_key:
        headers['X-Hermes-Session-Key'] = session_key
        if include_session_id:
            headers['X-Hermes-Session-Id'] = session_key
    return headers


def call_hermes_responses_api(prompt, conversation_key, session_key):
    """Call the stateful Hermes responses endpoint for website conversations."""
    api_url, api_key = get_hermes_api_config()
    if not api_url:
        return None

    response_input = prompt
    if isinstance(prompt, list):
        response_input = [{'role': 'user', 'content': prompt}]
    payload = {
        'model': 'hermes-agent',
        'input': response_input,
        'conversation': conversation_key,
    }
    response = requests.post(
        responses_url_from_api_url(api_url),
        json=payload,
        headers=build_hermes_headers(api_key, session_key),
        timeout=180,
    )
    response.raise_for_status()
    return parse_hermes_response_text(response.json())


def call_hermes_api(prompt, system_prompt=None, history=None, session_id=None):
    """Call the Hermes Agent API (OpenAI-compatible format).

    Returns mock response when HERMES_API_URL is not configured.
    """
    api_url, api_key = get_hermes_api_config()

    if not api_url:
        # Local dev mode: return mock response.
        time.sleep(0.5)
        snippet = str(prompt)[:100]
        return (
            f'[Hermes Mock] You said: "{snippet}..."\n\n'
            'Hermes API is not configured. To enable real responses, set:\n'
            '- HERMES_API_URL: your Hermes service URL\n'
            '- HERMES_API_KEY: your API key'
        )

    payload = {
        'model': 'hermes-agent',
        'messages': build_chat_messages(
            prompt,
            history=history,
            system_prompt=system_prompt,
        ),
        'stream': False,
    }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=build_hermes_headers(
                api_key,
                session_id,
                include_session_id=True,
            ),
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        return parse_hermes_response_text(data)
    except requests.exceptions.RequestException as error:
        return f'[Hermes Error] {str(error)}'
    except (ValueError, KeyError) as error:
        return f'[Hermes Parse Error] {str(error)}'


def get_writing_assist_response(action, text):
    """Build system prompt for the given writing-assist action and call Hermes."""
    system_prompt = WRITING_SYSTEM_PROMPTS.get(
        action,
        WRITING_SYSTEM_PROMPTS['polish'],
    )
    return call_hermes_api(text, system_prompt=system_prompt)


def format_sse(event_name, payload):
    """Serialize one browser-friendly server-sent event."""
    return (
        f'event: {event_name}\n'
        f'data: {json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}\n\n'
    )


def add_editor_context(prompt, context_text):
    """Add unsaved article text to one request without polluting saved chat history."""
    if not context_text:
        return prompt
    context_part = {
        'type': 'input_text',
        'text': f'[当前文章上下文]\n{context_text}\n[/当前文章上下文]',
    }
    if isinstance(prompt, list):
        return [context_part, *prompt]
    return [context_part, {'type': 'input_text', 'text': prompt}]


def post_hermes_stream(api_url, payload, headers):
    """Open a Hermes stream, retrying one connection reset before any response."""
    for attempt in range(2):
        try:
            return requests.post(
                responses_url_from_api_url(api_url),
                json=payload,
                headers=headers,
                timeout=(30, 300),
                stream=True,
            )
        except requests.exceptions.ConnectionError:
            if attempt:
                raise
            time.sleep(0.25)


def hermes_error_message(error):
    """Return a stable user-facing message for transient Hermes failures."""
    if isinstance(error, requests.exceptions.ConnectionError):
        return 'Hermes 服务连接已中断，请检查连接后重试。'
    if isinstance(error, requests.exceptions.Timeout):
        return 'Hermes 服务响应超时，请稍后重试。'
    return str(error) or 'Hermes 请求失败，请稍后重试。'


def stream_hermes_response(prompt, conversation_key, session_key):
    """Yield text deltas from Hermes Responses SSE with a mock fallback."""
    api_url, api_key = get_hermes_api_config()
    if not api_url:
        response = call_hermes_api(prompt, session_id=session_key)
        for start in range(0, len(response), 24):
            yield response[start : start + 24]
        return

    response_input = prompt
    if isinstance(prompt, list):
        response_input = [{'role': 'user', 'content': prompt}]
    payload = {
        'model': 'hermes-agent',
        'input': response_input,
        'conversation': conversation_key,
        'stream': True,
    }
    response = post_hermes_stream(
        api_url,
        payload,
        build_hermes_headers(api_key, session_key),
    )
    response.raise_for_status()
    emitted = False
    try:
        event_name = ''
        for raw_line in response.iter_lines(decode_unicode=True):
            line = (raw_line or '').strip()
            if not line:
                event_name = ''
                continue
            if line.startswith('event:'):
                event_name = line[6:].strip()
                continue
            if not line.startswith('data:'):
                continue
            raw_data = line[5:].strip()
            if raw_data == '[DONE]':
                break
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            event_type = str(data.get('type') or event_name)
            if event_type.endswith('.delta'):
                delta = data.get('delta')
                if isinstance(delta, str) and delta:
                    emitted = True
                    yield delta
            elif event_type in {'response.completed', 'response.done'} and not emitted:
                completed = data.get('response') if isinstance(data.get('response'), dict) else data
                text = parse_hermes_response_text(completed)
                if text:
                    emitted = True
                    yield text
            elif event_type in {'response.failed', 'error'}:
                response_data = data.get('response')
                response_error = (
                    response_data.get('error') if isinstance(response_data, dict) else None
                )
                error = data.get('error') or response_error or {}
                message = error.get('message') if isinstance(error, dict) else str(error)
                raise RuntimeError(message or 'Hermes stream failed')
    finally:
        response.close()


def create_chat_job_for_message(user_message, *, job_key=None):
    """Create an idempotent persisted job for one saved user message."""
    job = HermesChatJob(
        job_key=job_key or uuid.uuid4().hex,
        status=CHAT_JOB_PENDING,
        user_id=user_message.conversation.user_id,
        conversation_id=user_message.conversation_id,
        user_message_id=user_message.id,
    )
    db.session.add(job)
    return job


def register_hermes_routes(app):
    """Register Hermes Agent routes."""

    @app.route('/chat')
    @login_required
    @admin_required
    def chat():
        """Render the Hermes Agent chat page."""
        return render_with_background(
            'admin/chat.html',
            'blog_background',
            title='Hermes Agent',
            conversations=get_user_conversations(current_user.id),
        )

    @app.route('/api/hermes/conversations', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def api_hermes_conversations():
        """List or create website Hermes conversations."""
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            title = (data.get('title') or DEFAULT_CHAT_TITLE).strip()[:160]
            conversation = create_hermes_conversation(current_user, title=title)
            db.session.commit()
            return jsonify({'conversation': serialize_conversation(conversation)})

        return jsonify(
            {
                'conversations': [
                    serialize_conversation(item)
                    for item in get_user_conversations(current_user.id)
                ]
            }
        )

    @app.route('/api/hermes/conversations/<int:conversation_id>/messages')
    @login_required
    @admin_required
    def api_hermes_conversation_messages(conversation_id):
        """Return saved display messages for one website Hermes conversation."""
        conversation = get_user_conversation_or_404(
            conversation_id,
            include_messages=True,
        )
        return jsonify(
            {
                'conversation': serialize_conversation(conversation),
                'messages': [serialize_message(message) for message in conversation.messages],
            }
        )

    @app.route('/api/hermes/attachments/<int:attachment_id>')
    @login_required
    @admin_required
    def api_hermes_attachment(attachment_id):
        """Serve a private attachment only to its owning administrator."""
        attachment = HermesAttachment.query.filter_by(
            id=attachment_id,
            user_id=current_user.id,
        ).first_or_404()
        return send_file(
            attachment_path(attachment),
            mimetype=attachment.mime_type,
            download_name=attachment.original_name,
            as_attachment=attachment.kind != 'image',
            conditional=True,
        )

    @app.route('/api/hermes/conversations/<int:conversation_id>', methods=['DELETE'])
    @login_required
    @admin_required
    def api_hermes_delete_conversation(conversation_id):
        """Delete a conversation, its jobs, messages, and private files."""
        conversation = get_user_conversation_or_404(conversation_id)
        attachments = HermesAttachment.query.filter_by(conversation_id=conversation.id).all()
        HermesChatJob.query.filter_by(conversation_id=conversation.id).delete(
            synchronize_session=False
        )
        db.session.delete(conversation)
        db.session.commit()
        remove_attachment_files(attachments)
        return jsonify({'status': 'deleted', 'conversation_id': conversation_id})

    @app.route('/api/hermes/chat/stream', methods=['POST'])
    @login_required
    @admin_required
    def api_hermes_chat_stream():
        """Create or retry one turn and stream its assistant reply as SSE."""
        message_text = (request.form.get('message') or '').strip()
        editor_context = (request.form.get('context') or '').strip()
        retry_message_id = request.form.get('retry_message_id', type=int)
        uploaded_files = request.files.getlist('attachments')
        client_request_id = (request.form.get('client_request_id') or uuid.uuid4().hex).strip()
        normalized_job_key = client_request_id.replace('-', '').lower()
        if not re.fullmatch(r'[0-9a-f]{32}', normalized_job_key):
            return jsonify({'error': 'Invalid client_request_id'}), 400
        if len(message_text) > 2000:
            return jsonify({'error': 'Message too long, max 2000 chars'}), 400
        editor_context_limit = current_app.config['HERMES_EDITOR_CONTEXT_MAX_CHARS']
        if len(editor_context) > editor_context_limit:
            return jsonify({
                'error': f'Article context too long, max {editor_context_limit} chars'
            }), 400
        if retry_message_id and uploaded_files:
            return jsonify({'error': 'Retry cannot include new attachments'}), 400
        if retry_message_id and editor_context:
            return jsonify({'error': 'Retry cannot include new article context'}), 400
        if not retry_message_id and not message_text and not any(item.filename for item in uploaded_files):
            return jsonify({'error': 'Message or attachment is required'}), 400

        existing_job = HermesChatJob.query.filter_by(
            job_key=normalized_job_key,
            user_id=current_user.id,
        ).first()
        if existing_job:
            def replay_existing():
                yield format_sse(
                    'conversation',
                    {
                        'conversation': serialize_conversation(existing_job.conversation),
                        'job': serialize_chat_job(existing_job),
                    },
                )
                yield format_sse('user_message', serialize_message(existing_job.user_message))
                if existing_job.assistant_message:
                    yield format_sse(
                        'response_complete',
                        {'message': serialize_message(existing_job.assistant_message)},
                    )
                else:
                    yield format_sse(
                        'error',
                        {'message': existing_job.error or 'This request is already in progress.'},
                    )

            return Response(
                stream_with_context(replay_existing()),
                mimetype='text/event-stream',
                headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'},
            )

        attachments = []
        try:
            if retry_message_id:
                user_message = get_user_message_or_404(retry_message_id)
                if user_message.role != 'user':
                    return jsonify({'error': 'Only user messages can be retried'}), 400
                conversation = user_message.conversation
            else:
                conversation_id = request.form.get('conversation_id', type=int)
                if conversation_id:
                    conversation = get_user_conversation_or_404(conversation_id)
                else:
                    conversation = create_hermes_conversation(
                        current_user,
                        title=build_chat_title(message_text or uploaded_files[0].filename),
                    )
                if conversation.title == DEFAULT_CHAT_TITLE:
                    conversation.title = build_chat_title(message_text or uploaded_files[0].filename)
                user_message = HermesMessage(
                    conversation=conversation,
                    role='user',
                    content=message_text,
                )
                db.session.add(user_message)
                db.session.flush()
                attachments = save_attachments(
                    uploaded_files,
                    conversation=conversation,
                    message=user_message,
                    user=current_user,
                )

            job = create_chat_job_for_message(user_message, job_key=normalized_job_key)
            conversation.updated_at = utc_now()
            db.session.commit()
        except AttachmentError as error:
            db.session.rollback()
            if attachments:
                remove_attachment_files(attachments)
            return jsonify({'error': str(error)}), 400
        except Exception:
            db.session.rollback()
            if attachments:
                remove_attachment_files(attachments)
            current_app.logger.exception('Hermes chat turn could not be saved')
            return jsonify({'error': '消息保存失败，附件已清理。'}), 500

        conversation_id = conversation.id
        user_message_id = user_message.id
        job_id = job.id

        def generate():
            active_job = db.session.get(HermesChatJob, job_id)
            active_conversation = db.session.get(HermesConversation, conversation_id)
            active_message = db.session.get(HermesMessage, user_message_id)
            yield format_sse(
                'conversation',
                {
                    'conversation': serialize_conversation(active_conversation),
                    'job': serialize_chat_job(active_job),
                },
            )
            yield format_sse('user_message', serialize_message(active_message))
            active_job.status = CHAT_JOB_RUNNING
            db.session.commit()
            response_parts = []
            try:
                prompt = build_attachment_content(active_message) or active_message.content
                prompt = add_editor_context(prompt, editor_context)
                session_key = f'agent:main:rainwave:web:{active_job.user_id}'
                for delta in stream_hermes_response(
                    prompt,
                    active_conversation.conversation_key,
                    session_key,
                ):
                    db.session.expire(active_job, ['status'])
                    if active_job.status == CHAT_JOB_CANCELLED:
                        yield format_sse('cancelled', {'job_key': active_job.job_key})
                        return
                    response_parts.append(delta)
                    yield format_sse('response_delta', {'delta': delta})

                db.session.refresh(active_job)
                if active_job.status == CHAT_JOB_CANCELLED:
                    yield format_sse('cancelled', {'job_key': active_job.job_key})
                    return

                response_text = ''.join(response_parts).strip()
                if not response_text:
                    raise RuntimeError('Hermes returned an empty response')
                assistant_message = HermesMessage(
                    conversation=active_conversation,
                    role='assistant',
                    content=response_text,
                )
                active_conversation.updated_at = utc_now()
                db.session.add(assistant_message)
                db.session.flush()
                active_job.assistant_message_id = assistant_message.id
                active_job.status = CHAT_JOB_SUCCEEDED
                active_job.error = None
                db.session.commit()
                yield format_sse(
                    'response_complete',
                    {'message': serialize_message(assistant_message)},
                )
            except GeneratorExit:
                db.session.rollback()
                active_job = db.session.get(HermesChatJob, job_id)
                if active_job and active_job.status in {CHAT_JOB_PENDING, CHAT_JOB_RUNNING}:
                    active_job.status = CHAT_JOB_CANCELLED
                    db.session.commit()
                raise
            except Exception as error:
                db.session.rollback()
                error_message = hermes_error_message(error)
                active_job = db.session.get(HermesChatJob, job_id)
                if active_job and active_job.status != CHAT_JOB_CANCELLED:
                    active_job.status = CHAT_JOB_FAILED
                    active_job.error = error_message
                    db.session.commit()
                yield format_sse('error', {'message': error_message})

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'X-Accel-Buffering': 'no',
                'Cache-Control': 'no-store',
                'Connection': 'keep-alive',
            },
        )

    @app.route('/api/hermes/chat/jobs/<job_key>/cancel', methods=['POST'])
    @login_required
    @admin_required
    def api_hermes_cancel_job(job_key):
        job = get_user_chat_job_or_404(job_key)
        if job.status in {CHAT_JOB_PENDING, CHAT_JOB_RUNNING}:
            job.status = CHAT_JOB_CANCELLED
            db.session.commit()
        return jsonify({'job': serialize_chat_job(job)})

    @app.route('/api/hermes/messages/<int:message_id>/retry', methods=['POST'])
    @login_required
    @admin_required
    def api_hermes_retry_message(message_id):
        user_message = get_user_message_or_404(message_id)
        if user_message.role != 'user':
            return jsonify({'error': 'Only user messages can be retried'}), 400
        job = create_chat_job_for_message(user_message)
        db.session.commit()
        start_hermes_chat_job(current_app._get_current_object(), job.id)
        return jsonify({'job': serialize_chat_job(job)}), 202

    @app.route('/api/hermes/chat', methods=['POST'])
    @login_required
    @admin_required
    def api_hermes_chat():
        """Queue a Hermes Agent chat request and return immediately."""
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400

        message = data.get('message', '').strip()
        if not message:
            return jsonify({'error': 'Message cannot be empty'}), 400

        if len(message) > 2000:
            return jsonify({'error': 'Message too long, max 2000 chars'}), 400

        conversation_id = data.get('conversation_id')
        if conversation_id:
            conversation = get_user_conversation_or_404(conversation_id)
        else:
            conversation = create_hermes_conversation(
                current_user,
                title=build_chat_title(message),
            )

        if conversation.title == DEFAULT_CHAT_TITLE:
            conversation.title = build_chat_title(message)

        user_message = HermesMessage(
            conversation=conversation,
            role='user',
            content=message,
        )
        db.session.add(user_message)
        db.session.flush()

        job = create_chat_job_for_message(user_message)
        conversation.updated_at = utc_now()
        db.session.commit()

        start_hermes_chat_job(current_app._get_current_object(), job.id)

        return jsonify(
            {
                'status': 'queued',
                'job': serialize_chat_job(job),
                'conversation': serialize_conversation(conversation),
                'user_message': serialize_message(user_message),
            }
        ), 202

    @app.route('/api/hermes/chat/jobs/<job_key>')
    @login_required
    @admin_required
    def api_hermes_chat_job(job_key):
        """Poll a queued Hermes Agent chat request."""
        job = get_user_chat_job_or_404(job_key)
        message = None
        if job.assistant_message:
            message = serialize_message(job.assistant_message)

        return jsonify(
            {
                'job': serialize_chat_job(job),
                'conversation': serialize_conversation(job.conversation),
                'message': message,
                'response': message['content'] if message else '',
            }
        )

    @app.route('/api/hermes/writing-assist', methods=['POST'])
    @login_required
    @admin_required
    def api_hermes_writing_assist():
        """AJAX endpoint for AI writing assistance."""
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400

        action = data.get('action', '').strip()
        text = data.get('text', '').strip()

        if action not in HERMES_WRITING_ACTIONS:
            supported = ', '.join(HERMES_WRITING_ACTIONS)
            return jsonify({'error': f'Invalid action. Supported: {supported}'}), 400

        if not text:
            return jsonify({'error': 'Text cannot be empty'}), 400

        text_limit = current_app.config['HERMES_EDITOR_CONTEXT_MAX_CHARS']
        if len(text) > text_limit:
            return jsonify({'error': f'Text too long, max {text_limit} chars'}), 400

        response = get_writing_assist_response(action, text)
        return jsonify({
            'result': response,
            'content_html': render_markdown_to_html(response),
        })
