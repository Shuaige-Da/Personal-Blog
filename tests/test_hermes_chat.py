import unittest

from flask import Flask

from backend.admin.hermes import (
    build_fallback_history,
    build_chat_messages,
    build_conversation_key,
    parse_hermes_response_text,
    responses_url_from_api_url,
    trim_chat_history,
)
from backend.core.models import HermesChatJob, HermesConversation, HermesMessage, User, db


class HermesChatHistoryTests(unittest.TestCase):
    def test_build_chat_messages_includes_prior_turns(self):
        history = [
            {'role': 'user', 'content': '查杭州天气'},
            {'role': 'assistant', 'content': '杭州今天多云。'},
        ]

        messages = build_chat_messages('明天呢', history=history)

        self.assertEqual(
            messages,
            [
                {'role': 'user', 'content': '查杭州天气'},
                {'role': 'assistant', 'content': '杭州今天多云。'},
                {'role': 'user', 'content': '明天呢'},
            ],
        )

    def test_responses_url_from_chat_completions_url(self):
        self.assertEqual(
            responses_url_from_api_url('http://127.0.0.1:8642/v1/chat/completions'),
            'http://127.0.0.1:8642/v1/responses',
        )

    def test_parse_responses_output_text(self):
        self.assertEqual(
            parse_hermes_response_text({'output_text': 'remembered answer'}),
            'remembered answer',
        )

    def test_parse_responses_output_content_items(self):
        self.assertEqual(
            parse_hermes_response_text(
                {
                    'output': [
                        {
                            'content': [
                                {'type': 'output_text', 'text': 'from content'}
                            ]
                        }
                    ]
                }
            ),
            'from content',
        )

    def test_conversation_key_is_stable_prefix_with_uuid_suffix(self):
        key = build_conversation_key(user_id=7)

        self.assertTrue(key.startswith('rainwave-web-7-'))
        self.assertGreater(len(key), len('rainwave-web-7-'))


class HermesConversationModelTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_conversation_stores_messages_for_display_history(self):
        user = User(username='admin', is_admin=True)
        user.set_password('password')
        conversation = HermesConversation(
            user=user,
            conversation_key='rainwave-web-1-test',
            title='Weather',
        )
        db.session.add_all(
            [
                user,
                conversation,
                HermesMessage(
                    conversation=conversation,
                    role='user',
                    content='weather in Hangzhou',
                ),
                HermesMessage(
                    conversation=conversation,
                    role='assistant',
                    content='Sunny.',
                ),
            ]
        )
        db.session.commit()

        saved = HermesConversation.query.filter_by(title='Weather').one()
        self.assertEqual(len(saved.messages), 2)
        self.assertEqual(saved.messages[0].content, 'weather in Hangzhou')
        self.assertEqual(saved.messages[1].role, 'assistant')

    def test_trim_chat_history_keeps_recent_complete_turns(self):
        history = [
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'u2'},
            {'role': 'assistant', 'content': 'a2'},
            {'role': 'user', 'content': 'u3'},
            {'role': 'assistant', 'content': 'a3'},
        ]

        self.assertEqual(
            trim_chat_history(history, max_messages=4),
            [
                {'role': 'user', 'content': 'u2'},
                {'role': 'assistant', 'content': 'a2'},
                {'role': 'user', 'content': 'u3'},
                {'role': 'assistant', 'content': 'a3'},
            ],
        )

    def test_chat_job_tracks_pending_request_and_assistant_result(self):
        user = User(username='admin', is_admin=True)
        user.set_password('password')
        conversation = HermesConversation(
            user=user,
            conversation_key='rainwave-web-1-test',
            title='Weather',
        )
        user_message = HermesMessage(
            conversation=conversation,
            role='user',
            content='weather in Hangzhou',
        )
        db.session.add_all([user, conversation, user_message])
        db.session.flush()

        job = HermesChatJob(
            job_key='job-1',
            status='pending',
            user_id=user.id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
        )
        db.session.add(job)
        db.session.commit()

        saved = HermesChatJob.query.filter_by(job_key='job-1').one()
        self.assertEqual(saved.status, 'pending')
        self.assertEqual(saved.user_message.content, 'weather in Hangzhou')

        assistant_message = HermesMessage(
            conversation=conversation,
            role='assistant',
            content='Sunny.',
        )
        db.session.add(assistant_message)
        db.session.flush()
        saved.status = 'succeeded'
        saved.assistant_message_id = assistant_message.id
        db.session.commit()

        self.assertEqual(saved.assistant_message.content, 'Sunny.')

    def test_build_fallback_history_excludes_current_user_message(self):
        user = User(username='admin', is_admin=True)
        user.set_password('password')
        conversation = HermesConversation(
            user=user,
            conversation_key='rainwave-web-1-test',
            title='Weather',
        )
        db.session.add_all(
            [
                user,
                conversation,
                HermesMessage(conversation=conversation, role='user', content='first'),
                HermesMessage(conversation=conversation, role='assistant', content='reply'),
            ]
        )
        current = HermesMessage(
            conversation=conversation,
            role='user',
            content='current',
        )
        db.session.add(current)
        db.session.commit()

        self.assertEqual(
            build_fallback_history(conversation, current.id),
            [
                {'role': 'user', 'content': 'first'},
                {'role': 'assistant', 'content': 'reply'},
            ],
        )

    def test_build_fallback_history_only_loads_recent_messages(self):
        user = User(username='history-admin', is_admin=True)
        user.set_password('password')
        conversation = HermesConversation(
            user=user,
            conversation_key='rainwave-web-history-test',
            title='History',
        )
        db.session.add_all([user, conversation])
        db.session.flush()

        for index in range(8):
            db.session.add(
                HermesMessage(
                    conversation=conversation,
                    role='user' if index % 2 == 0 else 'assistant',
                    content=f'message-{index}',
                )
            )
            db.session.flush()

        current = HermesMessage(
            conversation=conversation,
            role='user',
            content='current',
        )
        db.session.add(current)
        db.session.commit()

        history = build_fallback_history(conversation, current.id)

        self.assertEqual(
            [message['content'] for message in history],
            [f'message-{index}' for index in range(2, 8)],
        )


if __name__ == '__main__':
    unittest.main()
