import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../widgets/common.dart';

/// Start a plain (non-work) timer. Work time goes through Clock in, which needs a job.
class StartTimerSheet extends StatefulWidget {
  const StartTimerSheet({super.key, required this.categories});
  final List<Category> categories;

  @override
  State<StartTimerSheet> createState() => _StartTimerSheetState();
}

class _StartTimerSheetState extends State<StartTimerSheet> {
  int? _categoryId;
  bool _busy = false;

  Future<void> _start() async {
    setState(() => _busy = true);
    try {
      final action = await AppScope.of(context).api.startTimer(categoryId: _categoryId!);
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
    final options = widget.categories.where((c) => !c.isWork).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text('Start a timer', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -0.4)),
        const SizedBox(height: 6),
        const Text('For paid work, use Clock in.', style: TextStyle(fontSize: 14, color: Color(0xFF6B6B73))),
        const SizedBox(height: 18),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final c in options)
            OptionChip(label: c.name, selected: c.id == _categoryId,
                onTap: () => setState(() => _categoryId = c.id)),
        ]),
        const SizedBox(height: 22),
        PillButton(label: 'Start', icon: Icons.play_arrow_rounded, busy: _busy,
            onPressed: _categoryId == null ? null : _start),
      ],
    );
  }
}
