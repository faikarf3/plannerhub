def _create(client, **body):
    body = {"title": "Follow up Traveloka", "category": "Job Search", **body}
    r = client.post("/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _undo(client, action_id, expect=200):
    r = client.post(f"/actions/{action_id}/undo")
    assert r.status_code == expect, r.text
    return r.json()


def test_auth_required(client):
    r = client.get("/tasks", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_create_and_undo(client):
    out = _create(client, due_at="2026-11-20T17:00:00")
    task = out["result"]["task"]
    # Naive datetimes are New York local time; stored/returned in UTC (EST = UTC-5).
    assert task["due_at"].startswith("2026-11-20T22:00:00")
    assert "Follow up Traveloka" in out["summary"]

    _undo(client, out["action_id"])
    assert client.get(f"/tasks/{task['id']}").status_code == 404
    # Undo is one-shot.
    _undo(client, out["action_id"], expect=409)


def test_missing_category_falls_back_to_personal(client):
    task = client.post("/tasks", json={"title": "Laundry"}).json()["result"]["task"]
    personal = next(c for c in client.get("/categories").json() if c["name"] == "Personal")
    assert task["category_id"] == personal["id"]


def test_unknown_category_rejected(client):
    r = client.post("/tasks", json={"title": "x", "category": "Nope"})
    assert r.status_code == 422


def test_update_and_undo_restores_old_values(client):
    task = _create(client, due_at="2026-11-20T17:00:00")["result"]["task"]
    r = client.patch(f"/tasks/{task['id']}",
                     json={"title": "Email Traveloka", "due_at": None, "category": "Personal"})
    assert r.status_code == 200, r.text
    updated = r.json()["result"]["task"]
    assert updated["title"] == "Email Traveloka" and updated["due_at"] is None

    _undo(client, r.json()["action_id"])
    restored = client.get(f"/tasks/{task['id']}").json()
    assert restored == task


def test_complete_and_undo(client):
    task = _create(client)["result"]["task"]
    r = client.post(f"/tasks/{task['id']}/complete")
    assert r.json()["result"]["task"]["status"] == "done"
    assert r.json()["result"]["task"]["completed_at"] is not None
    assert client.post(f"/tasks/{task['id']}/complete").status_code == 409

    _undo(client, r.json()["action_id"])
    restored = client.get(f"/tasks/{task['id']}").json()
    assert restored["status"] == "todo" and restored["completed_at"] is None


def test_delete_and_undo_relinks_time_entries(client):
    task = _create(client)["result"]["task"]
    entry = client.post("/time-entries", json={
        "category": "Job Search", "task_id": task["id"], "duration_min": 30,
    }).json()["result"]["time_entry"]

    r = client.delete(f"/tasks/{task['id']}")
    assert r.status_code == 200
    assert client.get(f"/time-entries/{entry['id']}").json()["task_id"] is None

    _undo(client, r.json()["action_id"])
    assert client.get(f"/tasks/{task['id']}").json() == task
    assert client.get(f"/time-entries/{entry['id']}").json()["task_id"] == task["id"]


def test_undo_of_undo_target_gone_is_conflict(client):
    out = _create(client)
    task_id = out["result"]["task"]["id"]
    done = client.post(f"/tasks/{task_id}/complete").json()
    _undo(client, out["action_id"])  # deletes the task
    _undo(client, done["action_id"], expect=404)


def test_action_log_lists_changes(client):
    out = _create(client)
    log = client.get("/actions").json()
    assert log[0]["id"] == out["action_id"]
    assert log[0]["undoable"] is True
