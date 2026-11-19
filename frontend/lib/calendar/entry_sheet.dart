import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/category_picker.dart';
import '../widgets/common.dart';
import '../widgets/time_field.dart';

/// Edit or delete logged time; for the running timer, change its start or stop it.
class EntrySheet extends StatefulWidget {
  const EntrySheet({super.key, required this.entry, required this.categories});
  final TimeEntry entry;
  final List<Category> categories;

  @override
  State<EntrySheet> createState() => _EntrySheetState();
}

class _EntrySheetState extends State<EntrySheet> {
  late int _categoryId = widget.entry.categoryId;
  late String? _job = widget.entry.job;
  late DateTime _start = widget.entry.startedAt;
  late DateTime? _end = widget.entry.endedAt;
  late final _note = TextEditingController(text: widget.entry.note ?? '');
  bool _busy = false;

  TimeEntry get _e => widget.entry;

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

  void _save() => _run((api) => api.updateTimeEntry(
        _e.id,
        categoryId: _categoryId != _e.categoryId ? _categoryId : null,
        job: _job != _e.job ? _job : null,
        start: _start != _e.startedAt ? _start : null,
        end: _end != _e.endedAt ? _end : null,
        note: _note.text.trim() != (_e.note ?? '') ? _note.text.trim() : null,
      ));

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final running = _e.running;
    final name = widget.categories.where((c) => c.id == _categoryId).firstOrNull?.name ?? 'Time';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(color: running ? Palette.red : Palette.grey,
              borderRadius: BorderRadius.circular(10)),
          child: Text(running ? 'Running' : 'Logged', style: TextStyle(fontSize: 12,
              fontWeight: FontWeight.w600, color: running ? Colors.white : Palette.body)),
        ),
      ),
      const SizedBox(height: 6),
      Text(name, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
      Text(dayHeading(_start), style: const TextStyle(fontSize: 14, color: Palette.muted)),
      const SizedBox(height: 18),
      CategoryPicker(
        categories: widget.categories, categoryId: _categoryId, job: _job,
        onChanged: (c, j) => setState(() {
          _categoryId = c;
          _job = j;
        }),
      ),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(child: TimeField(label: 'Start', value: _start,
            onChanged: (t) => setState(() => _start = atTime(_start, t)))),
        const SizedBox(width: 12),
        Expanded(
          child: running
              ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('End', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600,
                      color: Palette.muted)),
                  const SizedBox(height: 6),
                  SizedBox(
                    height: 48,
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _busy ? null : () => _run((api) => api.stopTimer()),
                      style: FilledButton.styleFrom(backgroundColor: Palette.red,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
                      child: const Text('Stop now', style: TextStyle(fontWeight: FontWeight.w600)),
                    ),
                  ),
                ])
              : TimeField(label: 'End', value: _end!,
                  onChanged: (t) => setState(() => _end = endAfter(_start, t))),
        ),
      ]),
      const SizedBox(height: 18),
      const FieldLabel('Note'),
      TextField(controller: _note, decoration: const InputDecoration(hintText: 'Optional')),
      const SizedBox(height: 22),
      PillButton(label: 'Save', dark: true, busy: _busy,
          onPressed: categoryComplete(widget.categories, _categoryId, _job) ? _save : null),
      TextButton(
        onPressed: _busy ? null : () => _run((api) => api.deleteTimeEntry(_e.id)),
        style: TextButton.styleFrom(foregroundColor: Palette.redDark, minimumSize: const Size.fromHeight(44)),
        child: const Text('Delete', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
      ),
    ]);
  }
}
