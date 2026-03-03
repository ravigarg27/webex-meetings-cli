from webex_cli.commands.common import managed_client


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_managed_client_closes_after_context() -> None:
    client = _FakeClient()

    def factory(token):
        assert token is None
        return client

    with managed_client(client_factory=factory) as opened:
        assert opened is client
        assert opened.closed is False

    assert client.closed is True
