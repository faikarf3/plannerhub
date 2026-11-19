import 'package:intl/intl.dart';

/// "1h 24m", "2h", "45m" (matches the backend's summaries).
String duration(int minutes) {
  final h = minutes ~/ 60, m = minutes % 60;
  if (h > 0 && m > 0) return '${h}h ${m.toString().padLeft(2, '0')}m';
  return h > 0 ? '${h}h' : '${m}m';
}

/// "1:24:08" for the running timer.
String stopwatch(Duration d) {
  final s = d.inSeconds.clamp(0, 1 << 31);
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  String two(int n) => n.toString().padLeft(2, '0');
  return '$h:${two(m)}:${two(sec)}';
}

/// "2:00 PM"
String clock(DateTime t) => DateFormat('h:mm a').format(t);

/// "9:00" without am/pm, for compact ranges like "9:00–11:00".
String shortClock(DateTime t) => DateFormat('h:mm').format(t);

/// "Wed, Nov 18"
String dayHeading(DateTime t) => DateFormat('EEE, MMM d').format(t);

bool sameDay(DateTime a, DateTime b) =>
    a.year == b.year && a.month == b.month && a.day == b.day;

/// Due label for a task row: "Overdue", "Today", "5:00 PM", "Tomorrow", "Fri", "Nov 28".
({String text, bool urgent}) dueLabel(DateTime due, DateTime now) {
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(due.year, due.month, due.day);
  final days = day.difference(today).inDays;
  final endOfDay = due.hour == 23 && due.minute == 59;
  if (due.isBefore(now) && !(days == 0 && endOfDay)) return (text: 'Overdue', urgent: true);
  if (days == 0) return (text: endOfDay ? 'Today' : clock(due), urgent: true);
  if (days == 1) return (text: 'Tomorrow', urgent: false);
  if (days < 7) return (text: DateFormat('EEE').format(due), urgent: false);
  return (text: DateFormat('MMM d').format(due), urgent: false);
}
