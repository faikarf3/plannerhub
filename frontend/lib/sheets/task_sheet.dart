import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Add a task (task == null) or edit one. Returns the applied action, if any.
class TaskSheet extends StatefulWidget {
  const TaskSheet({super.key, required this.categories, this.task});
  final List<Category> categories;
  final Task? task;

  @override
  State<TaskSheet> createState() => _TaskSheetState();
}

DateTime _endOf(DateTime d) => DateTime(d.year, d.month, d.day, 23, 59);

class _TaskSheetState extends State<TaskSheet> {
  late final _title = TextEditingController(text: widget.task?.title ?? '');
  late int? _categoryId = widget.task?.categoryId;
  late DateTime? _due = widget.task?.dueAt ?? (widget.task == null ? _endOf(DateTime.now()) : null);
  bool _busy = false;

  bool get _editing => widget.task != null;

  Map<String, DateTime?> get _shortcuts {
    final now = DateTime.now();
    return {
      'Today': _endOf(now),
      'Tomorrow': _endOf(now.add(const Duration(days: 1))),
      'Next week': _endOf(now.add(const Duration(days: 7))),
      'None': null,
    };
  }

  bool _isCustom() => _due != null && !_shortcuts.values.contains(_due);

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
    final title = _title.text.trim();
    if (title.isEmpty) return;
    final t = widget.task;
    if (t == null) {
      _run((api) => api.createTask(title: title, categoryId: _categoryId, dueAt: _due));
      return;
    }
    _run((api) => api.updateTask(
          t.id,
          title: title != t.title ? title : null,
          categoryId: _categoryId != t.categoryId ? _categoryId : null,
          dueAt: _due != t.dueAt ? _due : null,
          clearDue: _due == null && t.dueAt != null,
        ));
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final shortcuts = _shortcuts;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_editing ? 'TASK' : 'NEW TASK', style: sectionLabel()),
        TextField(
          controller: _title,
          autofocus: !_editing,
          textCapitalization: TextCapitalization.sentences,
          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4),
          decoration: const InputDecoration(
            hintText: 'What needs doing?',
            filled: false,
            contentPadding: EdgeInsets.symmetric(vertical: 12),
            border: UnderlineInputBorder(borderSide: BorderSide(color: Palette.border)),
            enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Palette.border)),
            focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: Palette.faint)),
          ),
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: 20),
        const FieldLabel('Category'),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final c in widget.categories)
            OptionChip(label: c.name, selected: c.id == _categoryId,
                onTap: () => setState(() => _categoryId = c.id)),
        ]),
        const SizedBox(height: 20),
        const FieldLabel('Due'),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final e in shortcuts.entries)
            OptionChip(label: e.key, selected: !_isCustom() && _due == e.value,
                onTap: () => setState(() => _due = e.value)),
          OptionChip(
            label: _isCustom() ? DateFormat('EEE, MMM d').format(_due!) : 'Pick date…',
            selected: _isCustom(),
            onTap: () async {
              final now = DateTime.now();
              final picked = await showDatePicker(context: context,
                  initialDate: _due ?? now, firstDate: now.subtract(const Duration(days: 365)),
                  lastDate: now.add(const Duration(days: 730)));
              if (picked != null) setState(() => _due = _endOf(picked));
            },
          ),
        ]),
        const SizedBox(height: 26),
        if (_editing) ...[
          PillButton(label: 'Mark done', icon: Icons.check, busy: _busy,
              onPressed: () => _run((api) => api.completeTask(widget.task!.id))),
          const SizedBox(height: 10),
        ],
        PillButton(
          label: _editing ? 'Save' : 'Add task',
          dark: _editing,
          busy: _busy && !_editing,
          onPressed: _title.text.trim().isEmpty ? null : _save,
        ),
        if (_editing)
          TextButton(
            onPressed: _busy ? null : () => _run((api) => api.deleteTask(widget.task!.id)),
            style: TextButton.styleFrom(foregroundColor: Palette.redDark, minimumSize: const Size.fromHeight(44)),
            child: const Text('Delete task', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
          ),
      ],
    );
  }
}
