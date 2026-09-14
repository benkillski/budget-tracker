from sqlmodel import select

from app.models import Category


def test_create_category_persists_limit_in_cents(session, client):
    response = client.post(
        "/settings/categories",
        data={"name": "Groceries", "monthly_limit": "300.00"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    category = session.exec(select(Category)).first()
    assert category.name == "Groceries"
    assert category.monthly_limit_cents == 30000


def test_update_category_limit_changes_existing_category(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"monthly_limit": "150.50"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(category)
    assert category.monthly_limit_cents == 15050


def test_settings_page_shows_simplefin_not_configured_by_default(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Not configured" in response.text
