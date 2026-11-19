import 'dart:async';

import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../sheets/clock_in_sheet.dart';
import '../sheets/log_result_sheet.dart';
import '../sheets/start_timer_sheet.dart';
import '../sheets/task_sheet.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'log_bar.dart';

class TodayScreen extends StatefulWidget {
  const TodayScreen({super.key});

  @override
  State<TodayScreen> createState() => _TodayScreenState();
}

class _TodayScreenState extends State<TodayScreen> with WidgetsBindingObserver {
  TodayData? _data;
  List<Category> _categories = const [];
  Object? _error;
  DateTime _now = DateTime.now();
  Timer? _ticker;

  ApiClient get _api => AppScope.of(context).api;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ticker?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load(); // logs from Siri while away
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([_api.today(), _api.categories()]);
      if (!mounted) return;
      setState(() {
        _data = results[0] as TodayData;
        _categories = results[1] as List<Category>;
        _error = null;
        _now = DateTime.now();
      });
      _syncTicker();
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  void _syncTicker() {
    final running = _data?.runningTimer != null;
    if (running && _ticker == null) {
      _ticker = Timer.periodic(const Duration(seconds: 1), (_) => setState(() => _now = DateTime.now()));
    } else if (!running) {
      _ticker?.cancel();
      _ticker = null;
    }
  }

  String _label(TimeEntry e) {
    if (e.job != null) return jobs[e.job] ?? e.job!;
    return _categories.where((c) => c.id == e.categoryId).firstOrNull?.name ?? 'Time';
  }

