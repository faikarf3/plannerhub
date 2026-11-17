def test_today_view(client):
    client.post("/tasks", json={"title": "PH201 slides", "category": "SI Prep",
                                "due_at": "2026-11-17T20:00:00"})
    client.post("/tasks", json={"title": "Tutoring", "category": "Work",
                                "scheduled_start": "2026-11-17T15:00:00",
                                "scheduled_end": "2026-11-17T18:00:00"})
    client.post("/tasks", json={"title": "Old thing", "due_at": "2026-11-10T12:00:00"})
    client.post("/time-entries", json={"category": "Climbing", "started_at": "2026-11-17T10:00:00",
                                       "ended_at": "2026-11-17T12:00:00"})

    t = client.get("/today", params={"day": "2026-11-17"}).json()
    assert {x["title"] for x in t["tasks_due"]} == {"PH201 slides", "Old thing"}
    assert [x["title"] for x in t["planned_shifts"]] == ["Tutoring"]
    assert t["minutes_by_category"] == {"Climbing": 120}


def test_morning_digest(client):
    client.post("/tasks", json={"title": "Submit OA", "due_at": "2026-11-18T17:00:00"})
    client.post("/tasks", json={"title": "Old thing", "due_at": "2026-11-10T12:00:00"})
    client.post("/tasks", json={"title": "SI session", "category": "Work",
                                "scheduled_start": "2026-11-18T10:00:00",
                                "scheduled_end": "2026-11-18T11:30:00"})
    client.post("/time-entries", json={"category": "Job Search", "duration_min": 90,
                                       "ended_at": "2026-11-17T21:00:00", "confirmed": False})

    d = client.get("/digest/morning", params={"day": "2026-11-18"}).json()
    assert [t["title"] for t in d["due_today"]] == ["Submit OA"]
    assert [t["title"] for t in d["overdue"]] == ["Old thing"]
    assert d["yesterday_minutes_by_category"] == {"Job Search": 90}
    assert d["yesterday_unconfirmed"] == 1
    assert "Shifts: SI session" in d["text"]
    assert "Job Search 1h 30m" in d["text"]
