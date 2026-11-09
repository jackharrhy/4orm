import pytest

from tests.conftest import login_as, make_test_user


@pytest.fixture()
def csrf_member(raw_client, test_engine):
    with test_engine.begin() as conn:
        make_test_user(conn, "csrfuser")
    login_as(raw_client, "csrfuser")
    return raw_client


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example.com"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_origin_writes_are_rejected(csrf_member, headers):
    response = csrf_member.post(
        "/settings/profile", data={"display_name": "hacked"}, headers=headers
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://testserver"},
    ],
)
def test_same_origin_and_nonbrowser_writes_are_allowed(csrf_member, headers):
    response = csrf_member.post(
        "/settings/profile",
        data={"display_name": "Legit", "content": "hi"},
        headers=headers,
    )
    assert response.status_code in (200, 303)


@pytest.mark.parametrize("path", ["/login", "/register", "/feed.xml"])
def test_retired_login_and_readonly_feeds_do_not_bypass_csrf(raw_client, path):
    response = raw_client.post(path, headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403
