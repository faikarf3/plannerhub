import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:planner_hub/api/client.dart';
import 'package:planner_hub/auth.dart';
import 'package:planner_hub/calendar/calendar_screen.dart';
import 'package:planner_hub/scope.dart';
import 'package:planner_hub/theme.dart';

import 'today_test.dart' show FakeApi, action, categories, entry, utc;

Future<FakeApi> pumpCalendar(WidgetTester tester) async {
  final monday = mondayOf(DateTime.now());
  final tue = monday.add(const Duration(days: 1));
  final api = FakeApi({
    'GET /categories': (_) => categories,
    'GET /calendar': (_) => {
          'start': '', 'end': '',
          'entries': [entry(1, 1, monday.add(const Duration(hours: 9)), monday.add(const Duration(hours: 11)),
              job: 'tutoring')],
          'planned': [
            {'schedule_id': 4, 'on_date': '${tue.year}-${tue.month.toString().padLeft(2, '0')}-'
                '${tue.day.toString().padLeft(2, '0')}',
             'started_at': utc(tue.add(const Duration(hours: 10))),
             'ended_at': utc(tue.add(const Duration(hours: 12))),
             'label': 'SI session', 'category_id': 1, 'job': 'si_session', 'is_work': true,
             'status': 'planned', 'moved': false, 'time_entry_id': null},
          ],
          'tasks': [],
        },
    'POST /schedules/4/occurrences/${tue.year}-${tue.month.toString().padLeft(2, '0')}-'
        '${tue.day.toString().padLeft(2, '0')}/skip': (_) => action(20, 'Skipped SI session'),
  });
  api.client; // build the mock
  await tester.binding.setSurfaceSize(const Size(430, 900));
  await tester.pumpWidget(AppScope(
    api: ApiClient(baseUrl: 'http://test', token: ({refresh = false}) async => 'test-token',
        httpClient: api.client),
    auth: Auth.withToken('test-token'),
    child: MaterialApp(theme: buildTheme(fonts: false),
        home: const Scaffold(body: CalendarScreen(active: true))),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  return api;
}

void main() {
  testWidgets('shows logged and planned blocks for the week', (tester) async {
    final api = await pumpCalendar(tester);
    expect(api.calls, containsAll(['GET /calendar', 'GET /categories']));
    expect(find.text('Calendar'), findsOneWidget);
    expect(find.text('Tutoring'), findsOneWidget);
    expect(find.text('SI session'), findsOneWidget);
    expect(find.text('Paid work'), findsOneWidget);
  });

  testWidgets('a planned block can be skipped for this week', (tester) async {
    final api = await pumpCalendar(tester);
    await tester.tap(find.text('SI session'));
    await tester.pumpAndSettle();
    expect(find.text('Changes here apply to this week only.'), findsOneWidget);
    await tester.tap(find.text('Skip this week'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(api.calls.where((c) => c.endsWith('/skip')), hasLength(1));
    await tester.pumpAndSettle(const Duration(seconds: 7));
  });

  testWidgets('tapping a logged block opens it for editing', (tester) async {
    await pumpCalendar(tester);
    await tester.tap(find.text('Tutoring'));
    await tester.pumpAndSettle();
    expect(find.text('Logged'), findsWidgets);
    expect(find.text('Delete'), findsOneWidget);
  });

  testWidgets('an empty spot offers to plan or log', (tester) async {
    await pumpCalendar(tester);
    // An empty slot: Sunday's column, late in the visible range.
    final grid = tester.getRect(find.byType(SingleChildScrollView));
    await tester.tapAt(Offset(grid.right - 20, grid.bottom - 40));
    await tester.pumpAndSettle();
    expect(find.text('New block'), findsOneWidget);
    expect(find.text('Plan it'), findsOneWidget);
    expect(find.text('Log it'), findsOneWidget);
  });

  testWidgets('week arrows load another week', (tester) async {
    final api = await pumpCalendar(tester);
    final before = api.calls.where((c) => c == 'GET /calendar').length;
    await tester.tap(find.byTooltip('Next week'));
    await tester.pump(const Duration(milliseconds: 50));
    expect(api.calls.where((c) => c == 'GET /calendar').length, before + 1);
    expect(find.text('This week'), findsOneWidget);
  });
}
