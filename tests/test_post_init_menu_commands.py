import os, sys, asyncio

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_post_init_menu_commands.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.calls = []
    async def set_my_commands(self, commands, **kw):
        self.calls.append(commands)


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (Victoria): missing a native Telegram "Menu" button next
    # to the text input, showing the bot's commands -- so the user doesn't
    # have to remember the bot understands slash commands at all.
    # set_my_commands (called from Application's post_init hook) is what
    # makes Telegram show that button. Only genuinely public commands
    # belong here -- the owner-only ones (/admin, /grant, /blogger, etc.,
    # all group=-1, gated by NOTIFY_USER_ID inside their own handlers)
    # must NOT leak into a menu every user sees.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    await bot._post_init(app)

    assert len(app.bot.calls) == 1, f"post_init must call set_my_commands exactly once, got: {app.bot.calls}"
    commands = app.bot.calls[0]
    cmd_names = {c.command for c in commands}

    assert cmd_names == {"start", "subscribe", "promo"}, \
        f"the bot's public command menu must be exactly start/subscribe/promo, got: {cmd_names}"
    print(f"1. set_my_commands is called with exactly the public commands: {sorted(cmd_names)}")

    admin_only = {"admin", "feedback", "research", "users", "send", "broadcast",
                  "newpromo", "blogger", "promocodes", "grant"}
    assert not (cmd_names & admin_only), \
        f"owner-only admin commands must never appear in the public command menu, got overlap: {cmd_names & admin_only}"
    print("2. None of the owner-only admin commands leak into the public menu")

    print("\nALL POST-INIT-MENU-COMMANDS TESTS PASSED")


asyncio.run(main())
