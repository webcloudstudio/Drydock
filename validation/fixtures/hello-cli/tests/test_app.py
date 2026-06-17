from app import main


def test_main(capsys):
    main()
    captured = capsys.readouterr()
    assert captured.out == "hello world\n"
    assert captured.err == ""
