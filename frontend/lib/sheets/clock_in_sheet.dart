import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/segmented.dart';

const jobs = {
  'tutoring': 'Tutoring',
  'si_session': 'SI session',
  'si_prep': 'SI prep',
  'restaurant': 'Restaurant',
};

/// Pick a job and clock in, now or earlier. Returns the applied action.
class ClockInSheet extends StatefulWidget {
  const ClockInSheet({super.key, this.running, this.runningLabel});
  final TimeEntry? running;
  final String? runningLabel;

  @override
  State<ClockInSheet> createState() => _ClockInSheetState();
}

class _ClockInSheetState extends State<ClockInSheet> {
  String _job = 'tutoring';
  bool _now = true;
  TimeOfDay _at = TimeOfDay.now();
  bool _busy = false;

  DateTime get _startAt {
    final n = DateTime.now();
    return DateTime(n.year, n.month, n.day, _at.hour, _at.minute);
  }

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      final action = await AppScope.of(context).api.clockIn(_job, at: _now ? null : _startAt);
      if (mounted) Navigator.pop(context, action);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        showError(context, e);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final running = widget.running;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Clock in', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
        const SizedBox(height: 18),
        for (final e in jobs.entries) ...[
          _JobRow(label: e.value, selected: e.key == _job, onTap: () => setState(() => _job = e.key)),
          const SizedBox(height: 8),
        ],
        const SizedBox(height: 10),
        const FieldLabel('Started'),
        Segmented<bool>(
          options: const {true: 'Now', false: 'Earlier'},
          value: _now,
          onChanged: (v) => setState(() => _now = v),
        ),
        if (!_now) ...[
          const SizedBox(height: 10),
          OutlinedButton(
            onPressed: () async {
              final picked = await showTimePicker(context: context, initialTime: _at);
              if (picked != null) setState(() => _at = picked);
            },
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48),
                foregroundColor: Palette.ink, side: const BorderSide(color: Palette.border),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
            child: Text('Started at ${clock(_startAt)}', style: const TextStyle(fontSize: 16)),
          ),
        ],
        if (running != null) ...[
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(color: Palette.field, borderRadius: BorderRadius.circular(12)),
            child: Row(children: [
              const Icon(Icons.schedule, size: 18, color: Palette.redDark),
              const SizedBox(width: 10),
              Expanded(child: Text(
                'This stops your ${widget.runningLabel ?? 'running'} timer at '
                '${duration(running.minutesAt(DateTime.now()))}.',
                style: const TextStyle(fontSize: 14, color: Palette.body))),
            ]),
          ),
        ],
        const SizedBox(height: 20),
        PillButton(label: 'Clock in for ${jobs[_job]!.toLowerCase()}', busy: _busy, onPressed: _submit),
      ],
    );
  }
}

class _JobRow extends StatelessWidget {
  const _JobRow({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      selected: selected,
      button: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          height: 56,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: selected ? Palette.redTint : Colors.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: selected ? Palette.red : const Color(0xFFEEEEEE),
                width: selected ? 1.5 : 1),
          ),
          child: Row(children: [
            Expanded(child: Text(label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600))),
            Container(
              width: 22, height: 22,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white,
                border: Border.all(color: selected ? Palette.red : Palette.check, width: selected ? 7 : 2),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
