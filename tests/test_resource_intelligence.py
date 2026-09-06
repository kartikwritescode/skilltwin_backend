import asyncio
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_resource_upload_and_async_processing(async_client: AsyncClient, auth_headers: dict):
    content = b"Dart Streams provide reactive asynchronous programming. StreamController manages listeners."
    files = {"file": ("dart_streams_guide.txt", content, "text/plain")}
    data = {"title": "Dart Streams Guide", "is_public": "false"}

    upload_resp = await async_client.post("/api/v1/resources/upload", files=files, data=data, headers=auth_headers)
    assert upload_resp.status_code == 202
    upload_data = upload_resp.json()
    res_id = upload_data["id"]
    assert upload_data["title"] == "Dart Streams Guide"
    assert upload_data["processing_status"] in ["processing", "completed"]

    # Wait for async background processing
    res_data = {}
    for _ in range(30):
        get_resp = await async_client.get(f"/api/v1/resources/{res_id}", headers=auth_headers)
        if get_resp.status_code == 200:
            res_data = get_resp.json()
            if res_data.get("processing_status") == "completed":
                break
        await asyncio.sleep(0.05)

    assert get_resp.status_code == 200
    assert res_data["processing_status"] == "completed"
    assert res_data["chunk_count"] > 0
    assert len(res_data["extracted_concepts"]) > 0

@pytest.mark.asyncio
async def test_rag_retrieval_scoping_and_security(async_client: AsyncClient, auth_headers: dict):
    content_a = b"Confidential User A architectural note on microservices and distributed transaction logs."
    files_a = {"file": ("user_a_notes.txt", content_a, "text/plain")}
    data_a = {"title": "User A Private", "is_public": "false"}
    up_a = await async_client.post("/api/v1/resources/upload", files=files_a, data=data_a, headers=auth_headers)
    assert up_a.status_code == 202
    await asyncio.sleep(0.1)

    user_b_token = create_access_token(user_id="other_user_99", email="b@example.com")
    headers_b = {"Authorization": f"Bearer {user_b_token}"}

    search_payload = {"query": "distributed transaction logs", "top_k": 5}
    search_b = await async_client.post("/api/v1/resources/search", json=search_payload, headers=headers_b)
    assert search_b.status_code == 200
    results_b = search_b.json()["results"]
    assert not any(r["resource_title"] == "User A Private" for r in results_b)

    search_a = await async_client.post("/api/v1/resources/search", json=search_payload, headers=auth_headers)
    assert search_a.status_code == 200
    results_a = search_a.json()["results"]
    assert any(r["resource_title"] == "User A Private" for r in results_a)

@pytest.mark.asyncio
async def test_resource_crud_and_delete(async_client: AsyncClient, auth_headers: dict):
    content = b"Temporary deletion document."
    files = {"file": ("temp.txt", content, "text/plain")}
    up = await async_client.post("/api/v1/resources/upload", files=files, headers=auth_headers)
    res_id = up.json()["id"]

    list_resp = await async_client.get("/api/v1/resources", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(r["id"] == res_id for r in list_resp.json())

    del_resp = await async_client.delete(f"/api/v1/resources/{res_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_after = await async_client.get(f"/api/v1/resources/{res_id}", headers=auth_headers)
    assert get_after.status_code == 404
