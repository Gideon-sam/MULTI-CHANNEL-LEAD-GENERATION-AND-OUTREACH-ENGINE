import pytest

from incubrix_engine.cli import _parser


def test_dashboard_server_is_private_by_default():
    args = _parser().parse_args(["serve"])
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert not args.allow_public


def test_dashboard_server_requires_explicit_public_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["incubrix-engine", "serve", "--host", "0.0.0.0"]
    )
    from incubrix_engine.cli import main

    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "Refusing a public bind" in capsys.readouterr().err
