import 'package:flutter/material.dart';

import '../theme.dart';

/// Two-or-more option switch on a grey track ("Now | Earlier").
class Segmented<T> extends StatelessWidget {
  const Segmented({super.key, required this.options, required this.value, required this.onChanged});

  final Map<T, String> options;
  final T value;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Palette.grey, borderRadius: BorderRadius.circular(14)),
      child: Row(children: [
        for (final entry in options.entries)
          Expanded(
            child: Semantics(
              button: true,
              selected: entry.key == value,
              child: GestureDetector(
                onTap: () => onChanged(entry.key),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  height: 40,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: entry.key == value ? Colors.white : Colors.transparent,
                    borderRadius: BorderRadius.circular(10),
                    boxShadow: entry.key == value
                        ? const [BoxShadow(color: Color(0x14000000), blurRadius: 3, offset: Offset(0, 1))]
                        : null,
                  ),
                  child: Text(entry.value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600,
                      color: entry.key == value ? Palette.ink : Palette.muted)),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}
