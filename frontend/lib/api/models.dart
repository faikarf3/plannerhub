// Read models for the API's JSON. Times arrive in UTC and are shown in local time.

DateTime? _time(Object? v) => v == null ? null : DateTime.parse(v as String).toLocal();

Map<String, dynamic> _map(Object? v) => (v as Map).cast<String, dynamic>();

List<T> _list<T>(Object? v, T Function(Map<String, dynamic>) f) =>
    (v as List? ?? const []).map((e) => f(_map(e))).toList();

class Category {
  Category.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        name = j['name'] as String,
        isWork = j['is_work'] as bool;
  final int id;
  final String name;
  final bool isWork;
}

class Task {
  Task.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        title = j['title'] as String,
        categoryId = j['category_id'] as int,
        status = j['status'] as String,
        dueAt = _time(j['due_at']);
  final int id;
  final String title;
  final int categoryId;
  final String status;
  final DateTime? dueAt;
}

class TimeEntry {
  TimeEntry.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        categoryId = j['category_id'] as int,
        job = j['job'] as String?,
        startedAt = _time(j['started_at'])!,
        endedAt = _time(j['ended_at']),
        durationMin = j['duration_min'] as int?,
        confirmed = j['confirmed'] as bool? ?? true,
        note = j['note'] as String?;
  final int id;
  final int categoryId;
  final String? job;
  final DateTime startedAt;
  final DateTime? endedAt;
  final int? durationMin;
  final bool confirmed;
  final String? note;

  bool get running => endedAt == null;
  int minutesAt(DateTime now) => durationMin ?? now.difference(startedAt).inMinutes;
}

class PlannedBlock {
  PlannedBlock.fromJson(Map<String, dynamic> j)
      : scheduleId = j['schedule_id'] as int,
        onDate = j['on_date'] as String,
        startedAt = _time(j['started_at'])!,
        endedAt = _time(j['ended_at'])!,
        label = j['label'] as String,
        isWork = j['is_work'] as bool,
        status = j['status'] as String;
  final int scheduleId;
  final String onDate;
  final DateTime startedAt;
  final DateTime endedAt;
  final String label;
  final bool isWork;
  final String status;
}

/// One applied change (a line on a confirmation card).
class ActionResult {
  ActionResult.fromJson(Map<String, dynamic> j)
      : actionId = j['action_id'] as int,
        actionType = j['action_type'] as String,
        summary = j['summary'] as String;
  final int actionId;
  final String actionType;
  final String summary;
}

class Clarify {
  Clarify.fromJson(Map<String, dynamic> j)
      : question = j['question'] as String,
        options = (j['options'] as List? ?? const []).cast<String>();
  final String question;
  final List<String> options;
}

/// POST /log and /clarify response.
class LogResult {
  LogResult.fromJson(Map<String, dynamic> j)
      : journalEntryId = j['journal_entry_id'] as int,
        parsed = j['parsed'] as bool,
        actions = _list(j['actions'], ActionResult.fromJson),
        clarify = j['clarify'] == null ? null : Clarify.fromJson(_map(j['clarify'])),
        error = j['error'] as String?,
        message = j['message'] as String;
  final int journalEntryId;
  final bool parsed;
  final List<ActionResult> actions;
  final Clarify? clarify;
  final String? error;
  final String message;
}

class TodayData {
  TodayData.fromJson(Map<String, dynamic> j)
      : tasksDue = _list(j['tasks_due'], Task.fromJson),
        runningTimer = j['running_timer'] == null ? null : TimeEntry.fromJson(_map(j['running_timer'])),
        timeEntries = _list(j['time_entries'], TimeEntry.fromJson),
        plannedBlocks = _list(j['planned_blocks'], PlannedBlock.fromJson);
  final List<Task> tasksDue;
  final TimeEntry? runningTimer;
  final List<TimeEntry> timeEntries;
  final List<PlannedBlock> plannedBlocks;
}
