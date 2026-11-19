import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// "Log something…" box. The round button sends when there's text, and is the
/// mic when empty (for now it opens the keyboard, whose mic key dictates).
class LogBar extends StatefulWidget {
  const LogBar({super.key, required this.onLogged});
  final Future<void> Function(String said, LogResult result) onLogged;

  @override
  State<LogBar> createState() => _LogBarState();
}

class _LogBarState extends State<LogBar> {
  final _text = TextEditingController();
  final _focus = FocusNode();
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _text.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final said = _text.text.trim();
    if (said.isEmpty || _busy) return;
    setState(() => _busy = true);
    final LogResult result;
    try {
      result = await AppScope.of(context).api.log(said);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        showError(context, e);
      }
      return;
    }
    if (!mounted) return;
    _text.clear();
    _focus.unfocus();
    setState(() => _busy = false); // ready again before the result sheet opens
    await widget.onLogged(said, result);
  }

  @override
  Widget build(BuildContext context) {
    final hasText = _text.text.trim().isNotEmpty;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Palette.line)),
      ),
      child: Row(children: [
        Expanded(
          child: TextField(
            controller: _text,
            focusNode: _focus,
            enabled: !_busy,
            textInputAction: TextInputAction.send,
            textCapitalization: TextCapitalization.sentences,
            onSubmitted: (_) => _send(),
            decoration: const InputDecoration(hintText: 'Log something…'),
          ),
        ),
        const SizedBox(width: 10),
        SizedBox(
          width: 52,
          height: 52,
          child: IconButton.filled(
            tooltip: hasText ? 'Log it' : 'Speak (uses the keyboard mic for now)',
            onPressed: _busy ? null : (hasText ? _send : () => _focus.requestFocus()),
            style: IconButton.styleFrom(backgroundColor: Palette.red,
                disabledBackgroundColor: Palette.red.withValues(alpha: 0.6)),
            icon: _busy
                ? const SizedBox(width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Icon(hasText ? Icons.arrow_upward : Icons.mic_none_rounded, color: Colors.white),
          ),
        ),
      ]),
    );
  }
}
