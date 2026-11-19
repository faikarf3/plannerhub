import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/category_picker.dart';
import '../widgets/common.dart';
import '../widgets/segmented.dart';
import '../widgets/time_field.dart';

const _dayShort = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const _dayFull = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

TimeOfDay _parse(String hhmmss) {
  final parts = hhmmss.split(':');
  return TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1]));
}

String _hhmm(TimeOfDay t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

DateTime _asDate(TimeOfDay t) => DateTime(2000, 1, 1, t.hour, t.minute);

/// Add a repeat (item == null) or edit one. Returns the applied action.
class ScheduleSheet extends StatefulWidget {
  const ScheduleSheet({super.key, required this.categories, this.item});
  final List<Category> categories;
  final ScheduleItem? item;

  @override
  State<ScheduleSheet> createState() => _ScheduleSheetState();
}

class _ScheduleSheetState extends State<ScheduleSheet> {
  late int? _categoryId = widget.item?.categoryId;
  late String? _job = widget.item?.job;
  late final Set<int> _days = {...?widget.item?.weekdays};
  late TimeOfDay _start = widget.item == null ? const TimeOfDay(hour: 9, minute: 0) : _parse(widget.item!.startTime);
  late TimeOfDay _end = widget.item == null ? const TimeOfDay(hour: 10, minute: 0) : _parse(widget.item!.endTime);
  late DateTime? _until = widget.item?.until;
  late bool _hasEnd = widget.item?.until != null;
  late final _title = TextEditingController(text: widget.item?.title ?? '');
  bool _busy = false;

  bool get _overnight => _end.hour * 60 + _end.minute <= _start.hour * 60 + _start.minute;
  bool get _sameTime => _end == _start;
  bool get _valid => categoryComplete(widget.categories, _categoryId, _job) && _days.isNotEmpty && !_sameTime;

  Future<void> _run(Future<ActionResult> Function(ApiClient api) call) async {
    setState(() => _busy = true);
    try {
      final action = await call(AppScope.of(context).api);
      if (mounted) Navigator.pop(context, action);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        showError(context, e);
      }
    }
  }

  void _save() {
    final days = _days.toList()..sort();
    final until = _hasEnd ? _until : null;
    final title = _title.text.trim();
    final item = widget.item;
    if (item == null) {
      _run((api) => api.createSchedule(categoryId: _categoryId!, job: _job, weekdays: days,
          startTime: _hhmm(_start), endTime: _hhmm(_end), until: until, title: title));
      return;
    }
    final changes = <String, Object?>{
      if (_categoryId != item.categoryId) 'category_id': _categoryId,
      if (_job != item.job) 'job': _job,
      if (days.join(',') != ([...item.weekdays]..sort()).join(',')) 'weekdays': days,
      if (_hhmm(_start) != item.startTime.substring(0, 5)) 'start_time': _hhmm(_start),
      if (_hhmm(_end) != item.endTime.substring(0, 5)) 'end_time': _hhmm(_end),
      if (until != item.until) 'until': until == null ? null : ApiClient.day(until),
      if (title != (item.title ?? '')) 'title': title.isEmpty ? null : title,
    };
    if (changes.isEmpty) {
      Navigator.pop(context);
      return;
    }
    _run((api) => api.updateSchedule(item.id, changes));
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(widget.item == null ? 'New repeat' : 'Edit repeat',
          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
      const SizedBox(height: 18),
      CategoryPicker(categories: widget.categories, categoryId: _categoryId, job: _job,
          onChanged: (c, j) => setState(() {
                _categoryId = c;
                _job = j;
              })),
      const SizedBox(height: 18),
      const FieldLabel('Days'),
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        for (var i = 0; i < 7; i++)
          Semantics(
            button: true,
            selected: _days.contains(i),
            label: _dayFull[i],
            excludeSemantics: true,
            child: InkResponse(
              onTap: () => setState(() => _days.contains(i) ? _days.remove(i) : _days.add(i)),
              child: Container(
                width: 42, height: 42,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _days.contains(i) ? Palette.red : Colors.white,
                  border: _days.contains(i) ? null : Border.all(color: Palette.border),
                ),
                child: Text(_dayShort[i], style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600,
                    color: _days.contains(i) ? Colors.white : Palette.body)),
              ),
            ),
          ),
      ]),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(child: TimeField(label: 'Start', value: _asDate(_start),
            onChanged: (t) => setState(() => _start = t))),
        const SizedBox(width: 12),
        Expanded(child: TimeField(label: 'End', value: _asDate(_end), onChanged: (t) => setState(() => _end = t))),
      ]),
      if (_sameTime || _overnight)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_sameTime ? "Start and end can't be the same." : 'Ends the next day',
              style: TextStyle(fontSize: 13, color: _sameTime ? Palette.redDark : Palette.muted)),
        ),
      const SizedBox(height: 18),
      const FieldLabel('Until'),
      Segmented<bool>(options: const {false: 'No end', true: 'Until a date'}, value: _hasEnd,
          onChanged: (v) => setState(() {
                _hasEnd = v;
                _until ??= DateTime.now().add(const Duration(days: 30));
              })),
      if (_hasEnd) ...[
        const SizedBox(height: 10),
        OutlinedButton(
          onPressed: () async {
            final now = DateTime.now();
            final picked = await showDatePicker(context: context, initialDate: _until ?? now,
                firstDate: now.subtract(const Duration(days: 365)), lastDate: now.add(const Duration(days: 730)));
            if (picked != null) setState(() => _until = picked);
          },
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48), foregroundColor: Palette.ink,
              side: const BorderSide(color: Palette.border),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
          child: Text('Last time: ${DateFormat('EEE, MMM d').format(_until!)}',
              style: const TextStyle(fontSize: 16)),
        ),
      ],
      const SizedBox(height: 18),
      const FieldLabel('Name (optional)'),
      TextField(controller: _title, textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(hintText: 'e.g. PH201 lecture')),
      const SizedBox(height: 22),
      PillButton(label: 'Save', busy: _busy, onPressed: _valid ? _save : null),
      if (widget.item != null)
        TextButton(
          onPressed: _busy ? null : () => _run((api) => api.deleteSchedule(widget.item!.id)),
          style: TextButton.styleFrom(foregroundColor: Palette.redDark, minimumSize: const Size.fromHeight(44)),
          child: const Text('Delete repeat', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
        ),
    ]);
  }
}
