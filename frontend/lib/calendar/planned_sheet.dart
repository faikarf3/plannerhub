import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../format.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/dashed_box.dart';
import '../widgets/time_field.dart';

/// One planned block from a repeat: move it, mark it done, or skip it, for this
/// week only. The repeat itself is edited on the Schedule screen.
class PlannedSheet extends StatefulWidget {
  const PlannedSheet({super.key, required this.block});
  final PlannedBlock block;

  @override
  State<PlannedSheet> createState() => _PlannedSheetState();
}

class _PlannedSheetState extends State<PlannedSheet> {
  late DateTime _start = widget.block.startedAt;
  late DateTime _end = widget.block.endedAt;
  bool _busy = false;

  PlannedBlock get _b => widget.block;
  bool get _changed => _start != _b.startedAt || _end != _b.endedAt;

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

  @override
  Widget build(BuildContext context) {
    final started = !_start.isAfter(DateTime.now());
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Align(
        alignment: Alignment.centerLeft,
        child: DashedBox(
          color: Palette.faint,
          radius: 10,
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 10, vertical: 3),
            child: Text('Planned', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600,
                color: Palette.body)),
          ),
        ),
      ),
      const SizedBox(height: 6),
      Text(_b.label, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
      Text('${dayHeading(_b.startedAt)} · repeats weekly',
          style: const TextStyle(fontSize: 14, color: Palette.muted)),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(child: TimeField(label: 'Start', value: _start, onChanged: (t) => setState(() {
              final length = _end.difference(_start);
              _start = atTime(_start, t);
              _end = _start.add(length); // moving the start keeps the length
            }))),
        const SizedBox(width: 12),
        Expanded(child: TimeField(label: 'End', value: _end,
            onChanged: (t) => setState(() => _end = endAfter(_start, t)))),
      ]),
      const SizedBox(height: 10),
      const Text('Changes here apply to this week only.',
          style: TextStyle(fontSize: 13, color: Palette.muted)),
      const SizedBox(height: 22),
      SizedBox(
        height: 52,
        child: OutlinedButton.icon(
          onPressed: _busy || !started
              ? null
              : () => _run((api) => api.confirmOccurrence(_b,
                  start: _changed ? _start : null, end: _changed ? _end : null)),
          icon: const Icon(Icons.check, size: 18),
          label: Text(started ? 'Mark as done' : 'Mark as done once it starts'),
          style: OutlinedButton.styleFrom(
            foregroundColor: Palette.redDark, backgroundColor: Palette.redTint,
            side: const BorderSide(color: Palette.redBorder), shape: const StadiumBorder(),
            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        ),
      ),
      const SizedBox(height: 10),
      PillButton(label: 'Move this week', dark: true, busy: _busy,
          onPressed: _changed ? () => _run((api) => api.moveOccurrence(_b, _start, _end)) : null),
      TextButton(
        onPressed: _busy ? null : () => _run((api) => api.skipOccurrence(_b)),
        style: TextButton.styleFrom(foregroundColor: Palette.redDark, minimumSize: const Size.fromHeight(44)),
        child: const Text('Skip this week', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
      ),
    ]);
  }
}
