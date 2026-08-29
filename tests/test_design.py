def test_design_page_is_public_and_documents_the_style_boundary(client):
    response = client.get("/design")

    assert response.status_code == 200
    assert "the restrictions" in response.text
    assert "personal pages stay personal" in response.text
    assert ".fourm-shell" in response.text
    assert ".fourm-*" in response.text
