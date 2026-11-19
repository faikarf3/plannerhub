import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// After /log or /clarify: either the follow-up question, or what changed.
/// `onChanged` runs whenever data changed (applied, undone) so Today refreshes.
Future<void> showLogResult(BuildContext context, String said, LogResult result,
    {required VoidCallback onChanged}) async {
  if (result.clarify != null) {
    final next = await showPlannerSheet<(String, LogResult)>(
      context,
      (_) => _ClarifySheet(said: said, journalId: result.journalEntryId, clarify: result.clarify!),
    );
    if (next != null && context.mounted) {
      onChanged();
      await showLogResult(context, next.$1, next.$2, onChanged: onChanged);
    }
    return;
  }
  if (result.actions.isNotEmpty) onChanged();
  await showPlannerSheet<void>(context, (_) => _LoggedSheet(said: said, result: result, onChanged: onChanged));
}

class _YouSaid extends StatelessWidget {
  const _YouSaid(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('YOU SAID', style: sectionLabel()),
          const SizedBox(height: 8),
          Text('“$text”', style: const TextStyle(fontSize: 17, height: 1.45, color: Palette.body)),
        ],
      );
}

class _LoggedSheet extends StatefulWidget {
  const _LoggedSheet({required this.said, required this.result, required this.onChanged});
  final String said;
  final LogResult result;
  final VoidCallback onChanged;

  @override
  State<_LoggedSheet> createState() => _LoggedSheetState();
}

class _LoggedSheetState extends State<_LoggedSheet> {
  final _undone = <int>{};
  final _busy = <int>{};

  Future<void> _undo(ActionResult a) async {
    setState(() => _busy.add(a.actionId));
    try {
      await AppScope.of(context).api.undo(a.actionId);
      _undone.add(a.actionId);
      widget.onChanged();
    } on ApiException catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy.remove(a.actionId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _YouSaid(widget.said),
        const SizedBox(height: 20),
        if (r.actions.isEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(r.message, style: TextStyle(fontSize: 15,
                color: r.error != null ? Palette.redDark : Palette.muted)),
          ),
        for (final a in r.actions) _actionRow(a),
        if (r.error != null && r.actions.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text('Stopped: ${r.error}', style: const TextStyle(color: Palette.redDark)),
          ),
        const SizedBox(height: 22),
        PillButton(label: 'Done', dark: true, onPressed: () => Navigator.pop(context)),
      ],
    );
  }

  Widget _actionRow(ActionResult a) {
    final undone = _undone.contains(a.actionId);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.line))),
      child: Row(children: [
        Container(
          width: 32, height: 32,
          decoration: BoxDecoration(color: undone ? Palette.grey : Palette.redTint,
              shape: BoxShape.circle),
          child: Icon(undone ? Icons.undo : Icons.check, size: 16,
              color: undone ? Palette.muted : Palette.red),
        ),
        const SizedBox(width: 14),
        Expanded(child: Text(a.summary, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500,
            color: undone ? Palette.muted : Palette.ink,
            decoration: undone ? TextDecoration.lineThrough : null))),
        if (undone)
          const Text('Undone', style: TextStyle(color: Palette.muted, fontSize: 14))
        else
          TextButton(
            onPressed: _busy.contains(a.actionId) ? null : () => _undo(a),
            style: TextButton.styleFrom(foregroundColor: Palette.redDark, minimumSize: const Size(44, 44)),
            child: const Text('Undo', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
          ),
      ]),
    );
  }
}

class _ClarifySheet extends StatefulWidget {
  const _ClarifySheet({required this.said, required this.journalId, required this.clarify});
  final String said;
  final int journalId;
  final Clarify clarify;

  @override
  State<_ClarifySheet> createState() => _ClarifySheetState();
}

class _ClarifySheetState extends State<_ClarifySheet> {
  final _answer = TextEditingController();
  bool _busy = false;

  Future<void> _send(String answer) async {
    if (answer.trim().isEmpty || _busy) return;
    setState(() => _busy = true);
    try {
      final result = await AppScope.of(context).api.clarify(widget.journalId, answer.trim());
      if (mounted) Navigator.pop(context, ('${widget.said} — $answer', result));
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        showError(context, e);
      }
    }
  }

  @override
  void dispose() {
    _answer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _YouSaid(widget.said),
        const SizedBox(height: 20),
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: Palette.redTint, borderRadius: BorderRadius.circular(18)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(children: [
                Icon(Icons.schedule, size: 16, color: Palette.redDark),
                SizedBox(width: 8),
                Text('One thing first', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600,
                    color: Palette.redDark)),
              ]),
              const SizedBox(height: 12),
              Text(widget.clarify.question, style: const TextStyle(fontSize: 20,
                  fontWeight: FontWeight.w600, letterSpacing: -0.2)),
              if (widget.clarify.options.isNotEmpty) ...[
                const SizedBox(height: 14),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final o in widget.clarify.options)
                    OptionChip(label: o, selected: false, onTap: () => _send(o)),
                ]),
              ],
            ],
          ),
        ),
        const SizedBox(height: 18),
        Row(children: [
          Expanded(
            child: TextField(
              controller: _answer,
              autofocus: widget.clarify.options.isEmpty,
              textInputAction: TextInputAction.send,
              onSubmitted: _send,
              decoration: const InputDecoration(hintText: 'Type your answer…'),
            ),
          ),
          const SizedBox(width: 10),
          IconButton.filled(
            onPressed: _busy ? null : () => _send(_answer.text),
            style: IconButton.styleFrom(backgroundColor: Palette.red, fixedSize: const Size(52, 52)),
            icon: _busy
                ? const SizedBox(width: 18, height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.arrow_upward, color: Colors.white),
            tooltip: 'Send answer',
          ),
        ]),
        const SizedBox(height: 14),
        const Text('Nothing is saved until you answer. Your words are kept in the journal.',
            textAlign: TextAlign.center, style: TextStyle(fontSize: 13, color: Palette.muted)),
      ],
    );
  }
}