  Future<void> _act(Future<ActionResult> Function() call) async {
    try {
      final action = await call();
      if (!mounted) return;
      showUndo(context, action, onChanged: _load);
      await _load();
    } on ApiException catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _sheet(Widget sheet) async {
    final action = await showPlannerSheet<ActionResult>(context, (_) => sheet);
    if (action != null && mounted) {
      showUndo(context, action, onChanged: _load);
      await _load();
    }
  }

  Future<void> _logged(String said, LogResult result) =>
      showLogResult(context, said, result, onChanged: _load);

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Column(
      children: [
        Expanded(
          child: RefreshIndicator(
            color: Palette.red,
            onRefresh: _load,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
              children: [
                _header(),
                const SizedBox(height: 24),
                if (data == null && _error != null)
                  _problem()
                else if (data == null)
                  const Padding(
                    padding: EdgeInsets.only(top: 80),
                    child: Center(child: CircularProgressIndicator(color: Palette.red)),
                  )
                else ...[
                  data.runningTimer != null ? _timerCard(data.runningTimer!) : _idleCard(data),
                  if (data.plannedBlocks.isNotEmpty) ...[const SizedBox(height: 28), _planned(data)],
                  const SizedBox(height: 28),
                  _due(data),
                  const SizedBox(height: 28),
                  _loggedSection(data),
                ],
              ],
            ),
          ),
        ),
        LogBar(onLogged: _logged),
      ],
    );
  }

  Widget _header() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(dayHeading(_now), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500,
              color: Palette.muted)),
          const SizedBox(height: 2),
          const Text('Today', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -0.6)),
        ],
      );

  Widget _problem() => Padding(
        padding: const EdgeInsets.only(top: 40),
        child: Column(children: [
          Text(_error is ApiException ? (_error as ApiException).message : 'Couldn\'t load today.',
              textAlign: TextAlign.center, style: const TextStyle(color: Palette.body, fontSize: 15)),
          const SizedBox(height: 16),
          OutlinedButton(onPressed: _load, child: const Text('Try again')),
        ]),
      );

  Widget _timerCard(TimeEntry t) => Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: Palette.redTint,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: Palette.redBorder),
        ),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(width: 8, height: 8,
                    decoration: const BoxDecoration(color: Palette.red, shape: BoxShape.circle)),
                const SizedBox(width: 8),
                Text(_label(t), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600,
                    color: Palette.redDark)),
              ]),
              const SizedBox(height: 4),
              Text(stopwatch(_now.difference(t.startedAt)),
                  style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w600, letterSpacing: -0.6,
                      fontFeatures: [FontFeature.tabularFigures()])),
              Text('since ${clock(t.startedAt)}', style: const TextStyle(fontSize: 13, color: Palette.muted)),
            ]),
          ),
          FilledButton(
            onPressed: () => _act(_api.stopTimer),
            style: FilledButton.styleFrom(backgroundColor: Palette.red, minimumSize: const Size(84, 44),
                shape: const StadiumBorder(),
                textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
            child: const Text('Stop'),
          ),
        ]),
      );

  Widget _idleCard(TodayData data) {
    final last = data.timeEntries.where((e) => !e.running).lastOrNull;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(18),
          border: Border.all(color: const Color(0xFFEEEEEE))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text('No timer running', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        if (last != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text('${_label(last)} stopped at ${clock(last.endedAt!)} · '
                '${duration(last.durationMin ?? 0)} logged',
                style: const TextStyle(fontSize: 13, color: Palette.muted)),
          ),
        const SizedBox(height: 14),
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: () => _sheet(StartTimerSheet(categories: _categories)),
              icon: const Icon(Icons.play_arrow_rounded, size: 18),
              label: const Text('Start timer'),
              style: OutlinedButton.styleFrom(
                foregroundColor: Palette.ink, minimumSize: const Size.fromHeight(44),
                side: const BorderSide(color: Palette.border), shape: const StadiumBorder(),
                textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: FilledButton.icon(
              onPressed: () => _sheet(const ClockInSheet()),
              icon: const Icon(Icons.schedule, size: 18),
              label: const Text('Clock in'),
              style: FilledButton.styleFrom(
                backgroundColor: Palette.red, minimumSize: const Size.fromHeight(44),
                shape: const StadiumBorder(),
                textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
            ),
          ),
        ]),
      ]),
    );
  }

  Widget _planned(TodayData data) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('PLANNED', style: sectionLabel()),
          const SizedBox(height: 6),
          for (final b in data.plannedBlocks)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 9),
              child: Row(children: [
                SizedBox(
                  width: 112,
                  child: Text('${clock(b.startedAt)}–${shortClock(b.endedAt)}',
                      style: const TextStyle(fontSize: 13, color: Palette.muted)),
                ),
                Container(width: 8, height: 8, decoration: BoxDecoration(shape: BoxShape.circle,
                    color: b.isWork ? Palette.red : Palette.check)),
                const SizedBox(width: 10),
                Expanded(child: Text(b.label, style: TextStyle(fontSize: 16,
                    color: b.status == 'done' ? Palette.muted : Palette.ink))),
                if (b.status == 'done')
                  const Text('Done', style: TextStyle(fontSize: 13, color: Palette.muted)),
              ]),
            ),
        ],
      );

  Widget _due(TodayData data) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(child: Text('DUE', style: sectionLabel())),
            IconButton(
              tooltip: 'Add task',
              onPressed: () => _sheet(TaskSheet(categories: _categories)),
              style: IconButton.styleFrom(backgroundColor: Palette.redTint, fixedSize: const Size(32, 32),
                  minimumSize: const Size(32, 32)),
              icon: const Icon(Icons.add, size: 18, color: Palette.red),
            ),
          ]),
          if (data.tasksDue.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Text('Nothing due. Tap + to add a task.', style: TextStyle(color: Palette.muted)),
            ),
          for (final (i, t) in data.tasksDue.indexed) _taskRow(t, last: i == data.tasksDue.length - 1),
        ],
      );

  Widget _taskRow(Task t, {required bool last}) {
    final due = t.dueAt == null ? null : dueLabel(t.dueAt!, _now);
    return Container(
      decoration: BoxDecoration(
          border: last ? null : const Border(bottom: BorderSide(color: Palette.line))),
      child: Row(children: [
        IconButton(
          tooltip: 'Mark "${t.title}" done',
          onPressed: () => _act(() => _api.completeTask(t.id)),
          icon: Container(
            width: 24, height: 24,
            decoration: BoxDecoration(shape: BoxShape.circle,
                border: Border.all(color: Palette.check, width: 2)),
          ),
          padding: EdgeInsets.zero,
          visualDensity: VisualDensity.compact,
        ),
        const SizedBox(width: 4),
        Expanded(
          child: InkWell(
            onTap: () => _sheet(TaskSheet(categories: _categories, task: t)),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(t.title, style: const TextStyle(fontSize: 16)),
            ),
          ),
        ),
        if (due != null)
          Text(due.text, style: TextStyle(fontSize: 13,
              fontWeight: due.urgent ? FontWeight.w500 : FontWeight.w400,
              color: due.urgent ? Palette.redDark : Palette.muted)),
      ]),
    );
  }

  Widget _loggedSection(TodayData data) {
    final total = data.timeEntries.fold<int>(0, (sum, e) => sum + e.minutesAt(_now));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Expanded(child: Text('LOGGED', style: sectionLabel())),
          if (total > 0)
            Text(duration(total), style: const TextStyle(fontSize: 13, color: Palette.muted)),
        ]),
        const SizedBox(height: 6),
        if (data.timeEntries.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 10),
            child: Text('Nothing logged yet. Say or type what you did below.',
                style: TextStyle(color: Palette.muted)),
          ),
        for (final e in data.timeEntries)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 9),
            child: Row(children: [
              SizedBox(
                width: 104,
                child: Text(
                  '${shortClock(e.startedAt)}–${e.running ? 'now' : shortClock(e.endedAt!)}',
                  style: TextStyle(fontSize: 13, color: e.running ? Palette.redDark : Palette.muted,
                      fontFeatures: const [FontFeature.tabularFigures()]),
                ),
              ),
              Expanded(
                child: Text(_label(e) + (e.confirmed ? '' : ' (estimate)'),
                    style: const TextStyle(fontSize: 16)),
              ),
              Text(duration(e.minutesAt(_now)), style: TextStyle(fontSize: 14,
                  color: e.running ? Palette.redDark : Palette.body,
                  fontFeatures: const [FontFeature.tabularFigures()])),
            ]),
          ),
      ],
    );
  }
}
