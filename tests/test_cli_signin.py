"""Phase 2b Task 7: `dropwatch signin` prints the code and saves the TV session."""
import asyncio

from test_signin_api import CODE, S

from dropwatch.cli import cmd_signin
from dropwatch.store import Store


class Provider:
    async def start(self):
        return CODE

    async def wait(self, code, cancel):
        await asyncio.sleep(0)
        return S


async def test_cli_signin_prints_code_and_saves(tmp_path, capsys):
    store = Store(tmp_path / "d.db")
    assert await cmd_signin(store, provider=Provider()) == 0
    out = capsys.readouterr().out
    assert "https://www.twitch.tv/activate" in out and "BKDQMDGP" in out and "tok" not in out
    assert store.get_session() == S
