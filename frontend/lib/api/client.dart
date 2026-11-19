import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';

import 'models.dart';

/// A failed request, with the backend's human-readable `message` when it sent one.
class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status; // 0 = couldn't reach the server
  final String message;
  @override
  String toString() => message;
}

/// Thin typed wrapper over the Planner Hub API. Every write goes through the
/// backend's action layer, so each one returns an action id that can be undone.
/// Gets the bearer token; `refresh` asks Firebase for a new one.
typedef TokenSource = Future<String?> Function({bool refresh});

class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.token,
    this.onUnauthorized,
    http.Client? httpClient,
    this.retryDelays = const [Duration(seconds: 1), Duration(seconds: 3)],
  }) : _http = httpClient ?? http.Client();

  final String baseUrl;
  final TokenSource token;

  /// Called with the server's message when it refuses the sign-in (a 401 that a
  /// fresh token didn't fix). The app signs out and shows it on the sign-in screen.
  final void Function(String message)? onUnauthorized;

  /// Waits before retrying a 503 (the server couldn't reach Google to check the sign-in).
  final List<Duration> retryDelays;
  final http.Client _http;

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? query}) async {
    var refreshed = false;
    var attempt = 0;
    while (true) {
      try {
        return await _once(method, path, body: body, query: query, refresh: refreshed);
      } on ApiException catch (e) {
        if (e.status == 401 && !refreshed && e.message.toLowerCase().contains('expired')) {
          refreshed = true; // one retry with a fresh Firebase token
          continue;
        }
        if (e.status == 503 && attempt < retryDelays.length) {
          await Future<void>.delayed(retryDelays[attempt++]);
          continue;
        }
        if (e.status == 401) onUnauthorized?.call(e.message);
        rethrow;
      }
    }
  }

  Future<dynamic> _once(String method, String path,
      {Object? body, Map<String, String>? query, required bool refresh}) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    final request = http.Request(method, uri);
    final t = await token(refresh: refresh);
    if (t != null) request.headers['Authorization'] = 'Bearer $t';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(request));
    } on http.ClientException {
      // Network-level failure only; anything else is a bug and should surface.
      throw ApiException(0, "Can't reach Planner Hub. Check your connection.");
    }
    final decoded = response.body.isEmpty ? null : jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode >= 400) {
      final message = decoded is Map && decoded['message'] is String
          ? decoded['message'] as String
          : 'Request failed (${response.statusCode})';
      throw ApiException(response.statusCode, message);
    }
    return decoded;
  }

  Future<Map<String, dynamic>> _obj(String method, String path, {Object? body, Map<String, String>? query}) async =>
      ((await _send(method, path, body: body, query: query)) as Map).cast<String, dynamic>();

  Future<ActionResult> _action(String method, String path, [Object? body]) async =>
      ActionResult.fromJson(await _obj(method, path, body: body));

  // ---- reads

  /// Who the server thinks we are; called right after sign-in to confirm the
  /// account is allowed ({"auth": "owner"|"firebase", "email", "uid"}).
  Future<Map<String, dynamic>> me() => _obj('GET', '/me');

  Future<TodayData> today() async => TodayData.fromJson(await _obj('GET', '/today'));

  Future<CalendarData> calendar(DateTime start, DateTime end) async =>
      CalendarData.fromJson(await _obj('GET', '/calendar', query: {'start': _day(start), 'end': _day(end)}));

  Future<List<Category>> categories() async => ((await _send('GET', '/categories')) as List)
      .map((e) => Category.fromJson((e as Map).cast<String, dynamic>()))
      .toList();

  // ---- logging

  Future<LogResult> log(String text) async => LogResult.fromJson(await _obj('POST', '/log', body: {'text': text}));

  Future<LogResult> clarify(int journalId, String answer) async =>
      LogResult.fromJson(await _obj('POST', '/clarify/$journalId', body: {'answer': answer}));

  Future<void> undo(int actionId) => _send('POST', '/actions/$actionId/undo');

  // ---- timer and shifts

  Future<ActionResult> startTimer({required int categoryId}) =>
      _action('POST', '/timer/start', {'category_id': categoryId});

  Future<ActionResult> stopTimer() => _action('POST', '/timer/stop');

  Future<ActionResult> clockIn(String job, {DateTime? at}) =>
      _action('POST', '/shifts/clock-in', {'job': job, if (at != null) 'at': at.toUtc().toIso8601String()});

  // ---- time entries

  Future<ActionResult> logTime({required int categoryId, String? job, required DateTime start,
          required DateTime end, String? note}) =>
      _action('POST', '/time-entries', {
        'category_id': categoryId, if (job != null) 'job': job,
        'started_at': _iso(start), 'ended_at': _iso(end),
        if (note != null && note.isNotEmpty) 'note': note,
      });

  Future<ActionResult> updateTimeEntry(int id,
          {int? categoryId, String? job, DateTime? start, DateTime? end, String? note}) =>
      _action('PATCH', '/time-entries/$id', {
        if (categoryId != null) 'category_id': categoryId,
        if (job != null) 'job': job,
        if (start != null) 'started_at': _iso(start),
        if (end != null) 'ended_at': _iso(end),
        if (note != null) 'note': note.isEmpty ? null : note,
      });

  Future<ActionResult> deleteTimeEntry(int id) => _action('DELETE', '/time-entries/$id');

  // ---- repeating schedule

  Future<ActionResult> createSchedule({required int categoryId, String? job, required List<int> weekdays,
          required String startTime, required String endTime, DateTime? startsOn, String? note}) =>
      _action('POST', '/schedules', {
        'category_id': categoryId, if (job != null) 'job': job, 'weekdays': weekdays,
        'start_time': startTime, 'end_time': endTime,
        if (startsOn != null) 'starts_on': _day(startsOn),
        if (note != null && note.isNotEmpty) 'note': note,
      });

  String _occ(PlannedBlock b) => '/schedules/${b.scheduleId}/occurrences/${b.onDate}';

  Future<ActionResult> skipOccurrence(PlannedBlock b) => _action('POST', '${_occ(b)}/skip');

  Future<ActionResult> moveOccurrence(PlannedBlock b, DateTime start, DateTime end) =>
      _action('POST', '${_occ(b)}/move', {'started_at': _iso(start), 'ended_at': _iso(end)});

  Future<ActionResult> confirmOccurrence(PlannedBlock b, {DateTime? start, DateTime? end}) =>
      _action('POST', '${_occ(b)}/confirm', {
        if (start != null) 'started_at': _iso(start),
        if (end != null) 'ended_at': _iso(end),
      });

  // ---- tasks

  Future<ActionResult> createTask({required String title, int? categoryId, DateTime? dueAt,
          DateTime? scheduledStart, DateTime? scheduledEnd}) =>
      _action('POST', '/tasks', {
        'title': title,
        if (categoryId != null) 'category_id': categoryId,
        if (dueAt != null) 'due_at': _iso(dueAt),
        if (scheduledStart != null) 'scheduled_start': _iso(scheduledStart),
        if (scheduledEnd != null) 'scheduled_end': _iso(scheduledEnd),
      });

  Future<ActionResult> updateTask(int id, {String? title, int? categoryId, DateTime? dueAt, bool clearDue = false}) =>
      _action('PATCH', '/tasks/$id', {
        if (title != null) 'title': title,
        if (categoryId != null) 'category_id': categoryId,
        if (dueAt != null) 'due_at': dueAt.toUtc().toIso8601String(),
        if (clearDue) 'due_at': null,
      });

  Future<ActionResult> completeTask(int id) => _action('POST', '/tasks/$id/complete');

  Future<ActionResult> deleteTask(int id) => _action('DELETE', '/tasks/$id');

  static String _iso(DateTime t) => t.toUtc().toIso8601String();
  static String _day(DateTime d) => DateFormat('yyyy-MM-dd').format(d);
}
