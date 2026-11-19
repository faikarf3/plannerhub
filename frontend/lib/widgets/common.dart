import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../scope.dart';
import '../theme.dart';

/// Full-width pill button. `dark` = black (Save/Done), otherwise red (primary).
class PillButton extends StatelessWidget {
  const PillButton({super.key, required this.label, required this.onPressed, this.dark = false,
      this.icon, this.busy = false});

  final String label;
  final VoidCallback? onPressed;
  final bool dark;
  final IconData? icon;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final bg = dark ? Palette.ink : Palette.red;
    return SizedBox(
      height: 52,
      child: FilledButton(
        onPressed: busy ? null : onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: bg,
          disabledBackgroundColor: bg.withValues(alpha: 0.5),
          foregroundColor: Colors.white,
          shape: const StadiumBorder(),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        child: busy
            ? const SizedBox(width: 20, height: 20,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
            : Row(mainAxisSize: MainAxisSize.min, children: [
                if (icon != null) ...[Icon(icon, size: 18), const SizedBox(width: 8)],
                Text(label),
              ]),
      ),
    );
  }
}

/// Selectable option ("Work", "Today"): red outline + pale red when selected.
class OptionChip extends StatelessWidget {
  const OptionChip({super.key, required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? Palette.redTint : Colors.white,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: selected ? Palette.red : Palette.border,
                width: selected ? 1.5 : 1),
          ),
          child: Text(label, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500,
              color: selected ? Palette.redDark : Palette.body)),
        ),
      ),
    );
  }
}

/// Small grey label above a field or chip group.
class FieldLabel extends StatelessWidget {
  const FieldLabel(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(text, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600,
            color: Palette.muted)),
      );
}

/// Bottom sheet with the app's look; content scrolls and rises with the keyboard.
Future<T?> showPlannerSheet<T>(BuildContext context, WidgetBuilder builder) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (ctx) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(ctx).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
        child: builder(ctx),
      ),
    ),
  );
}

void showError(BuildContext context, Object error) {
  final message = error is ApiException ? error.message : 'Something went wrong.';
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// "Stopped Climbing at 3:24pm (1h 24m)" with an Undo button.
void showUndo(BuildContext context, ActionResult action, {VoidCallback? onChanged}) {
  final api = AppScope.of(context).api;
  final messenger = ScaffoldMessenger.of(context);
  messenger
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(action.summary),
      duration: const Duration(seconds: 6),
      action: SnackBarAction(
        label: 'Undo',
        onPressed: () async {
          try {
            await api.undo(action.actionId);
            onChanged?.call();
          } on ApiException catch (e) {
            messenger.showSnackBar(SnackBar(content: Text(e.message)));
          }
        },
      ),
    ));
}
