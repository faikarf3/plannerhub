import 'package:flutter_test/flutter_test.dart';
import 'package:planner_hub/format.dart';

void main() {
  test('durations match the backend summaries', () {
    expect(duration(84), '1h 24m');
    expect(duration(120), '2h');
    expect(duration(45), '45m');
    expect(duration(61), '1h 01m');
  });

  test('stopwatch', () {
    expect(stopwatch(const Duration(hours: 1, minutes: 24, seconds: 8)), '1:24:08');
    expect(stopwatch(const Duration(seconds: -5)), '0:00:00');
  });

  test('due labels', () {
    final now = DateTime(2026, 11, 18, 14, 30); // Wednesday
    expect(dueLabel(DateTime(2026, 11, 18, 23, 59), now).text, 'Today');
    expect(dueLabel(DateTime(2026, 11, 18, 17), now).text, '5:00 PM');
    expect(dueLabel(DateTime(2026, 11, 18, 9), now), (text: 'Overdue', urgent: true));
    expect(dueLabel(DateTime(2026, 11, 19, 23, 59), now).text, 'Tomorrow');
    expect(dueLabel(DateTime(2026, 11, 20, 23, 59), now), (text: 'Fri', urgent: false));
    expect(dueLabel(DateTime(2026, 12, 1, 23, 59), now).text, 'Dec 1');
  });
}
