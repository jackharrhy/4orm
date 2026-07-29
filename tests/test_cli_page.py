def test_cli_page(client):
    response = client.get("/cli")
    assert response.status_code == 200
    assert "4orm cli" in response.text
    assert "/cli/download/macos-arm64" in response.text


def test_cli_download_redirect(client):
    response = client.get("/cli/download/linux-amd64", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].endswith("/4orm-linux-amd64.tar.gz")


def test_cli_download_unknown_target(client):
    response = client.get("/cli/download/commodore-64")
    assert response.status_code == 404
