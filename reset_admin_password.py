"""管理员密码重置脚本。

这个文件不是网页的一部分，而是命令行工具。
适合在你忘记后台密码时直接运行，用来重置或创建管理员账号。
"""

import argparse
import os


def build_parser():
    """Create the command-line parser for the password reset script."""
    parser = argparse.ArgumentParser(
        description='Reset the local admin password for this site.'
    )
    parser.add_argument(
        '--username',
        default='admin',
        help='Username to update. Defaults to admin.',
    )
    parser.add_argument(
        '--password',
        required=True,
        help='New password to set for the target user.',
    )
    parser.add_argument(
        '--create-if-missing',
        action='store_true',
        help='Create an admin user when the username does not exist.',
    )
    return parser


def main():
    """Reset an existing admin password or create a local admin account."""
    args = build_parser().parse_args()

    os.environ.setdefault('LOCAL_DEV', '1')

    from backend.core.app import create_app
    from backend.core.models import User, db

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=args.username).first()

        if user is None:
            if not args.create_if_missing:
                raise SystemExit(
                    f"User '{args.username}' does not exist. "
                    'Use --create-if-missing to create a local admin account.'
                )

            user = User(username=args.username, is_admin=True)
            db.session.add(user)

        user.set_password(args.password)
        if not user.is_admin:
            user.is_admin = True

        db.session.commit()
        print(f'reset-ok username={user.username} is_admin={user.is_admin}')


if __name__ == '__main__':
    main()
