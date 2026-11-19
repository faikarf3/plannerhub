import 'package:flutter/material.dart';

import '../format.dart';
import '../theme.dart';

DateTime atTime(DateTime day, TimeOfDay t) => DateTime(day.year, day.month, day.day, t.hour, t.minute);

/// End on the same day as `start`, or the next day when it's not after it (overnight).
DateTime endAfter(DateTime start, TimeOfDay end) {
  final e = atTime(start, end);
  return e.isAfter(start) ? e : e.add(const Duration(days: 1));
}

/// Labelled time button ("Start  2:00 PM") that opens the time picker.
class TimeField extends StatelessWidget {
  const TimeField({super.key, required this.label, required this.value, required this.onChanged});

  final String label;
  final DateTime value;
  final ValueChanged<TimeOfDay> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Palette.muted)),
      const SizedBox(height: 6),
      Semantics(
        button: true,
        label: '$label ${clock(value)}',
        excludeSemantics: true,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () async {
            final picked = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(value));
            if (picked != null) onChanged(picked);
          },
          child: Container(
            height: 48,
            padding: const EdgeInsets.symmetric(horizontal: 14),
            alignment: Alignment.centerLeft,
            decoration: BoxDecoration(color: Palette.field, borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Palette.border)),
            child: Text(clock(value), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500)),
          ),
        ),
      ),
    ]);
  }
}
