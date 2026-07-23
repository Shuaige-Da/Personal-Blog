# -*- coding: utf-8 -*-
"""Hermes Agent integration module.

This module handles:
1. Standalone chat page (/chat)
2. AJAX chat API (/api/hermes/chat)
3. AI writing assistant API (/api/hermes/writing-assist)

When HERMES_API_URL is not configured, returns mock responses for local dev.
"""

import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from backend.admin.auth import admin_required
from backend.admin.settings import render_with_background
from backend.core.constants import HERMES_WRITING_ACTIONS
from backend.core.models import HermesChatJob, HermesConversation, HermesMessage, db, utc_now

MAX_CHAT_HISTORY_MESSAGES = 6
MAX_CHAT_MESSAGE_CHARS = 500
DEFAULT_CHAT_TITLE = 'New chat'
CHAT_JOB_PENDING = 'pending'
CHAT_JOB_RUNNING = 'running'
CHAT_JOB_SUCCEEDED = 'succeeded'
CHAT_JOB_FAILED = 'failed'
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


def get_user_conversation_or_404(conversation_id):
    """Load a conversation owned by the current user."""
    return HermesConversation.query.filter_by(
        id=conversation_id,
        user_id=current_user.id,
    ).first_or_404()


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
            try:
                response = call_hermes_responses_api(
                    user_message.content,
                    conversation.conversation_key,
                    session_key,
                )
                if response is None:
                    response = call_hermes_api(
                        user_message.content,
                        history=build_fallback_history(conversation, user_message.id),
                        session_id=session_key,
                    )
            except requests.exceptions.RequestException as error:
                app.logger.warning('Hermes responses API failed: %s', error)
                response = call_hermes_api(
                    user_message.content,
                    history=build_fallback_history(conversation, user_message.id),
                    session_id=session_key,
                )

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

    payload = {
        'model': 'hermes-agent',
        'input': prompt,
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
        snippet = prompt[:100]
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
        conversation = get_user_conversation_or_404(conversation_id)
        return jsonify(
            {
                'conversation': serialize_conversation(conversation),
                'messages': [serialize_message(message) for message in conversation.messages],
            }
        )

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

        job = HermesChatJob(
            job_key=uuid.uuid4().hex,
            status=CHAT_JOB_PENDING,
            user_id=current_user.id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
        )
        conversation.updated_at = utc_now()
        db.session.add(job)
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

        if len(text) > 5000:
            return jsonify({'error': 'Text too long, max 5000 chars'}), 400

        response = get_writing_assist_response(action, text)
        return jsonify({'result': response})
