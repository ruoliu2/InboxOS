def _sync(client):
    response = client.post("/sync/start", json={})
    assert response.status_code == 200


def test_sync_and_thread_list(authenticated_client):
    _sync(authenticated_client)

    response = authenticated_client.get("/threads")
    assert response.status_code == 200
    threads = response.json()

    assert len(threads) == 3
    assert any("to_reply" in thread["action_states"] for thread in threads)


def test_analyze_creates_deadline_task(authenticated_client):
    _sync(authenticated_client)

    response = authenticated_client.post("/threads/thr_1001/analyze")
    assert response.status_code == 200
    payload = response.json()

    assert payload["thread_id"] == "thr_1001"
    assert payload["analysis"]["deadlines"]

    tasks = authenticated_client.get("/tasks").json()
    assert any(task["thread_id"] == "thr_1001" for task in tasks)


def test_reply_updates_thread_for_mail_ui(authenticated_client):
    _sync(authenticated_client)

    response = authenticated_client.post(
        "/threads/thr_1001/reply",
        json={
            "body": "Thanks, I will send the requested details this afternoon.",
            "mute_thread": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["muted"] is True
    assert payload["sent_message"]["sender"] == "you@example.com"
    assert payload["sent_message"]["body"] == (
        "Thanks, I will send the requested details this afternoon."
    )
    assert payload["thread"]["action_states"] == ["fyi"]
    assert payload["thread"]["snippet"] == (
        "Thanks, I will send the requested details this afternoon."
    )

    thread = authenticated_client.get("/threads/thr_1001").json()
    assert thread["messages"][-1]["body"] == payload["sent_message"]["body"]
    assert thread["action_states"] == ["fyi"]
