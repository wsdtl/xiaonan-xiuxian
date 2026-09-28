"""Command callbacks declare only the arguments they consume."""
import asyncio

import pytest

from launch.adapter.depends import Depends, call_with_dependencies
from launch.adapter.registry import MessageHandler, manager as public_manager


def test_bound_callback_filters_extra_fields_and_restores_manager():
    seen = []
    real_manager = object()

    async def callback(user_id: str, manager):
        seen.append((user_id, manager, manager._current_manager()))
        return 'done'

    bound = MessageHandler._bind_manager(callback, real_manager)
    result = asyncio.run(bound(user_id='player', message='unused', protocol_private=42))
    assert result == 'done'
    assert seen == [('player', public_manager, real_manager)]
    assert public_manager._current_manager() is not real_manager


def test_selected_parameters_keep_defaults_dependencies_and_missing_errors():
    calls = []

    def dependency(user_id: str):
        calls.append(user_id)
        return user_id.upper()

    async def callback(user_id: str, derived=Depends(dependency), page: int = 1):
        return user_id, derived, page

    assert asyncio.run(call_with_dependencies(callback, {'user_id': 'alice', 'extra': 42})) == ('alice', 'ALICE', 1)
    assert calls == ['alice']
    with pytest.raises(TypeError, match='命令参数：user_id'):
        asyncio.run(call_with_dependencies(callback, {'extra': 42}))


def test_explicit_variadic_callback_still_receives_context():
    def callback(user_id, **context):
        return user_id, context

    assert asyncio.run(call_with_dependencies(callback, {'user_id': 'alice', 'extra': 42})) == ('alice', {'extra': 42})


def test_registration_keeps_aliases_regex_order_and_reload_semantics(monkeypatch):
    import re
    from types import SimpleNamespace
    from game.cmd import command

    registered = []
    helps = []

    def registrar(kind):
        def register(**kwargs):
            def decorate(func):
                registered.append((kind, kwargs, func))
                return func
            return decorate
        return register

    monkeypatch.setattr(command, '_registered_commands', [])
    monkeypatch.setattr(command, '_registered_command_routes', [])
    monkeypatch.setattr(command, 'help_registry', SimpleNamespace(register=lambda *args, **kwargs: helps.append((args, kwargs))))
    for kind in ('command', 'fullmatch', 'regex'):
        monkeypatch.setattr(command.MessageHandler, kind, staticmethod(registrar(kind)))

    async def handler(user_id):
        return user_id

    metadata = {'scope': '通用', 'guard_rule': '已创建', 'hidden': True}
    command.GameCommand.command(('甲', '乙'), metadata=metadata)(handler)
    command.GameCommand.command(('甲', '丙'), metadata=metadata)(handler)
    assert [r[0] for r in command.registered_command_routes()] == ['甲', '丙']
    patterns = (re.compile('丁.*'), re.compile('戊.*'))
    command.GameCommand.regex(patterns, metadata=metadata)(handler)
    assert [r[0] for r in command.registered_command_routes()] == ['甲', '丙', '丁.*', '戊.*']
    assert [row[1]['cmd'] for row in registered[-2:]] == list(patterns)
    assert all(row[2] is handler for row in registered)
    assert not helps
    with pytest.raises(TypeError, match='正则命令'):
        command.GameCommand.regex('not a pattern', metadata=metadata)
    with pytest.raises(ValueError, match='scope'):
        command.GameCommand.fullmatch('己', metadata={**metadata, 'scope': '未知'})
