import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:planner_hub/api/client.dart';
import 'package:planner_hub/auth.dart';
import 'package:planner_hub/scope.dart';
import 'package:planner_hub/theme.dart';
import 'package:planner_hub/today/today_screen.dart';

/// A fake backend: records requests and answers from `routes` ("GET /today").
class FakeApi {
  FakeApi(this.routes);
  final Map<String, Object? Function(Map<String, dynamic>? body)> routes;
  final calls = <String>[];

  late final client = MockClient((req) async {
    final key = '${req.method} ${req.url.path}';
    calls.add(key);
    expect(req.headers['Authorization'], 'Bearer test-token');
    final handler = routes[key];
    if (handler == null) return http.Response('{"message":"no route $key"}', 404);
    final body = req.body.isEmpty ? null : (jsonDecode(req.body) as Map).cast<String, dynamic>();
    return http.Response.bytes(utf8.encode(jsonEncode(handler(body))), 200,
        headers: {'content-type': 'application/json; charset=utf-8'});
  });
}

String utc(DateTime local) => local.toUtc().toIso8601String();

final categories = [
  {'id': 1, 'name': 'Work', 'color': null, 'parent_id': null, 'is_work': true, 'weekly_target_hours': null},
  {'id': 2, 'name': 'Climbing', 'color': null, 'parent_id': null, 'is_work': false, 'weekly_target_hours': null},
  {'id': 3, 'name': 'Job Search', 'color': null, 'parent_id': null, 'is_work': false, 'weekly_target_hours': null},
];

Map<String, dynamic> entry(int id, int category, DateTime start, DateTime? end, {String? job}) => {
      'id': id, 'category_id': category, 'task_id': null, 'job': job, 'started_at': utc(start),
      'ended_at': end == null ? null : utc(end),
      'duration_min': end?.difference(start).inMinutes, 'source': 'manual', 'confirmed': true, 'note': null,
    };

Map<String, dynamic> action(int id, String summary) =>
    {'action_id': id, 'action_type': 'x', 'summary': summary, 'result': {}};

Future<FakeApi> pumpToday(WidgetTester tester, {required bool running}) async {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final api = FakeApi({
    'GET /categories': (_) => categories,
    'GET /today': (_) => {
          'date': '2026-11-18',
          'tasks_due': [
            {'id': 7, 'title': 'Follow up Traveloka', 'category_id': 3, 'status': 'todo',
             'due_at': utc(DateTime(today.year, today.month, today.day, 23, 59)),
             'scheduled_start': null, 'scheduled_end': null, 'recurrence_rule': null,
             'source': 'manual', 'linked_type': null, 'linked_id': null, 'completed_at': null},
          ],
          'running_timer': running ? entry(3, 2, now.subtract(const Duration(minutes: 84)), null) : null,
          'time_entries': [
            entry(1, 1, today.add(const Duration(hours: 0)), today.add(const Duration(hours: 2)), job: 'tutoring'),
            if (running) entry(3, 2, now.subtract(const Duration(minutes: 84)), null),
          ],
          'planned_blocks': [],
          'minutes_by_category': {},
        },
    'POST /timer/stop': (_) => action(10, 'Stopped Climbing at 3:24pm (1h 24m)'),
    'POST /tasks/7/complete': (_) => action(11, 'Done: "Follow up Traveloka"'),
    'POST /log': (body) => {
          'journal_entry_id': 5, 'parsed': true, 'via': 'quickadd',
          'actions': [action(12, 'Logged 2h Climbing, 2:00pm–4:00pm at Vital')],
          'clarify': null, 'error': null, 'message': 'Logged 2h Climbing',
        },
  });
  await tester.pumpWidget(AppScope(
    api: ApiClient(baseUrl: 'http://test', token: ({refresh = false}) async => 'test-token',
        httpClient: api.client),
    auth: Auth.withToken('test-token'),
    child: MaterialApp(theme: buildTheme(fonts: false), home: const Scaffold(body: TodayScreen())),
  ));
  await tester.pump(); // post-frame load
  await tester.pump(const Duration(milliseconds: 50));
  return api;
}

void main() {
  testWidgets('running timer, tasks and log; Stop calls the API', (tester) async {
    final api = await pumpToday(tester, running: true);
    expect(find.text('Climbing'), findsWidgets);
    expect(find.text('Stop'), findsOneWidget);
    expect(find.text('Follow up Traveloka'), findsOneWidget);
    expect(find.text('Today'), findsWidgets);
    expect(find.text('Tutoring'), findsOneWidget);

    await tester.tap(find.text('Stop'));
    await tester.pump(const Duration(milliseconds: 50));
    expect(api.calls, contains('POST /timer/stop'));
    expect(find.text('Stopped Climbing at 3:24pm (1h 24m)'), findsOneWidget);
    expect(find.text('Undo'), findsOneWidget);
    await tester.pump(const Duration(seconds: 7)); // let the snackbar and ticker settle
  });

  testWidgets('no timer: Start timer and Clock in are offered', (tester) async {
    await pumpToday(tester, running: false);
    expect(find.text('No timer running'), findsOneWidget);
    expect(find.text('Clock in'), findsOneWidget);
    expect(find.text('Start timer'), findsOneWidget);
  });

  testWidgets('completing a task', (tester) async {
    final api = await pumpToday(tester, running: false);
    await tester.tap(find.byTooltip('Mark "Follow up Traveloka" done'));
    await tester.pump(const Duration(milliseconds: 50));
    expect(api.calls, contains('POST /tasks/7/complete'));
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('logging shows what changed with undo', (tester) async {
    final api = await pumpToday(tester, running: false);
    await tester.enterText(find.byType(TextField), 'climb 2h vital');
    await tester.pump(); // the mic button turns into "send" once there's text
    await tester.tap(find.byTooltip('Log it'));
    await tester.pump(const Duration(milliseconds: 100)); // the request resolves
    await tester.pumpAndSettle(); // the sheet slides up
    expect(api.calls, contains('POST /log'));
    expect(find.text('“climb 2h vital”'), findsOneWidget);
    expect(find.text('Logged 2h Climbing, 2:00pm–4:00pm at Vital'), findsOneWidget);
    expect(find.text('Done'), findsOneWidget);
  });
}
