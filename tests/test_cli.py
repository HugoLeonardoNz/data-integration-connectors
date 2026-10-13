"""A linha de comando de ponta a ponta, como no README."""

from __future__ import annotations

from conectores import cli, config


def test_ciclo_completo_e_status_pela_linha_de_comando(
    conn, api, banco_de_teste, monkeypatch, capsys
):
    monkeypatch.setattr(config, "DATABASE_URL", banco_de_teste)
    monkeypatch.setattr(config, "API_URL", str(api.base_url))

    assert cli.main(["ciclo"]) == 0
    primeira = capsys.readouterr().out
    assert cli.main(["ciclo"]) == 0
    segunda = capsys.readouterr().out
    assert cli.main(["status"]) == 0

    # 5 recursos, 3 empresas. Na segunda passada, nada novo e nada alterado.
    assert len(primeira.splitlines()) == len(segunda.splitlines()) == 15
    assert all("novas     0  alteradas     0" in linha for linha in segunda.splitlines())


def test_status_sem_nenhuma_execucao_acusa_problema(conn, banco_de_teste, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", banco_de_teste)

    assert cli.main(["status"]) == 1
