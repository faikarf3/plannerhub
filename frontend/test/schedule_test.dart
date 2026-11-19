import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:planner_hub/api/client.dart';
import 'package:planner_hub/auth.dart';
import 'package:planner_hub/schedule/schedule_screen.dart';
import 'package:planner_hub/scope.dart';
import 'package:planner_hub/theme.dart';

import 'today_test.dart' show FakeApi, action, categories;

Map<String, dynamic> repeat(int id, String label, List<int> days, String start, String end,
        {bool work = true, String? job = 'tutoring', String description = ''}) =>
    {
      'id': id, 'title': null, 'category_id': work ? 1 : 2, 'job': work ? job : null, 'weekdays': days,
      'start_time': '$start:00', 'end_time': '$end:00', 'starts_on': '2026-11-01', 'until': null,
      'note': null, 'label': label, 'description': description, 'is_work': work,
      'minutes_per_week': 180, 'active': true,
    };

Future<FakeApi> pumpSchedule(WidgetTester tester) async {
  final api = FakeApi({
    'GET /categories': (_) => categories,
    'GET /schedules': (_) => {
          'schedules': [
            repeat(1, 'Tutoring', [1], '15:00', '18:00', description: 'Tue 3:00pm–6:00pm'),
            repeat(2, 'Restaurant', [5, 6], '17:00', '01:00', job: 'restaurant',
                description: 'Sat, Sun 5:00pm–1:00am'),
          ],
          'paid_minutes_per_week': 1140,
        },
    'POST /schedules': (_) => action(30, 'Added repeat: Climbing, Mon 6:00pm–8:00pm'),
    'PATCH /schedules/1': (_) => action(31, 'Updated repeat: Tutoring, Tue 3:00pm–5:00pm'),
  });
  await tester.binding.setSurfaceSize(const Size(430, 1000));
  await tester.pumpWidget(AppScope(
    api: ApiClient(baseUrl: 'http://test', token: ({refresh = false}) async => 'test-token',
        httpClient: api.client),
    auth: Auth.withToken('test-token'),
    child: MaterialApp(theme: buildTheme(fonts: false), home: const ScheduleScreen()),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  return api;
}

void main() {
  testWidgets('lists repeats with the weekly paid total', (tester) async {
    await pumpSchedule(tester);
    expect(find.text('19h'), findsOneWidget);
    expect(find.text('Tutoring'), findsOneWidget);
    expect(find.text('Sat, Sun 5:00pm–1:00am'), findsOneWidget);
    expect(find.text('Paid'), findsNWidgets(2));
  });

  testWidgets('editing sends only what changed', (tester) async {
    final api = await pumpSchedule(tester);
    await tester.tap(find.text('Tutoring'));
    await tester.pumpAndSettle();
    expect(find.text('Edit repeat'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('Thursday'));
    await tester.pump();
    await tester.tap(find.text('Save'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(api.bodies['PATCH /schedules/1'], {'weekdays': [1, 3]});
    await tester.pumpAndSettle(const Duration(seconds: 7));
  });

  testWidgets('a new repeat needs what and a day', (tester) async {
    final api = await pumpSchedule(tester);
    await tester.tap(find.byTooltip('Add a repeat'));
    await tester.pumpAndSettle();
    expect(find.text('New repeat'), findsOneWidget);
    await tester.tap(find.text('Climbing'));
    await tester.pump();
    await tester.tap(find.text('Save'));
    await tester.pump();
    expect(api.calls, isNot(contains('POST /schedules'))); // no day picked yet
    await tester.tap(find.bySemanticsLabel('Monday'));
    await tester.pump();
    await tester.tap(find.text('Save'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(api.bodies['POST /schedules'], {
      'category_id': 2, 'weekdays': [0], 'start_time': '09:00', 'end_time': '10:00',
    });
    await tester.pumpAndSettle(const Duration(seconds: 7));
  });

  testWidgets('an overnight repeat says it ends the next day', (tester) async {
    await pumpSchedule(tester);
    await tester.tap(find.text('Restaurant'));
    await tester.pumpAndSettle();
    expect(find.text('Ends the next day'), findsOneWidget);
  });
}
