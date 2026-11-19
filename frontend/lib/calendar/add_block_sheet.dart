import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../sheets/clock_in_sheet.dart' show jobs;
import '../theme.dart';
import '../widgets/category_picker.dart';
import '../widgets/common.dart';
import '../widgets/segmented.dart';
import '../widgets/time_field.dart';

/// Tap an empty spot on the calendar: plan something (once, or every week) or
/// log time that already happened.
class AddBlockSheet extends StatefulWidget {
  const AddBlockSheet({super.key, required this.start, required this.categories});
  final DateTime start;
  final List<Category> categories;

  @override
  State<AddBlockSheet> createState() => _AddBlockSheetState();
}

class _AddBlockSheetState extends State<AddBlockSheet> {
  late bool _plan = widget.start.isAfter(DateTime.now()); // past spots default to logging
  int? _categoryId;
  String? _job;
  late DateTime _start = widget.start;
  late DateTime _end = widget.start.add(const Duration(hours: 1));
  bool _repeat = false;
  final _note = TextEditingController();
  bool _busy = false;

  String _hhmm(DateTime t) => DateFormat('HH:mm').format(t);

  String get _name {
    if (_job != null) return jobs[_job]!;
    return widget.categories.where((c) => c.id == _categoryId).firstOrNull?.name ?? 'Block';
  }

  Future<void> _submit() async {
    setState(() => _busy = true);
    final api = AppScope.of(context).api;
    final note = _note.text.trim();
    try {
      final ActionResult action;
      if (!_plan) {
        action = await api.logTime(categoryId: _categoryId!, job: _job, start: _start, end: _end, note: note);
      } else if (_repeat) {
        action = await api.createSchedule(categoryId: _categoryId!, job: _job,
            weekdays: [_start.weekday - 1], startTime: _hhmm(_start), endTime: _hhmm(_end),
            startsOn: _start, note: note);
      } else {
        action = await api.createTask(title: note.isNotEmpty ? note : _name, categoryId: _categoryId,
            scheduledStart: _start, scheduledEnd: _end);
      }
      if (mounted) Navigator.pop(context, action);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        showError(context, e);
      }
    }
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final weekday = DateFormat('EEEE').format(_start);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('New block', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
      Text(dayHeading(_start), style: const TextStyle(fontSize: 14, color: Palette.muted)),
      const SizedBox(height: 18),
      Segmented<bool>(options: const {true: 'Plan it', false: 'Log it'}, value: _plan,
          onChanged: (v) => setState(() => _plan = v)),
      const SizedBox(height: 18),
      CategoryPicker(categories: widget.categories, categoryId: _categoryId, job: _job,
          onChanged: (c, j) => setState(() {
                _categoryId = c;
                _job = j;
              })),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(child: TimeField(label: 'Start', value: _start, onChanged: (t) => setState(() {
              final length = _end.difference(_start);
              _start = atTime(_start, t);
              _end = _start.add(length);
            }))),
        const SizedBox(width: 12),
        Expanded(child: TimeField(label: 'End', value: _end,
            onChanged: (t) => setState(() => _end = endAfter(_start, t)))),
      ]),
      if (_plan) ...[
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.only(left: 14),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFEEEEEE))),
          child: SwitchListTile(
            value: _repeat,
            onChanged: (v) => setState(() => _repeat = v),
            activeTrackColor: Palette.red,
            contentPadding: const EdgeInsets.only(right: 8),
            title: const Text('Repeat weekly', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500)),
            subtitle: Text(_repeat ? 'Every $weekday, ${clock(_start)}–${clock(_end)}' : 'Just this once',
                style: const TextStyle(fontSize: 12, color: Palette.muted)),
          ),
        ),
      ],
      const SizedBox(height: 18),
      const FieldLabel('Note'),
      TextField(controller: _note, decoration: const InputDecoration(hintText: 'Optional')),
      const SizedBox(height: 22),
      PillButton(
        label: !_plan ? 'Log time' : (_repeat ? 'Add weekly repeat' : 'Add to plan'),
        busy: _busy,
        onPressed: categoryComplete(widget.categories, _categoryId, _job) ? _submit : null,
      ),
    ]);
  }
}
