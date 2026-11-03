import asyncio

from admin import main as admin_main


def test_user_list_builds_table_and_delete_uses_repository(monkeypatch):
    notifications = []
    labels = []
    buttons = []
    tables = []

    def fake_label(text):
        labels.append(text)

    def fake_notify(msg):
        notifications.append(msg)

    class FakeButton:
        def __init__(self, on_click=None, icon=None):
            self.on_click = on_click
            self.enabled = True

        def disable(self):
            self.enabled = False

        def enable(self):
            self.enabled = True

    def fake_button(on_click=None, icon=None):
        b = FakeButton(on_click=on_click, icon=icon)
        buttons.append(b)
        return b

    class FakeTable:
        def __init__(self, *, columns, rows, row_key, on_select):
            self.columns = columns
            self.rows = rows
            self.row_key = row_key
            self.on_select = on_select
            self.selection_mode = None

        def set_selection(self, mode):
            self.selection_mode = mode

    def fake_table(**kwargs):
        t = FakeTable(**kwargs)
        tables.append(t)
        return t

    monkeypatch.setattr(admin_main.ui, "label", fake_label)
    monkeypatch.setattr(admin_main.ui, "button", fake_button)
    monkeypatch.setattr(admin_main.ui, "table", fake_table)
    monkeypatch.setattr(admin_main.ui, "notify", fake_notify)

    class FakeSchema:
        def __init__(self, model):
            self.model = model

        def model_dump(self):
            return {"name": self.model.name}

        @classmethod
        def from_db_model(cls, model):
            return cls(model)

    monkeypatch.setattr(admin_main, "UserSchema", FakeSchema)

    class FakeUser:
        def __init__(self, name):
            self.name = name

    class FakeResult:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class FakeRepo:
        def __init__(self):
            self.deleted = []

        async def get_all(self):
            return [FakeUser("alice"), FakeUser("bob")]

        async def delete(self, name: str):
            self.deleted.append(name)
            return FakeResult(rowcount=1)

    repo = FakeRepo()

    async def run():
        await admin_main.user_list(repo)

        assert labels == ["All Users"]
        assert len(tables) == 1
        table = tables[0]
        assert [row["name"] for row in table.rows] == ["alice", "bob"]
        assert len(buttons) == 1
        button = buttons[0]
        assert button.enabled is False
        assert table.selection_mode == "multiple"

        event = type("E", (), {"selection": [{"name": "alice"}, {"name": "bob"}]})()
        table.on_select(event)
        assert button.enabled is True

        await button.on_click()
        assert repo.deleted == ["alice", "bob"]
        assert notifications == [
            "Deleted user 'alice'",
            "Deleted user 'bob'",
        ]

    asyncio.run(run())


def test_index_create_uses_repository_and_refreshes_user_list(monkeypatch):
    calls = {"created": [], "user_list_called": 0, "refresh_called": 0}
    inputs = []
    buttons = []

    class FakeContainer:
        def classes(self, _):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_column():
        return FakeContainer()

    def fake_row():
        return FakeContainer()

    class FakeInput:
        def __init__(self, label=None):
            self.label = label
            self.value = ""

    def fake_input(label=None):
        inp = FakeInput(label=label)
        inputs.append(inp)
        return inp

    class FakeButton:
        def __init__(self, on_click=None, icon=None):
            self.on_click = on_click
            self.icon = icon

    def fake_button(on_click=None, icon=None):
        b = FakeButton(on_click=on_click, icon=icon)
        buttons.append(b)
        return b

    async def fake_user_list(user_repo):
        calls["user_list_called"] += 1

    def fake_refresh():
        calls["refresh_called"] += 1

    fake_user_list.refresh = fake_refresh

    class FakeRepo:
        async def create(self, *, name: str):
            calls["created"].append(name)

    monkeypatch.setattr(admin_main.ui, "column", fake_column)
    monkeypatch.setattr(admin_main.ui, "row", fake_row)
    monkeypatch.setattr(admin_main.ui, "input", fake_input)
    monkeypatch.setattr(admin_main.ui, "button", fake_button)
    monkeypatch.setattr(admin_main, "user_list", fake_user_list)

    repo = FakeRepo()

    async def run():
        await admin_main.index(repo)

        assert calls["user_list_called"] == 1
        assert len(inputs) == 1
        name_input = inputs[0]
        name_input.value = "charlie"

        assert len(buttons) == 1
        create_button = buttons[0]
        await create_button.on_click()

        assert calls["created"] == ["charlie"]
        assert name_input.value == ""
        assert calls["refresh_called"] == 1

    asyncio.run(run())
