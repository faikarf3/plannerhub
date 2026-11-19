import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../sheets/clock_in_sheet.dart' show jobs;
import '../sheets/task_sheet.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/dashed_box.dart';
import 'add_block_sheet.dart';
import 'entry_sheet.dart';
import 'planned_sheet.dart';

const double hourHeight = 40;
const double _gutter = 40;

DateTime _dateOnly(DateTime t) => DateTime(t.year, t.month, t.day);
DateTime mondayOf(DateTime t) => _dateOnly(t).subtract(Duration(days: t.weekday - 1));

enum _Kind { work, other, running, planWork, planOther }

class _Block {
  _Block(this.start, this.end, this.label, this.kind, this.onTap, this.semantics);
  final DateTime start;
  final DateTime end;
  final String label;
  final _Kind kind;
  final VoidCallback onTap;
  final String semantics;
  int lane = 0;
}

/// Week grid, all 24 hours: logged time solid, planned time dashed, a red line at now.
class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key, required this.active});
  final bool active; // reload when the tab is shown again

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  DateTime _week = mondayOf(DateTime.now());
  CalendarData? _data;
  List<Category> _categories = const [];
  Object? _error;
  DateTime _now = DateTime.now();
  Timer? _clock;
  final _scroll = ScrollController(initialScrollOffset: 7 * hourHeight);

  ApiClient get _api => AppScope.of(context).api;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    _clock = Timer.periodic(const Duration(minutes: 1), (_) => setState(() => _now = DateTime.now()));
  }

  @override
  void didUpdateWidget(CalendarScreen old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _load();
  }

  @override
  void dispose() {
    _clock?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final week = _week;
    try {
      final results = await Future.wait([
        _api.calendar(week, week.add(const Duration(days: 6))),
        if (_categories.isEmpty) _api.categories(),
      ]);
      if (!mounted || week != _week) return; // the user moved on to another week
      setState(() {
        _data = results[0] as CalendarData;
        if (results.length > 1) _categories = results[1] as List<Category>;
        _error = null;
        _now = DateTime.now();
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  void _goTo(DateTime week) {
    setState(() {
      _week = week;
      _data = null;
    });
    _load();
  }

  Future<void> _open(Widget sheet) async {
    final action = await showPlannerSheet<ActionResult>(context, (_) => sheet);
    if (action != null && mounted) {
      showUndo(context, action, onChanged: _load);
      await _load();
    }
  }

  String _categoryName(int id) => _categories.where((c) => c.id == id).firstOrNull?.name ?? 'Time';
  bool _isWork(int id) => _categories.where((c) => c.id == id).firstOrNull?.isWork ?? false;

  /// Everything drawn on the grid, before splitting by day.
  List<_Block> _blocks(CalendarData data) {
    final out = <_Block>[];
    for (final e in data.entries) {
      final label = e.job != null ? (jobs[e.job] ?? e.job!) : _categoryName(e.categoryId);
      final end = e.endedAt ?? _now;
      final kind = e.running ? _Kind.running : (_isWork(e.categoryId) ? _Kind.work : _Kind.other);
      out.add(_Block(e.startedAt, end, label, kind,
          () => _open(EntrySheet(entry: e, categories: _categories)),
          '$label, ${e.running ? 'running' : 'logged'}, ${DateFormat('EEE h:mm a').format(e.startedAt)}'));
    }
    for (final b in data.planned.where((b) => b.status == 'planned')) {
      out.add(_Block(b.startedAt, b.endedAt, b.label, b.isWork ? _Kind.planWork : _Kind.planOther,
          () => _open(PlannedSheet(block: b)),
          '${b.label}, planned, ${DateFormat('EEE h:mm a').format(b.startedAt)}'));
    }
    for (final t in data.tasks.where((t) => t.scheduledStart != null)) {
      final start = t.scheduledStart!;
      out.add(_Block(start, t.scheduledEnd ?? start.add(const Duration(minutes: 30)), t.title,
          _isWork(t.categoryId) ? _Kind.planWork : _Kind.planOther,
          () => _open(TaskSheet(categories: _categories, task: t)),
          '${t.title}, planned, ${DateFormat('EEE h:mm a').format(start)}'));
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final days = [for (var i = 0; i < 7; i++) _week.add(Duration(days: i))];
    final thisWeek = _week == mondayOf(_now);
    return Column(children: [
      _header(thisWeek),
      _dayHeader(days),
      Expanded(
        child: _data == null
            ? Center(
                child: _error == null
                    ? const CircularProgressIndicator(color: Palette.red)
                    : Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(_error is ApiException ? (_error as ApiException).message : "Couldn't load the week.",
                            textAlign: TextAlign.center, style: const TextStyle(color: Palette.body)),
                        const SizedBox(height: 12),
                        OutlinedButton(onPressed: _load, child: const Text('Try again')),
                      ]),
              )
            : _grid(days, _blocks(_data!)),
      ),
      _legend(),
    ]);
  }

  Widget _header(bool thisWeek) {
    final end = _week.add(const Duration(days: 6));
    final range = _week.month == end.month
        ? '${DateFormat('MMM d').format(_week)} – ${end.day}'
        : '${DateFormat('MMM d').format(_week)} – ${DateFormat('MMM d').format(end)}';
    Widget arrow(IconData icon, String tip, int days) => IconButton(
          tooltip: tip,
          onPressed: () => _goTo(_week.add(Duration(days: days))),
          style: IconButton.styleFrom(side: const BorderSide(color: Color(0xFFEEEEEE)),
              fixedSize: const Size(44, 44)),
          icon: Icon(icon, size: 20, color: Palette.body),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 14),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(range, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: Palette.muted)),
            const SizedBox(height: 2),
            const Text('Calendar', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -0.6)),
          ]),
        ),
        if (!thisWeek)
          TextButton(
            onPressed: () => _goTo(mondayOf(DateTime.now())),
            style: TextButton.styleFrom(foregroundColor: Palette.red, minimumSize: const Size(44, 44)),
            child: const Text('This week', style: TextStyle(fontWeight: FontWeight.w600)),
          ),
        arrow(Icons.chevron_left, 'Previous week', -7),
        const SizedBox(width: 4),
        arrow(Icons.chevron_right, 'Next week', 7),
      ]),
    );
  }

  Widget _dayHeader(List<DateTime> days) => Container(
        padding: const EdgeInsets.fromLTRB(12 + _gutter, 0, 12, 6),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFFEEEEEE)))),
        child: Row(children: [
          for (final d in days)
            Expanded(
              child: Column(children: [
                Text(DateFormat('E').format(d)[0],
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Palette.muted)),
                const SizedBox(height: 2),
                Container(
                  width: 26, height: 26,
                  alignment: Alignment.center,
                  decoration: _dateOnly(d) == _dateOnly(_now)
                      ? const BoxDecoration(color: Palette.red, shape: BoxShape.circle)
                      : null,
                  child: Text('${d.day}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700,
                      color: _dateOnly(d) == _dateOnly(_now) ? Colors.white : Palette.ink)),
                ),
              ]),
            ),
        ]),
      );

  Widget _grid(List<DateTime> days, List<_Block> blocks) {
    return RefreshIndicator(
      color: Palette.red,
      onRefresh: _load,
      child: SingleChildScrollView(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
        child: SizedBox(
          height: 24 * hourHeight,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: _gutter, child: _hourLabels()),
            Expanded(
              child: CustomPaint(
                painter: _HourLines(),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final d in days) Expanded(child: _dayColumn(d, blocks)),
                ]),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _hourLabels() => Stack(children: [
        for (var h = 0; h < 24; h += 2)
          Positioned(
            top: math.max(h * hourHeight - 6, 0),
            right: 6,
            child: Text(DateFormat('h a').format(DateTime(2000, 1, 1, h)),
                style: const TextStyle(fontSize: 10, color: Palette.muted)),
          ),
      ]);

  Widget _dayColumn(DateTime day, List<_Block> all) {
    final dayStart = day, dayEnd = day.add(const Duration(days: 1));
    // This day's slice of each block (overnight blocks show on both days).
    final mine = <_Block>[
      for (final b in all)
        if (b.end.isAfter(dayStart) && b.start.isBefore(dayEnd))
          _Block(b.start.isBefore(dayStart) ? dayStart : b.start, b.end.isAfter(dayEnd) ? dayEnd : b.end,
              b.label, b.kind, b.onTap, b.semantics),
    ]..sort((a, b) => a.start.compareTo(b.start));
    // Overlapping blocks sit side by side.
    final laneEnds = <DateTime>[];
    for (final b in mine) {
      var lane = laneEnds.indexWhere((end) => !end.isAfter(b.start));
      if (lane == -1) {
        lane = laneEnds.length;
        laneEnds.add(b.end);
      } else {
        laneEnds[lane] = b.end;
      }
      b.lane = lane;
    }
    final lanes = math.max(laneEnds.length, 1);
    final isToday = _dateOnly(day) == _dateOnly(_now);
    double y(DateTime t) => t.difference(dayStart).inMinutes / 60 * hourHeight;

    return LayoutBuilder(builder: (context, box) {
      final laneWidth = box.maxWidth / lanes;
      return GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapUp: (details) {
          final halfHours = (details.localPosition.dy / (hourHeight / 2)).floor().clamp(0, 47);
          _open(AddBlockSheet(start: dayStart.add(Duration(minutes: halfHours * 30)), categories: _categories));
        },
        child: Container(
          decoration: BoxDecoration(
            color: isToday ? Palette.redTint.withValues(alpha: 0.6) : null,
            border: const Border(left: BorderSide(color: Color(0xFFF2F2F3))),
          ),
          child: Stack(clipBehavior: Clip.none, children: [
            for (final b in mine)
              Positioned(
                top: y(b.start) + 1,
                height: math.max(y(b.end) - y(b.start) - 2, 16),
                left: b.lane * laneWidth + 2,
                width: laneWidth - 4,
                child: _blockView(b),
              ),
            if (isToday) ...[
              Positioned(top: y(_now), left: -3, right: 0, child: Container(height: 2, color: Palette.red)),
              Positioned(top: y(_now) - 3, left: -5,
                  child: Container(width: 8, height: 8,
                      decoration: const BoxDecoration(color: Palette.red, shape: BoxShape.circle))),
            ],
          ]),
        ),
      );
    });
  }

  Widget _blockView(_Block b) {
    final (Color fill, Color text, Color? dash) = switch (b.kind) {
      _Kind.work => (const Color(0xFFFEE4E2), Palette.redDeep, null),
      _Kind.other => (const Color(0xFFF1F1F3), Palette.body, null),
      _Kind.running => (Palette.red, Colors.white, null),
      _Kind.planWork => (Colors.white, Palette.redDeep, const Color(0xFFF1A9A3)),
      _Kind.planOther => (Colors.white, Palette.body, Palette.check),
    };
    final label = Padding(
      padding: const EdgeInsets.fromLTRB(4, 3, 3, 2),
      child: Text(b.label, maxLines: 3, overflow: TextOverflow.clip,
          style: TextStyle(fontSize: 10, height: 1.2, fontWeight: FontWeight.w600, color: text)),
    );
    return Semantics(
      button: true,
      label: b.semantics,
      excludeSemantics: true,
      child: GestureDetector(
        onTap: b.onTap,
        child: dash != null
            ? DashedBox(color: dash, fill: fill, child: SizedBox.expand(child: label))
            : Container(
                decoration: BoxDecoration(color: fill, borderRadius: BorderRadius.circular(6)),
                child: label),
      ),
    );
  }

  Widget _legend() {
    Widget item(String text, Widget swatch) => Row(mainAxisSize: MainAxisSize.min, children: [
          swatch,
          const SizedBox(width: 6),
          Text(text, style: const TextStyle(fontSize: 12, color: Palette.muted)),
        ]);
    Widget solid(Color c) => Container(width: 12, height: 12,
        decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(3)));
    return Container(
      padding: const EdgeInsets.fromLTRB(12 + _gutter, 10, 12, 10),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Color(0xFFEEEEEE)))),
      child: Wrap(spacing: 16, runSpacing: 6, children: [
        item('Paid work', solid(const Color(0xFFFEE4E2))),
        item('Logged', solid(const Color(0xFFF1F1F3))),
        item('Planned', const SizedBox(width: 12, height: 12,
            child: DashedBox(color: Palette.faint, radius: 3, child: SizedBox.expand()))),
      ]),
    );
  }
}

class _HourLines extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = const Color(0xFFF2F2F3);
    for (var h = 0; h <= 24; h++) {
      canvas.drawRect(Rect.fromLTWH(0, h * hourHeight, size.width, 1), paint);
    }
  }

  @override
  bool shouldRepaint(_HourLines old) => false;
}
