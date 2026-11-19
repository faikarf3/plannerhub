import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'schedule_sheet.dart';

/// Every repeating weekly block, with the weekly paid-hours total.
class ScheduleScreen extends StatefulWidget {
  const ScheduleScreen({super.key});

  @override
  State<ScheduleScreen> createState() => _ScheduleScreenState();
}

class _ScheduleScreenState extends State<ScheduleScreen> {
  ScheduleList? _list;
  List<Category> _categories = const [];
  Object? _error;

  ApiClient get _api => AppScope.of(context).api;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([_api.schedules(), _api.categories()]);
      if (!mounted) return;
      setState(() {
        _list = results[0] as ScheduleList;
        _categories = results[1] as List<Category>;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _open({ScheduleItem? item}) async {
    final action = await showPlannerSheet<ActionResult>(
        context, (_) => ScheduleSheet(categories: _categories, item: item));
    if (action != null && mounted) {
      showUndo(context, action, onChanged: _load);
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final list = _list;
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          color: Palette.red,
          onRefresh: _load,
          child: ListView(padding: const EdgeInsets.fromLTRB(20, 4, 20, 32), children: [
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.chevron_left, size: 22),
                label: const Text('Calendar'),
                style: TextButton.styleFrom(foregroundColor: Palette.red, padding: const EdgeInsets.only(right: 8),
                    minimumSize: const Size(44, 44),
                    textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
              ),
            ),
            const SizedBox(height: 8),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              const Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Schedule', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -0.6)),
                  SizedBox(height: 4),
                  Text('Repeats every week as planned blocks', style: TextStyle(fontSize: 14, color: Palette.muted)),
                ]),
              ),
              IconButton.filled(
                tooltip: 'Add a repeat',
                onPressed: _categories.isEmpty ? null : () => _open(),
                style: IconButton.styleFrom(backgroundColor: Palette.red, fixedSize: const Size(44, 44)),
                icon: const Icon(Icons.add, color: Colors.white),
              ),
            ]),
            const SizedBox(height: 20),
            if (list == null && _error != null)
              Column(children: [
                Text(_error is ApiException ? (_error as ApiException).message : "Couldn't load your schedule.",
                    style: const TextStyle(color: Palette.body)),
                const SizedBox(height: 12),
                OutlinedButton(onPressed: _load, child: const Text('Try again')),
              ])
            else if (list == null)
              const Padding(padding: EdgeInsets.only(top: 60),
                  child: Center(child: CircularProgressIndicator(color: Palette.red)))
            else ...[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                decoration: BoxDecoration(color: Palette.redTint, borderRadius: BorderRadius.circular(14)),
                child: Row(children: [
                  const Expanded(child: Text('Paid work planned each week',
                      style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: Palette.redDeep))),
                  Text(duration(list.paidMinutesPerWeek), style: const TextStyle(fontSize: 17,
                      fontWeight: FontWeight.w700, color: Palette.redDeep)),
                ]),
              ),
              const SizedBox(height: 8),
              if (list.schedules.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Text('No repeats yet. Tap + to add tutoring, shifts or classes that happen every week.',
                      style: TextStyle(color: Palette.muted, fontSize: 15, height: 1.4)),
                ),
              for (final s in list.schedules) _row(s),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _row(ScheduleItem s) {
    final faded = !s.active;
    return InkWell(
      onTap: () => _open(item: s),
      child: Container(
        constraints: const BoxConstraints(minHeight: 64),
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Palette.line))),
        child: Row(children: [
          Container(width: 10, height: 10, decoration: BoxDecoration(shape: BoxShape.circle,
              color: s.isWork && !faded ? Palette.red : Palette.check)),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(s.label, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600,
                  color: faded ? Palette.muted : Palette.ink)),
              const SizedBox(height: 3),
              Text(faded ? '${s.description} · ended' : s.description,
                  style: const TextStyle(fontSize: 13, color: Palette.muted)),
            ]),
          ),
          if (s.isWork && !faded)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
              decoration: BoxDecoration(color: Palette.redTint, borderRadius: BorderRadius.circular(10)),
              child: const Text('Paid', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600,
                  color: Palette.redDark)),
            ),
          const SizedBox(width: 8),
          const Icon(Icons.chevron_right, size: 18, color: Palette.faint),
        ]),
      ),
    );
  }
}
